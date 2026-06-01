using NUnit.Framework;
using System.Linq;
using ReactionTest.Experiment;

namespace ReactionTest.Experiment.Tests
{
    public class TrialListGeneratorTests
    {
        [Test]
        public void GenerateBalancedColors_HalfRedHalfGreen()
        {
            var list = TrialListGenerator.GenerateBalancedColors(80, seed: 123);
            Assert.AreEqual(80, list.Length);
            Assert.AreEqual(40, list.Count(c => c == StimColor.Red));
            Assert.AreEqual(40, list.Count(c => c == StimColor.Green));
        }

        [Test]
        public void GenerateBalancedColors_Deterministic_ForSameSeed()
        {
            var a = TrialListGenerator.GenerateBalancedColors(40, 7);
            var b = TrialListGenerator.GenerateBalancedColors(40, 7);
            CollectionAssert.AreEqual(a, b);
        }

        [Test]
        public void GenerateBalancedColors_Empty_ForNonPositive()
        {
            Assert.AreEqual(0, TrialListGenerator.GenerateBalancedColors(0, 1).Length);
        }
    }
}
