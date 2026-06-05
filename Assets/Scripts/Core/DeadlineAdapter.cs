using UnityEngine;

namespace ReactionTest.Experiment
{
    /// <summary>
    /// Deadline mode の block-by-block 適応ルール（純粋ロジック・テスト容易）。
    /// rule:
    ///   rate >= upperRate → tighten (deadline を -stepMs)
    ///   rate <  lowerRate → loosen  (deadline を +stepMs)
    ///   それ以外          → hold
    /// 適応OFF / 試行数不足 (minTrials 未満) のときは hold。
    /// </summary>
    public static class DeadlineAdapter
    {
        public struct Decision
        {
            public float NewDeadlineMs;
            public string Action;
        }

        public static Decision Adapt(
            float currentMs, int correctBefore, int totalNonTimeout,
            float upperRate, float lowerRate, float stepMs, float minMs, float maxMs,
            bool enabled, int minTrials = 5)
        {
            if (!enabled)
                return new Decision { NewDeadlineMs = currentMs, Action = "hold (adaptive off)" };
            if (totalNonTimeout < minTrials)
                return new Decision { NewDeadlineMs = currentMs, Action = "hold (insufficient trials)" };

            float rate = correctBefore / (float)totalNonTimeout;
            float delta;
            string action;
            if (rate >= upperRate) { delta = -stepMs; action = "tighten"; }
            else if (rate < lowerRate) { delta = stepMs; action = "loosen"; }
            else { delta = 0f; action = "hold"; }
            float newVal = Mathf.Clamp(currentMs + delta, minMs, maxMs);
            return new Decision { NewDeadlineMs = newVal, Action = action };
        }

        /// <summary>
        /// Pre median から deadline を導出。
        /// deadline = clamp(medianMs − offsetMs, minMs, maxMs)。
        /// medianMs ≤ 0 (= Pre 正答ゼロ) のときは -1 を返し、呼び出し側で既存値を維持させる。
        /// </summary>
        public static float DeriveFromMedian(float medianMs, float offsetMs, float minMs, float maxMs)
        {
            if (medianMs <= 0f) return -1f;
            return Mathf.Clamp(medianMs - offsetMs, minMs, maxMs);
        }

        /// <summary>
        /// Deadline mode の EMS 指示時刻を計算する。
        /// deadlineMs は Unity が EMS 指令を出す時刻そのものとして扱う。
        /// </summary>
        public static float ComputeFireTimingMs(float deadlineMs)
            => deadlineMs;
    }

    /// <summary>
    /// 1試行の結果分類（純粋ロジック）。
    /// Fastest / Deadline 両モードで共通の意味づけ:
    ///   - Timeout: 反応なし
    ///   - CorrectBeforeDeadline: 正答 & EMS未発火
    ///   - EmsTriggeredAfterDeadline: 正答 & EMS発火後
    ///   - ErrorBeforeDeadline: 誤反応 & EMS未発火
    ///   - ErrorAfterEms: 誤反応 & EMS発火後
    /// </summary>
    public static class TrialOutcomeClassifier
    {
        public static TrialOutcome Classify(bool isTimeout, bool isCorrect, bool emsFired)
        {
            if (isTimeout) return TrialOutcome.Timeout;
            if (isCorrect)
                return emsFired ? TrialOutcome.EmsTriggeredAfterDeadline
                                : TrialOutcome.CorrectBeforeDeadline;
            return emsFired ? TrialOutcome.ErrorAfterEms
                            : TrialOutcome.ErrorBeforeDeadline;
        }
    }
}
