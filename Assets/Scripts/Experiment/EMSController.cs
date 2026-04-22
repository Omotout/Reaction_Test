using System;
using System.Collections.Concurrent;
using System.Diagnostics;
using System.IO.Ports;
using System.Threading;
using UnityEngine;
using Debug = UnityEngine.Debug;

namespace ReactionTest.Experiment
{
    /// <summary>
    /// EMS制御クラス
    /// Arduino DUE + L298N (H-Bridge) を使用した2相性パルス刺激を制御
    /// 
    /// Arduinoコマンド仕様:
    /// - "L": 左チャンネル発火（撓屈）
    /// - "R": 右チャンネル発火（尺屈）
    /// - "Wnn": パルス幅設定 (20-1000 µs)
    /// - "Cnn": パルス連射回数 (1-100)
    /// - "Bnn": バーストサイクル数 (1-20)
    /// - "Innnn": パルス間隔 (0-100000 µs)
    /// </summary>
    public class EMSController : MonoBehaviour
    {
        [Header("Hardware Settings")]
        [Tooltip("Arduinoのポート名 (例: COM5, /dev/tty.usbmodem...)")]
        [SerializeField] private string portName = "COM5";
        [SerializeField] private int baudRate = 9600;

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

        // シリアル通信
        private SerialPort _serialPort;
        private ConcurrentQueue<string> _serialQueue = new ConcurrentQueue<string>();
        private Thread _serialThread;
        private volatile bool _serialRunning = false;

        // パラメータ変更検知用
        private int _lastSentWidth;
        private int _lastSentCount;
        private int _lastSentBurst;
        private int _lastSentInterval;

        // 接続状態
        private bool _isConnected = false;

        // ── 安全機構 ──
        private readonly Stopwatch _refractoryWatch = Stopwatch.StartNew();
        private long _lastFireMs = -1000;
        private int _sessionFireCount = 0;
        private bool _emergencyStopped = false;

        [Header("Safety")]
        [Tooltip("連続発火の最小間隔（ms）")]
        [SerializeField] private int refractoryPeriodMs = 200;
        [Tooltip("1セッションあたりの最大発火回数")]
        [SerializeField] private int maxFiresPerSession = 500;

        public bool IsConnected => _isConnected;
        public bool IsEnabled => emsEnabled;

        private void Start()
        {
            SetupSerial();
            if (_isConnected)
            {
                SendEMSConfig();
            }
        }

        private void Update()
        {
            // テストトリガーの監視
            HandleTestTriggers();

            // 設定変更の監視（インスペクタで数値を変えたら即送信）
            if (_isConnected && HasConfigChanged())
            {
                SendEMSConfig();
            }
        }

        private void OnDestroy()
        {
            CleanupResources();
        }

        private void OnApplicationQuit()
        {
            CleanupResources();
        }

        /// <summary>
        /// 左チャンネル（撓屈）のEMS発火
        /// </summary>
        public void TriggerLeft()
        {
            if (!CanFire()) return;
            RecordFire();
            EnqueueCommand("L");
            UnityEngine.Debug.Log($"EMS Trigger: Left (#{_sessionFireCount})");
        }

        /// <summary>
        /// 右チャンネル（尺屈）のEMS発火
        /// </summary>
        public void TriggerRight()
        {
            if (!CanFire()) return;
            RecordFire();
            EnqueueCommand("R");
            UnityEngine.Debug.Log($"EMS Trigger: Right (#{_sessionFireCount})");
        }

        /// <summary>
        /// 緊急停止: EMS即時無効化。Escキーから呼ばれる。
        /// </summary>
        public void EmergencyStop()
        {
            _emergencyStopped = true;
            emsEnabled = false;
            UnityEngine.Debug.LogError($"EMS: EMERGENCY STOP activated. Total fires this session: {_sessionFireCount}");
        }

        /// <summary>
        /// 安全チェック: 不応期・最大発火回数・緊急停止
        /// </summary>
        private bool CanFire()
        {
            if (_emergencyStopped || !emsEnabled) return false;

            if (_sessionFireCount >= maxFiresPerSession)
            {
                UnityEngine.Debug.LogError($"EMS: Session fire limit ({maxFiresPerSession}) reached. Disabling.");
                emsEnabled = false;
                return false;
            }

            long now = _refractoryWatch.ElapsedMilliseconds;
            long elapsed = now - _lastFireMs;
            if (elapsed < refractoryPeriodMs)
            {
                UnityEngine.Debug.LogWarning($"EMS: Refractory period ({elapsed}ms < {refractoryPeriodMs}ms). Blocked.");
                return false;
            }

            return true;
        }

        private void RecordFire()
        {
            _lastFireMs = _refractoryWatch.ElapsedMilliseconds;
            _sessionFireCount++;
        }

        /// <summary>
        /// チャンネル指定でEMS発火
        /// </summary>
        public void Trigger(UserAction action)
        {
            switch (action)
            {
                case UserAction.Left:
                    TriggerLeft();
                    break;
                case UserAction.Right:
                    TriggerRight();
                    break;
            }
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

            if (_isConnected)
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
            EnqueueCommand($"W{pulseWidth}");
            EnqueueCommand($"C{pulseCount}");
            EnqueueCommand($"B{burstCount}");
            EnqueueCommand($"I{pulseInterval}");

            _lastSentWidth = pulseWidth;
            _lastSentCount = pulseCount;
            _lastSentBurst = burstCount;
            _lastSentInterval = pulseInterval;

            Debug.Log($"EMS Config sent: W={pulseWidth}µs, C={pulseCount}, B={burstCount}, I={pulseInterval}µs");
        }

        private void EnqueueCommand(string command)
        {
            _serialQueue.Enqueue(command);
        }

        private void SetupSerial()
        {
            try
            {
                _serialPort = new SerialPort(portName, baudRate);
                _serialPort.Open();
                _serialPort.ReadTimeout = 50;
                _isConnected = true;
                Debug.Log($"EMS Controller: Serial port {portName} connected");

                // バックグラウンドスレッドでシリアル送信を処理
                _serialRunning = true;
                _serialThread = new Thread(SerialWorker);
                _serialThread.IsBackground = true;
                _serialThread.Start();
            }
            catch (Exception e)
            {
                _isConnected = false;
                Debug.LogWarning($"EMS Controller: Arduino not connected (simulation mode) - {e.Message}");
            }
        }

        private void SerialWorker()
        {
            while (_serialRunning)
            {
                if (_serialQueue.TryDequeue(out string message))
                {
                    try
                    {
                        if (_serialPort != null && _serialPort.IsOpen)
                        {
                            _serialPort.WriteLine(message);
                        }
                    }
                    catch (Exception e)
                    {
                        Debug.LogWarning($"EMS Controller: Serial send error - {e.Message}");
                    }
                }
                else
                {
                    Thread.Sleep(1);
                }
            }
        }

        private void CleanupResources()
        {
            // シリアルスレッド停止
            _serialRunning = false;
            if (_serialThread != null && _serialThread.IsAlive)
            {
                _serialThread.Join(500);
            }

            // シリアルポートを閉じる
            if (_serialPort != null && _serialPort.IsOpen)
            {
                _serialPort.Close();
            }

            Debug.Log("EMS Controller: Resources cleaned up");
        }
    }
}
