using NUnit.Framework;
using ReactionTest.Experiment;

namespace ReactionTest.Experiment.Tests
{
    public class DeadlineAdapterTests
    {
        const float Upper = 0.70f, Lower = 0.50f, Step = 10f, Min = 100f, Max = 800f;

        [Test]
        public void Tightens_When_RateAtOrAboveUpper()
        {
            var d = DeadlineAdapter.Adapt(250f, 8, 10, Upper, Lower, Step, Min, Max, enabled: true);
            Assert.AreEqual("tighten", d.Action);
            Assert.AreEqual(240f, d.NewDeadlineMs, 1e-4f);
        }

        [Test]
        public void Loosens_When_RateBelowLower()
        {
            var d = DeadlineAdapter.Adapt(250f, 4, 10, Upper, Lower, Step, Min, Max, enabled: true);
            Assert.AreEqual("loosen", d.Action);
            Assert.AreEqual(260f, d.NewDeadlineMs, 1e-4f);
        }

        [Test]
        public void Holds_When_RateBetweenBounds()
        {
            var d = DeadlineAdapter.Adapt(250f, 6, 10, Upper, Lower, Step, Min, Max, enabled: true);
            Assert.AreEqual("hold", d.Action);
            Assert.AreEqual(250f, d.NewDeadlineMs, 1e-4f);
        }

        [Test]
        public void Holds_When_Disabled()
        {
            var d = DeadlineAdapter.Adapt(250f, 10, 10, Upper, Lower, Step, Min, Max, enabled: false);
            StringAssert.StartsWith("hold", d.Action);
            Assert.AreEqual(250f, d.NewDeadlineMs, 1e-4f);
        }

        [Test]
        public void Holds_When_InsufficientTrials()
        {
            var d = DeadlineAdapter.Adapt(250f, 3, 4, Upper, Lower, Step, Min, Max, enabled: true);
            StringAssert.StartsWith("hold", d.Action);
            Assert.AreEqual(250f, d.NewDeadlineMs, 1e-4f);
        }

        [Test]
        public void ClampsToMin_OnRepeatedTighten()
        {
            // 100ms から 10ms ずつ tighten しても Min(100) を下回らない
            var d = DeadlineAdapter.Adapt(105f, 10, 10, Upper, Lower, Step, Min, Max, enabled: true);
            Assert.AreEqual(100f, d.NewDeadlineMs, 1e-4f);
            Assert.AreEqual("tighten", d.Action);
        }

        [Test]
        public void ClampsToMax_OnRepeatedLoosen()
        {
            var d = DeadlineAdapter.Adapt(795f, 0, 10, Upper, Lower, Step, Min, Max, enabled: true);
            Assert.AreEqual(800f, d.NewDeadlineMs, 1e-4f);
            Assert.AreEqual("loosen", d.Action);
        }

        [Test]
        public void DeriveFromMedian_SubtractsOffsetWithinBounds()
        {
            // 通常: 240ms median, offset 10ms → 230ms
            Assert.AreEqual(230f, DeadlineAdapter.DeriveFromMedian(240f, 10f, Min, Max), 1e-4f);
        }

        [Test]
        public void DeriveFromMedian_ClampsToMinAndMax()
        {
            // 下限: median=105 - offset=20 = 85, clamped to Min=100
            Assert.AreEqual(100f, DeadlineAdapter.DeriveFromMedian(105f, 20f, Min, Max), 1e-4f);
            // 上限: median=1000 - offset=10 = 990, clamped to Max=800
            Assert.AreEqual(800f, DeadlineAdapter.DeriveFromMedian(1000f, 10f, Min, Max), 1e-4f);
        }

        [Test]
        public void DeriveFromMedian_ReturnsNegativeOnEmptyMedian()
        {
            // median<=0 = Pre 正答ゼロ → 呼び出し側で既存値を維持させる sentinel
            Assert.AreEqual(-1f, DeadlineAdapter.DeriveFromMedian(0f, 10f, Min, Max), 1e-4f);
            Assert.AreEqual(-1f, DeadlineAdapter.DeriveFromMedian(-5f, 10f, Min, Max), 1e-4f);
        }
    }

    public class TrialOutcomeClassifierTests
    {
        [Test]
        public void Timeout_OverridesAll()
        {
            Assert.AreEqual(TrialOutcome.Timeout,
                TrialOutcomeClassifier.Classify(isTimeout: true, isCorrect: false, emsFired: false));
            Assert.AreEqual(TrialOutcome.Timeout,
                TrialOutcomeClassifier.Classify(isTimeout: true, isCorrect: true, emsFired: true));
        }

        [Test]
        public void Correct_NoEms_IsBeforeDeadline()
        {
            Assert.AreEqual(TrialOutcome.CorrectBeforeDeadline,
                TrialOutcomeClassifier.Classify(false, isCorrect: true, emsFired: false));
        }

        [Test]
        public void Correct_WithEms_IsEmsTriggered()
        {
            // Deadline mode: deadline 後の EMS 補助 / Fastest mode: 通常の Training trial 両方をこの outcome に分類
            Assert.AreEqual(TrialOutcome.EmsTriggeredAfterDeadline,
                TrialOutcomeClassifier.Classify(false, isCorrect: true, emsFired: true));
        }

        [Test]
        public void Error_NoEms_IsErrorBeforeDeadline()
        {
            Assert.AreEqual(TrialOutcome.ErrorBeforeDeadline,
                TrialOutcomeClassifier.Classify(false, isCorrect: false, emsFired: false));
        }

        [Test]
        public void Error_WithEms_IsErrorAfterEms()
        {
            Assert.AreEqual(TrialOutcome.ErrorAfterEms,
                TrialOutcomeClassifier.Classify(false, isCorrect: false, emsFired: true));
        }
    }
}
