// ========================================================================
// V3: CRT特化 + EMSLatencyフェーズ対応
// - TaskType引数を全メソッドから削除
// - RunSingleTrial: CRT固定（ターゲット左右ランダム、色で表現）
// - RunEMSLatencyTrial: 視覚刺激なし、EMS発火→キー押下のレイテンシ測定
// - フェーズごとの試行数をインスペクターから設定可能
// - 【重要】エラー試行もデータとして返す（破棄しない）
// ========================================================================

using System;
using System.Collections;
using System.Diagnostics;
using UnityEngine;
using UnityEngine.UI;
using UnityEngine.InputSystem;

namespace ReactionTest.Experiment
{
    public class TrialEngine : MonoBehaviour
    {
        [Header("Stimulus")]
        [SerializeField] private Image stimulusImage;
        [SerializeField] private Color leftColor = Color.green;   // 左ターゲット色
        [SerializeField] private Color rightColor = Color.red;    // 右ターゲット色
        [SerializeField] private float minPreStimulusWaitSec = 0.8f;
        [SerializeField] private float maxPreStimulusWaitSec = 1.6f;
        [SerializeField] private float responseWindowSec = 1.0f;

        [Header("Feedback")]
        [SerializeField] private Text feedbackText;
        [SerializeField] private bool showReactionTimeFeedback = true;
        [SerializeField] private float feedbackDurationSec = 0.8f;

        [Header("Phase Trial Counts (Inspector で変更可)")]
        [SerializeField] private int practiceTrials = 15;
        [SerializeField] private int baselineTrials = 40;
        [SerializeField] private int emsLatencyTrialsPerSide = 15;
        [SerializeField] private int trainingTrials = 40;
        [SerializeField] private int postTestTrials = 40;



        [Header("EMS Latency Phase")]
        [Tooltip("EMSLatencyフェーズのEMS発火間隔（秒）")]
        [SerializeField] private float emsLatencyIntervalMin = 2.0f;
        [SerializeField] private float emsLatencyIntervalMax = 4.0f;

        [Header("EMS")]
        [SerializeField] private EMSController emsController;

        // 高精度タイマー
        private Stopwatch _reactionStopwatch = new Stopwatch();

        // 緊急停止フラグ
        private bool _isAborted = false;
        public bool IsAborted => _isAborted;
        public void ResetAbort() => _isAborted = false;

        // ============================================================
        // Public accessors for ExperimentOrchestrator
        // ============================================================

        public int PracticeTrials => practiceTrials;
        public int BaselineTrials => baselineTrials;
        public int EMSLatencyTrialsPerSide => emsLatencyTrialsPerSide;
        public int TrainingTrials => trainingTrials;
        public int PostTestTrials => postTestTrials;



        public bool ShowReactionTimeFeedback
        {
            get => showReactionTimeFeedback;
            set => showReactionTimeFeedback = value;
        }

        private void Awake()
        {
            // 高精度タイミングのためフレームレートを最大化
            int refreshRate = Screen.currentResolution.refreshRate;
            int targetFps = Mathf.Max(refreshRate * 2, 120);
            Application.targetFrameRate = targetFps;
            QualitySettings.vSyncCount = 0;
            UnityEngine.Debug.Log($"TrialEngine: Display {refreshRate}Hz → Target FPS: {targetFps}");
        }

        private void Start()
        {
            // 初期状態で刺激を非表示
            if (stimulusImage != null)
            {
                stimulusImage.gameObject.SetActive(false);
            }
            if (feedbackText != null)
            {
                feedbackText.gameObject.SetActive(false);
            }
        }

        public void SetEMSController(EMSController controller)
        {
            emsController = controller;
        }

        // ============================================================
        // CRT試行（Practice / Baseline / Calibration / Training / PostTest）
        // ============================================================

