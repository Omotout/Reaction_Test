using System.Diagnostics;
using UnityEngine;
using Debug = UnityEngine.Debug;

namespace ReactionTest.Experiment
{
    /// <summary>
    /// EMS制御クラス（安全層）。
    /// シリアルは <see cref="ArduinoLink"/>（単一所有者）へ委譲し、本クラスは発火の安全機構
    /// （不応期・最大発火回数・緊急停止）と波形パラメータ（強度）の管理に専念する。
    /// 安全判定は純粋ロジックの <see cref="EmsSafetyGate"/> に委譲。
    ///
    /// 送信コマンドは ArduinoProtocol 経由（integrated_full系）:
    /// - 手動発火: "EMS:L" / "EMS:R"
    /// - 波形設定: "EMSCFG,&lt;width&gt;,&lt;count&gt;,&lt;burst&gt;,&lt;interval&gt;"
    /// </summary>
    public class EMSController : MonoBehaviour
    {
        [Header("Link")]
        [Tooltip("シリアル所有者。未設定ならシーンから自動取得。")]
        [SerializeField] private ArduinoLink arduinoLink;

        [Header("EMS Config (Biphasic Pulse)")]
        [Tooltip("EMS刺激を有効にする")]
        [SerializeField] private bool emsEnabled = true;

        [Range(20, 1000)]
        [Tooltip("パルス幅 (µs)。単一パルスの場合は50µs前後が鋭い刺激")]
        [SerializeField] private int pulseWidth = 50;

        [Range(1, 100)]
        [Tooltip("刺激の連射回数。単一パルスなら1、バースト波なら5〜50")]
        [SerializeField] private int pulseCount = 1;

        [Range(1, 20)]
        [Tooltip("1回の繰り返しに含まれる2相性サイクル数")]
        [SerializeField] private int burstCount = 3;

        [Range(0, 100000)]
        [Tooltip("連射時のパルス間隔 (µs)。Count=1の場合は無視")]
        [SerializeField] private int pulseInterval = 40000;

        [Header("Test Trigger (Calibration)")]
        [Tooltip("チェックを入れると左用の刺激をテスト発火")]
        [SerializeField] private bool testTriggerLeft = false;
        [Tooltip("チェックを入れると右用の刺激をテスト発火")]
        [SerializeField] private bool testTriggerRight = false;

        [Header("Safety")]
        [Tooltip("連続発火の最小間隔（ms）")]
        [SerializeField] private int refractoryPeriodMs = 200;
        [Tooltip("1セッションあたりの最大発火回数")]
        [SerializeField] private int maxFiresPerSession = 500;

        // パラメータ変更検知用
        private int _lastSentWidth;
        private int _lastSentCount;
        private int _lastSentBurst;
        private int _lastSentInterval;

        // 安全機構（時刻源 + 純粋判定ロジック）
        private readonly Stopwatch _clock = Stopwatch.StartNew();
        private EmsSafetyGate _gate;

        public bool IsConnected => arduinoLink != null && arduinoLink.IsConnected;
        public bool IsEnabled => emsEnabled;

        private void Awake()
        {
            _gate = new EmsSafetyGate(refractoryPeriodMs, maxFiresPerSession);
        }

        private void Start()
        {
            if (arduinoLink == null)
            {
                arduinoLink = FindFirstObjectByType<ArduinoLink>();
            }
            if (arduinoLink == null)
            {
                Debug.LogWarning("EMS Controller: ArduinoLink が見つかりません。EMS発火は無効です。");
                return;
            }
            if (IsConnected)
            {
                SendEMSConfig();
            }
        }

        private void Update()
        {
            // テストトリガーの監視
            HandleTestTriggers();

            // 設定変更の監視（インスペクタで数値を変えたら即送信）
            if (IsConnected && HasConfigChanged())
            {
                SendEMSConfig();
            }
        }

        /// <summary>
        /// 左チャンネル（撓屈）のEMS発火
        /// </summary>
        public void TriggerLeft() => Fire(UserAction.Left);

