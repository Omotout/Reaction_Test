using System;
using System.Collections;
using UnityEngine;
using UnityEngine.UI;
using UnityEngine.InputSystem;

namespace ReactionTest.Experiment
{
    /// <summary>
    /// Arduino主導の試行実行。Unityは TRIAL/EMSLAT を送り、TRIAL_RESULT/EMSLAT_RESULT を待って採点・記録する。
    /// 刺激提示・RT計測・EMS発火スケジューリングはArduino側。
    /// </summary>
    public class TrialEngine : MonoBehaviour
    {
        [Header("Link / EMS")]
        [SerializeField] private ArduinoLink arduinoLink;
        [SerializeField] private EMSController emsController;

        [Header("Feedback (RTモニタ)")]
        [SerializeField] private Text feedbackText;
        [SerializeField] private bool showReactionTimeFeedback = true;
        [SerializeField] private float feedbackDurationSec = 0.8f;

        [Header("Timing")]
        [Tooltip("TRIAL_RESULT を待つ上限（秒）。Arduino側の応答窓 + 通信余裕。")]
        [SerializeField] private float resultTimeoutSec = 3.0f;

        private bool _hasTrialResult;
        private TrialResult _lastTrialResult;
        private bool _hasLatResult;
        private EmsLatencyResult _lastLatResult;

        private bool _isAborted;
        public bool IsAborted => _isAborted;
        public void ResetAbort() => _isAborted = false;

        public void SetArduinoLink(ArduinoLink link) => arduinoLink = link;
        public void SetEMSController(EMSController c) => emsController = c;

        private void OnEnable()
        {
            if (arduinoLink != null)
            {
                arduinoLink.OnTrialResult += HandleTrialResult;
                arduinoLink.OnEmsLatencyResult += HandleLatResult;
            }
            HideFeedback();
        }

        private void OnDisable()
        {
            if (arduinoLink != null)
            {
                arduinoLink.OnTrialResult -= HandleTrialResult;
                arduinoLink.OnEmsLatencyResult -= HandleLatResult;
            }
        }

        private void HandleTrialResult(TrialResult r) { _lastTrialResult = r; _hasTrialResult = true; }
        private void HandleLatResult(EmsLatencyResult r) { _lastLatResult = r; _hasLatResult = true; }

        public IEnumerator RunTrial(
            PhaseType phase, int trialIndex, StimColor color, UserAction correctHand,
            UserAction emsSide, int emsDelayUs, ExperimentCondition condition, string sessionDate,
            Action<TrialRecord> onCompleted)
        {
            HideFeedback();
            _hasTrialResult = false;

            if (arduinoLink != null)
                arduinoLink.SendTrial(color, correctHand, emsSide, emsDelayUs);
            else
                UnityEngine.Debug.Log($"[Sim] TRIAL {color}/{correctHand} ems={emsSide}@{emsDelayUs}us");

            float deadline = Time.realtimeSinceStartup + resultTimeoutSec;
            var keyboard = Keyboard.current;
            while (!_hasTrialResult)
            {
                if (keyboard != null && keyboard.escapeKey.wasPressedThisFrame) { Abort(); break; }
                if (Time.realtimeSinceStartup > deadline)
                {
                    UnityEngine.Debug.LogWarning($"TrialEngine: TRIAL_RESULT timeout (trial {trialIndex}).");
                    break;
                }
                yield return null;
            }

            TrialResult res = _hasTrialResult ? _lastTrialResult
                : new TrialResult { TouchedSide = UserAction.None, RtMs = -1f, Peak = 0, EmsFired = false, TimedOut = true };

            bool isCorrect = !res.TimedOut && res.TouchedSide == correctHand;

            var record = new TrialRecord
            {
                Condition = condition,
                SessionDate = sessionDate,
                Phase = phase,
                TrialNumber = trialIndex,
                StimColor = color,
                CorrectHand = correctHand,
                ResponseSide = res.TouchedSide,
                IsCorrect = isCorrect,
                ReactionTimeMs = res.RtMs,
                Peak = res.Peak,
                EmsFired = res.EmsFired,
                EmsSide = emsSide,
                EmsFireTimingMs = emsDelayUs / 1000f,
                Timestamp = DateTime.UtcNow.ToString("o")
                // SubjectId / ExclusionFlag / EmsToTouchMs は Orchestrator が補完
            };

            if (showReactionTimeFeedback && !res.TimedOut && res.RtMs > 0f)
                yield return ShowFeedback($"{res.RtMs:F0} ms", Color.white);
            else if (showReactionTimeFeedback)
                yield return ShowFeedback(res.TimedOut ? "—" : "?", Color.gray);

            onCompleted?.Invoke(record);
        }

        public IEnumerator RunEMSLatencyTrial(UserAction side, int trialIndex, Action<float> onLatencyMs)
        {
            HideFeedback();
            _hasLatResult = false;

            if (arduinoLink != null) arduinoLink.SendEmsLatency(side);
            else UnityEngine.Debug.Log($"[Sim] EMSLAT {side}");

            float deadline = Time.realtimeSinceStartup + resultTimeoutSec;
            var keyboard = Keyboard.current;
            while (!_hasLatResult)
            {
                if (keyboard != null && keyboard.escapeKey.wasPressedThisFrame) { Abort(); break; }
                if (Time.realtimeSinceStartup > deadline)
                {
                    UnityEngine.Debug.LogWarning($"TrialEngine: EMSLAT_RESULT timeout (trial {trialIndex}).");
                    break;
                }
                yield return null;
            }

            float latency = (_hasLatResult && !_lastLatResult.TimedOut) ? _lastLatResult.LatencyMs : -1f;
            if (showReactionTimeFeedback && latency > 0f)
                yield return ShowFeedback($"{latency:F0} ms", Color.cyan);
            onLatencyMs?.Invoke(latency);
        }

        private void Abort()
        {
            _isAborted = true;
            if (arduinoLink != null) arduinoLink.SendReset();
            if (emsController != null) emsController.EmergencyStop();
            UnityEngine.Debug.LogError("TrialEngine: ABORT (Escape) — sent RESET to Arduino.");
        }

        private IEnumerator ShowFeedback(string msg, Color color)
        {
            if (feedbackText == null) yield break;
            feedbackText.text = msg;
            feedbackText.color = color;
            feedbackText.gameObject.SetActive(true);
            yield return new WaitForSeconds(feedbackDurationSec);
            feedbackText.gameObject.SetActive(false);
        }

        private void HideFeedback()
        {
            if (feedbackText != null) feedbackText.gameObject.SetActive(false);
        }
    }
}
