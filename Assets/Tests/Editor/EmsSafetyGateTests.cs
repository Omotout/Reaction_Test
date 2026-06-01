using NUnit.Framework;
using ReactionTest.Experiment;

namespace ReactionTest.Experiment.Tests
{
    public class EmsSafetyGateTests
    {
        [Test]
        public void FirstFire_IsAllowed()
        {
            var gate = new EmsSafetyGate(refractoryPeriodMs: 200, maxFiresPerSession: 500);
            Assert.AreEqual(EmsSafetyGate.Result.Allowed, gate.TryFire(0));
            Assert.AreEqual(1, gate.FireCount);
        }

        [Test]
        public void SecondFireWithinRefractory_IsBlocked_AndDoesNotCount()
        {
            var gate = new EmsSafetyGate(refractoryPeriodMs: 200, maxFiresPerSession: 500);
            gate.TryFire(0);
            // 199ms後（不応期内）
            Assert.AreEqual(EmsSafetyGate.Result.Refractory, gate.TryFire(199));
            Assert.AreEqual(1, gate.FireCount, "ブロックされた発火はカウントしない");
        }

        [Test]
        public void SecondFireAfterRefractory_IsAllowed()
        {
            var gate = new EmsSafetyGate(refractoryPeriodMs: 200, maxFiresPerSession: 500);
            gate.TryFire(0);
            // ちょうど200ms後（不応期の境界＝許可）
            Assert.AreEqual(EmsSafetyGate.Result.Allowed, gate.TryFire(200));
            Assert.AreEqual(2, gate.FireCount);
        }

        [Test]
        public void MaxFires_ReachesLimit()
        {
            var gate = new EmsSafetyGate(refractoryPeriodMs: 0, maxFiresPerSession: 3);
            Assert.AreEqual(EmsSafetyGate.Result.Allowed, gate.TryFire(0));
            Assert.AreEqual(EmsSafetyGate.Result.Allowed, gate.TryFire(1));
            Assert.AreEqual(EmsSafetyGate.Result.Allowed, gate.TryFire(2));
            Assert.AreEqual(EmsSafetyGate.Result.LimitReached, gate.TryFire(3));
            Assert.AreEqual(3, gate.FireCount);
        }

        [Test]
        public void EmergencyStop_BlocksAllSubsequentFires()
        {
            var gate = new EmsSafetyGate(refractoryPeriodMs: 0, maxFiresPerSession: 500);
            gate.TryFire(0);
            gate.EmergencyStop();
            Assert.IsTrue(gate.EmergencyStopped);
            Assert.AreEqual(EmsSafetyGate.Result.EmergencyStopped, gate.TryFire(1000));
            Assert.AreEqual(1, gate.FireCount, "緊急停止後の発火はカウントしない");
        }

        [Test]
        public void EmergencyStop_TakesPrecedenceOverLimit()
        {
            var gate = new EmsSafetyGate(refractoryPeriodMs: 0, maxFiresPerSession: 1);
            gate.TryFire(0); // 上限到達
            gate.EmergencyStop();
            // 緊急停止が上限より優先して報告される
            Assert.AreEqual(EmsSafetyGate.Result.EmergencyStopped, gate.TryFire(1));
        }
    }
}
