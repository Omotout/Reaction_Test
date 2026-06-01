using NUnit.Framework;
using ReactionTest.Experiment;

namespace ReactionTest.Experiment.Tests
{
    public class EMSPolicyTests
    {
        [Test]
        public void ComputeFireTimingMs_SubtractsOffsetAndEmsToTouch()
        {
            // Q10=300, offset=0, emsToTouch=50 → 250
            Assert.AreEqual(250f, EMSPolicy.ComputeFireTimingMs(300f, 0f, 50f), 1e-4f);
            // offset=40 → 210
            Assert.AreEqual(210f, EMSPolicy.ComputeFireTimingMs(300f, 40f, 50f), 1e-4f);
        }

        [Test]
        public void ShouldFire_OnlyForEmsCondition()
        {
            Assert.IsTrue(EMSPolicy.ShouldFire(ExperimentCondition.EMS));
            Assert.IsFalse(EMSPolicy.ShouldFire(ExperimentCondition.Voluntary));
        }
    }
}