        /// <summary>
        /// 右チャンネル（尺屈）のEMS発火
        /// </summary>
        public void TriggerRight() => Fire(UserAction.Right);

        /// <summary>
        /// チャンネル指定でEMS発火
        /// </summary>
        public void Trigger(UserAction action)
        {
            if (action == UserAction.Left || action == UserAction.Right)
            {
                Fire(action);
            }
        }

        /// <summary>
        /// 安全チェックを通過したら ArduinoLink 経由で手動EMSコマンドを送る。
        /// </summary>
        private void Fire(UserAction side)
        {
            if (!emsEnabled) return; // 無効・緊急停止後はここで弾く（ログなし＝従来挙動）

            if (arduinoLink == null)
            {
                Debug.LogWarning("EMS: ArduinoLink 未設定。発火できません。");
                return;
            }

            // インスペクタ値の実行時変更を反映
            _gate.RefractoryPeriodMs = refractoryPeriodMs;
            _gate.MaxFiresPerSession = maxFiresPerSession;

            switch (_gate.TryFire(_clock.ElapsedMilliseconds))
            {
                case EmsSafetyGate.Result.Allowed:
                    arduinoLink.SendEmsManual(side);
                    Debug.Log($"EMS Trigger: {side} (#{_gate.FireCount})");
                    break;
                case EmsSafetyGate.Result.LimitReached:
                    Debug.LogError($"EMS: Session fire limit ({maxFiresPerSession}) reached. Disabling.");
                    emsEnabled = false;
                    break;
                case EmsSafetyGate.Result.Refractory:
                    Debug.LogWarning($"EMS: Refractory period (< {refractoryPeriodMs}ms). Blocked.");
                    break;
                case EmsSafetyGate.Result.EmergencyStopped:
                    // 既に停止済み。何もしない。
                    break;
            }
        }

        /// <summary>
        /// 緊急停止: EMS即時無効化。Escキーから呼ばれる。
        /// </summary>
        public void EmergencyStop()
        {
            _gate?.EmergencyStop();
            emsEnabled = false;
            int fired = _gate != null ? _gate.FireCount : 0;
            Debug.LogError($"EMS: EMERGENCY STOP activated. Total fires this session: {fired}");
        }

        /// <summary>
        /// EMS有効/無効を設定
        /// </summary>
        public void SetEnabled(bool enabled)
        {
            emsEnabled = enabled;
        }

        /// <summary>
        /// EMSパラメータを一括設定
        /// </summary>
        public void SetConfig(int width, int count, int burst, int interval)
        {
            pulseWidth = Mathf.Clamp(width, 20, 1000);
            pulseCount = Mathf.Clamp(count, 1, 100);
            burstCount = Mathf.Clamp(burst, 1, 20);
            pulseInterval = Mathf.Clamp(interval, 0, 100000);

            if (IsConnected)
            {
                SendEMSConfig();
            }
        }

        private void HandleTestTriggers()
        {
            if (testTriggerLeft)
            {
                TriggerLeft();
                testTriggerLeft = false;
            }
            if (testTriggerRight)
            {
                TriggerRight();
                testTriggerRight = false;
            }
        }

        private bool HasConfigChanged()
        {
            return _lastSentWidth != pulseWidth ||
                   _lastSentCount != pulseCount ||
                   _lastSentBurst != burstCount ||
                   _lastSentInterval != pulseInterval;
        }

        private void SendEMSConfig()
        {
            if (arduinoLink == null) return;

            arduinoLink.SendEmsConfig(pulseWidth, pulseCount, burstCount, pulseInterval);

            _lastSentWidth = pulseWidth;
            _lastSentCount = pulseCount;
            _lastSentBurst = burstCount;
            _lastSentInterval = pulseInterval;

            Debug.Log($"EMS Config sent: W={pulseWidth}µs, C={pulseCount}, B={burstCount}, I={pulseInterval}µs");
        }
    }
}
