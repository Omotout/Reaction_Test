using NUnit.Framework;
using ReactionTest.Experiment;

namespace ReactionTest.Experiment.Tests
{
    public class CounterbalanceTests
    {
        [Test]
        public void OrderAndMapping_From2x2Index()
        {
            // index 0..3 で 順序×マッピング の4群を巡回
            Assert.AreEqual(ConditionOrder.EmsFirst,        Counterbalance.OrderFor(0));
            Assert.AreEqual(ConditionOrder.VoluntaryFirst,  Counterbalance.OrderFor(1));
            Assert.AreEqual(SRMapping.RedRight,             Counterbalance.MappingFor(0));
            Assert.AreEqual(SRMapping.RedRight,             Counterbalance.MappingFor(1));
            Assert.AreEqual(SRMapping.RedLeft,              Counterbalance.MappingFor(2));
            // 4群目（index 3）と循環（index 4 で index 0 と一致）も確認
            Assert.AreEqual(ConditionOrder.VoluntaryFirst,  Counterbalance.OrderFor(3));
            Assert.AreEqual(SRMapping.RedLeft,              Counterbalance.MappingFor(3));
            Assert.AreEqual(ConditionOrder.EmsFirst,        Counterbalance.OrderFor(4));
            Assert.AreEqual(SRMapping.RedRight,             Counterbalance.MappingFor(4));
        }

        [Test]
        public void ConditionForSession_RespectsOrder()
        {
            Assert.AreEqual(ExperimentCondition.EMS,
                Counterbalance.ConditionForSession(ConditionOrder.EmsFirst, 1));
            Assert.AreEqual(ExperimentCondition.Voluntary,
                Counterbalance.ConditionForSession(ConditionOrder.EmsFirst, 2));
            Assert.AreEqual(ExperimentCondition.Voluntary,
                Counterbalance.ConditionForSession(ConditionOrder.VoluntaryFirst, 1));
            // 4象限目（VoluntaryFirst の第2セッション → EMS）も確認
            Assert.AreEqual(ExperimentCondition.EMS,
                Counterbalance.ConditionForSession(ConditionOrder.VoluntaryFirst, 2));
        }

        [Test]
        public void ConditionForSession_InvalidSession_Throws()
        {
            Assert.Throws<System.ArgumentOutOfRangeException>(
                () => Counterbalance.ConditionForSession(ConditionOrder.EmsFirst, 0));
            Assert.Throws<System.ArgumentOutOfRangeException>(
                () => Counterbalance.ConditionForSession(ConditionOrder.EmsFirst, 3));
        }

        [Test]
        public void CorrectHand_RespectsMapping()
        {
            Assert.AreEqual(UserAction.Right, Counterbalance.CorrectHand(StimColor.Red,   SRMapping.RedRight));
            Assert.AreEqual(UserAction.Left,  Counterbalance.CorrectHand(StimColor.Green, SRMapping.RedRight));
            Assert.AreEqual(UserAction.Left,  Counterbalance.CorrectHand(StimColor.Red,   SRMapping.RedLeft));
            Assert.AreEqual(UserAction.Right, Counterbalance.CorrectHand(StimColor.Green, SRMapping.RedLeft));
        }
    }
}
