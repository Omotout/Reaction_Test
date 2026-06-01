using NUnit.Framework;
using ReactionTest.Experiment;

namespace ReactionTest.Experiment.Tests
{
    public class SmokeTests
    {
        [Test]
        public void UserAction_IsAccessibleFromCore()
        {
            Assert.AreNotEqual(UserAction.Left, UserAction.Right);
        }
    }
}
