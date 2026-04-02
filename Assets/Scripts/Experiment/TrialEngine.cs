// Force recompile
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
        [SerializeField] private Color greenColor = Color.green;
        [SerializeField] private Color redColor = Color.red;
        [SerializeField] private float minPreStimulusWaitSec = 0.8f;
        [SerializeField] private float maxPreStimulusWaitSec = 1.6f;
        [SerializeField] private float responseWindowSec = 1.0f;

        [Header("Feedback")]
        [SerializeField] private Text feedbackText;
        [SerializeField] private bool showReactionTimeFeedback = true;
        [SerializeField] private float feedbackDurationSec = 0.8f;

        [Header("EMS")]
        [SerializeField] private EMSController emsController;

        // 高精度タイマー
        private Stopwatch _reactionStopwatch = new Stopwatch();

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

        public IEnumerator RunSingleTrial(
            PhaseType phase,
            TaskType task,
            int trialIndex,
            EMSDecision emsDecision,
            Action<TrialRecord> onCompleted)
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

            StimulusColor stimulusColor = TaskRule.PickStimulus(task);
            UserAction expectedAction = TaskRule.GetExpectedAction(task, stimulusColor);

            stimulusImage.color = stimulusColor == StimulusColor.Green ? greenColor : redColor;
            stimulusImage.gameObject.SetActive(true);

            // 高精度タイマーをリセット・開始
            _reactionStopwatch.Reset();
            _reactionStopwatch.Start();

            if (emsDecision.Enabled)
            {
                StartCoroutine(DispatchEMS(emsDecision.OffsetMs, expectedAction));
            }

            UserAction action = UserAction.None;
            double reactionTimeMs = -1.0;
            bool responded = false;
            
            // Mouseを取得（nullチェック）
            var mouse = Mouse.current;

            while (_reactionStopwatch.Elapsed.TotalSeconds < responseWindowSec)
            {
                if (mouse != null)
                {
                    if (mouse.leftButton.wasPressedThisFrame)
                    {
                        action = UserAction.Left;
                        reactionTimeMs = _reactionStopwatch.Elapsed.TotalMilliseconds;
                        responded = true;
                        break;
                    }

                    if (mouse.rightButton.wasPressedThisFrame)
                    {
                        action = UserAction.Right;
                        reactionTimeMs = _reactionStopwatch.Elapsed.TotalMilliseconds;
                        responded = true;
                        break;
                    }
                }

                yield return null;
            }

            _reactionStopwatch.Stop();
            stimulusImage.gameObject.SetActive(false);

            bool isCorrect = TaskRule.Evaluate(task, stimulusColor, action, out ErrorType errorType);

            // DRTで赤刺激に正しく無反応した場合、反応時間は記録しない（NaNとして扱う）
            // ただしisCorrect=trueで、reactionTimeMs=-1のままにしておく（解析時に除外）
            // 注: 正しい無反応はreactionTimeMs=-1, isCorrect=true, errorType=None となる

            // フィードバック表示
            if (showReactionTimeFeedback && feedbackText != null)
            {
                yield return ShowFeedback(reactionTimeMs, isCorrect, errorType);
            }

            TrialRecord record = new TrialRecord
            {
                Phase = phase,
                Task = task,
                TrialIndex = trialIndex,
                StimulusColor = stimulusColor,
                ExpectedAction = expectedAction,
                ActualAction = action,
                IsCorrect = isCorrect,
                ErrorType = errorType,
                ReactionTimeMs = (float)reactionTimeMs,
                EMSEnabled = emsDecision.Enabled,
                EMSOffsetMs = emsDecision.OffsetMs,
                Timestamp = DateTime.UtcNow.ToString("o")
            };

            onCompleted?.Invoke(record);
        }

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

        private IEnumerator DispatchEMS(float offsetMs, UserAction expectedAction)
        {
            // オフセットが正の場合は待機
            if (offsetMs > 0f)
            {
                // 高精度待機: WaitForSecondsはフレーム依存なので、短い待機ではSpinWaitを使用
                if (offsetMs < 50f)
                {
                    // 50ms未満の短い待機はビジーウェイト
                    var sw = Stopwatch.StartNew();
                    while (sw.Elapsed.TotalMilliseconds < offsetMs)
                    {
                        // Spin wait
                    }
                }
                else
                {
                    yield return new WaitForSeconds(offsetMs / 1000f);
                }
            }

            // EMS発火
            if (emsController != null)
            {
                emsController.Trigger(expectedAction);
            }
            else
            {
                UnityEngine.Debug.Log($"[EMS Simulation] Triggered with offset {offsetMs:F1}ms, action: {expectedAction}");
            }
        }
    }
}