        /// <summary>
        /// 1試行を実行（CRT: 左右2択）
        /// TaskType引数は廃止 — 常にCRTとして動作
        /// </summary>
        /// <param name="forcedTargetSide">
        /// UserAction.None（デフォルト）= ランダムにターゲット決定。
        /// Left/Right を指定すると、そのサイドをターゲットとして強制する。
        /// Calibrationフェーズで、ターゲット側に応じたEMS発火タイミングを
        /// 事前計算するために使用する。
        /// </param>
        public IEnumerator RunSingleTrial(
            PhaseType phase,
            int trialIndex,
            EMSDecision emsDecision,
            Action<TrialRecord, UserAction> onCompleted,
            UserAction forcedTargetSide = UserAction.None)
        {
            if (stimulusImage == null)
            {
                UnityEngine.Debug.LogError("TrialEngine: stimulusImage is not assigned.");
                yield break;
            }

            // フィードバックを非表示
            if (feedbackText != null)
            {
                feedbackText.gameObject.SetActive(false);
            }

            stimulusImage.gameObject.SetActive(false);
            float preWait = UnityEngine.Random.Range(minPreStimulusWaitSec, maxPreStimulusWaitSec);
            yield return new WaitForSeconds(preWait);

            // ターゲット決定: 強制指定があればそれを使用、なければランダム
            UserAction targetSide = forcedTargetSide != UserAction.None
                ? forcedTargetSide
                : TaskRule.PickTargetSide();

            // 色で表現（緑=左、赤=右）
            stimulusImage.color = targetSide == UserAction.Left ? leftColor : rightColor;
            stimulusImage.gameObject.SetActive(true);

            // 高精度タイマーをリセット・開始
            _reactionStopwatch.Reset();
            _reactionStopwatch.Start();

            if (emsDecision.Enabled)
            {
                StartCoroutine(DispatchEMS(emsDecision.FireTimingMs, targetSide));
            }

            UserAction action = UserAction.None;
            double reactionTimeMs = -1.0;
            
            var mouse = Mouse.current;
            var keyboard = Keyboard.current;

            while (_reactionStopwatch.Elapsed.TotalSeconds < responseWindowSec)
            {
                // 緊急停止: Escapeキー
                if (keyboard != null && keyboard.escapeKey.wasPressedThisFrame)
                {
                    _isAborted = true;
                    if (emsController != null) emsController.EmergencyStop();
                    UnityEngine.Debug.LogError("TrialEngine: ABORT requested (Escape key)");
                    break;
                }

                if (mouse != null)
                {
                    if (mouse.leftButton.wasPressedThisFrame)
                    {
                        action = UserAction.Left;
                        reactionTimeMs = _reactionStopwatch.Elapsed.TotalMilliseconds;
                        break;
                    }

                    if (mouse.rightButton.wasPressedThisFrame)
                    {
                        action = UserAction.Right;
                        reactionTimeMs = _reactionStopwatch.Elapsed.TotalMilliseconds;
                        break;
                    }
                }

                yield return null;
            }

            _reactionStopwatch.Stop();
            stimulusImage.gameObject.SetActive(false);

            bool isCorrect = TaskRule.Evaluate(targetSide, action, out ErrorType errorType);

            // フィードバック表示
            if (showReactionTimeFeedback && feedbackText != null)
            {
                yield return ShowFeedback(reactionTimeMs, isCorrect, errorType);
            }

            // 【重要】エラー試行も記録する（TrialRecordのSubjectId/Group/AgencyLikertはOrchestrator側で設定）
            TrialRecord record = new TrialRecord
            {
                Phase = phase,
                TrialNumber = trialIndex,
                TargetSide = targetSide,
                ResponseSide = action,
                IsCorrect = isCorrect,
                ReactionTimeMs = (float)reactionTimeMs,
                EMSOffsetMs = emsDecision.OffsetMs,           // 速めたい量
                EMSFireTimingMs = emsDecision.FireTimingMs,   // 実発火タイミング
                AgencyLikert = 0,  // Calibrationフェーズ以外は0
                Timestamp = DateTime.UtcNow.ToString("o")
            };

            onCompleted?.Invoke(record, targetSide);
        }

        // ============================================================
        // EMSLatency試行（視覚刺激なし、EMS→キー押下のレイテンシ測定）
        // ============================================================

        /// <summary>
        /// EMSLatencyフェーズ用: 視覚刺激なし、一定間隔でEMSを発火し、
        /// 通電開始から実際にキーが押し込まれるまでのミリ秒数を測定する
        /// </summary>
        /// <param name="side">EMS発火チャンネル (Left / Right)</param>
        /// <param name="trialIndex">試行番号</param>
        /// <param name="onCompleted">完了コールバック（TrialRecord）</param>
        public IEnumerator RunEMSLatencyTrial(
            UserAction side,
            int trialIndex,
            Action<TrialRecord> onCompleted)
        {
            // 視覚刺激は表示しない
            if (stimulusImage != null)
            {
                stimulusImage.gameObject.SetActive(false);
            }
            if (feedbackText != null)
            {
                feedbackText.gameObject.SetActive(false);
            }

            // ランダムな待機（被験者が予測できないように）
            float preWait = UnityEngine.Random.Range(emsLatencyIntervalMin, emsLatencyIntervalMax);
            yield return new WaitForSeconds(preWait);

            // EMS発火と同時に高精度タイマー開始
            _reactionStopwatch.Reset();
            _reactionStopwatch.Start();

            if (emsController != null)
            {
                emsController.Trigger(side);
            }
            else
            {
                UnityEngine.Debug.Log($"[EMS Simulation] Latency trial: {side}");
            }

            UserAction action = UserAction.None;
            double reactionTimeMs = -1.0;

            var mouse = Mouse.current;
            var keyboard = Keyboard.current;

            // キー押下を待つ（タイムアウト付き）
            while (_reactionStopwatch.Elapsed.TotalSeconds < responseWindowSec)
            {
                // 緊急停止
                if (keyboard != null && keyboard.escapeKey.wasPressedThisFrame)
                {
                    _isAborted = true;
                    if (emsController != null) emsController.EmergencyStop();
                    UnityEngine.Debug.LogError("TrialEngine: ABORT requested (Escape key)");
                    break;
                }

                if (mouse != null)
                {
                    if (mouse.leftButton.wasPressedThisFrame)
                    {
                        action = UserAction.Left;
                        reactionTimeMs = _reactionStopwatch.Elapsed.TotalMilliseconds;
                        break;
                    }

                    if (mouse.rightButton.wasPressedThisFrame)
                    {
                        action = UserAction.Right;
                        reactionTimeMs = _reactionStopwatch.Elapsed.TotalMilliseconds;
                        break;
                    }
                }

                yield return null;
            }

            _reactionStopwatch.Stop();

            // フィードバック表示
            if (showReactionTimeFeedback && feedbackText != null && reactionTimeMs > 0)
            {
                feedbackText.text = $"{reactionTimeMs:F0} ms";
                feedbackText.color = Color.cyan;
                feedbackText.gameObject.SetActive(true);
                yield return new WaitForSeconds(feedbackDurationSec);
                feedbackText.gameObject.SetActive(false);
            }

            TrialRecord record = new TrialRecord
            {
                Phase = PhaseType.EMSLatency,
                TrialNumber = trialIndex,
                TargetSide = side,           // EMS発火チャンネル
                ResponseSide = action,
                IsCorrect = action == side,  // 正しい側を押したか
                ReactionTimeMs = (float)reactionTimeMs,
                EMSOffsetMs = 0f,            // 刺激提示と同時にEMS発火するため概念的に0
                EMSFireTimingMs = 0f,
                AgencyLikert = 0,
                Timestamp = DateTime.UtcNow.ToString("o")
            };

            onCompleted?.Invoke(record);
        }

        // ============================================================
        // Private helpers
        // ============================================================

        private IEnumerator ShowFeedback(double reactionTimeMs, bool isCorrect, ErrorType errorType)
        {
            if (feedbackText == null) yield break;

            string feedbackMessage;
            Color feedbackColor;

            if (errorType == ErrorType.Omission)
            {
                feedbackMessage = "タイムアウト";
                feedbackColor = Color.gray;
            }
            else if (!isCorrect)
            {
                feedbackMessage = "エラー";
                feedbackColor = Color.red;
            }
            else
            {
                feedbackMessage = $"{reactionTimeMs:F0} ms";
                feedbackColor = Color.white;
            }

            feedbackText.text = feedbackMessage;
            feedbackText.color = feedbackColor;
            feedbackText.gameObject.SetActive(true);

            yield return new WaitForSeconds(feedbackDurationSec);

            feedbackText.gameObject.SetActive(false);
        }

        /// <summary>
        /// 刺激提示から fireTimingMs 後にEMSを発火する。
        /// fireTimingMs は「刺激提示からの遅延ms」であり、EMSPolicyから受け取った
        /// BaselineRT - Offset - EMSLatency に等しい。
        /// </summary>
        private IEnumerator DispatchEMS(float fireTimingMs, UserAction targetSide)
        {
            if (fireTimingMs > 0f)
            {
                // 高精度待機: 50ms未満はビジーウェイト
                if (fireTimingMs < 50f)
                {
                    var sw = Stopwatch.StartNew();
                    while (sw.Elapsed.TotalMilliseconds < fireTimingMs)
                    {
                        // Spin wait
                    }
                }
                else
                {
                    yield return new WaitForSeconds(fireTimingMs / 1000f);
                }
            }

            // EMS発火（ターゲット側のチャンネル）
            if (emsController != null)
            {
                emsController.Trigger(targetSide);
            }
            else
            {
                UnityEngine.Debug.Log($"[EMS Simulation] Triggered at fireTiming={fireTimingMs:F1}ms, side: {targetSide}");
            }
        }
    }
}
