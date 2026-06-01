using System.IO;
using NUnit.Framework;
using ReactionTest.Experiment;

namespace ReactionTest.Experiment.Tests
{
    public class ExperimentConfigTests
    {
        [Test]
        public void LoadOrCreate_CreatesDefaultWhenMissing()
        {
            string path = Path.Combine(Path.GetTempPath(), "ec_" + Path.GetRandomFileName() + ".json");
            try
            {
                var cfg = ExperimentConfig.LoadOrCreate(path);
                Assert.IsTrue(File.Exists(path));
                Assert.AreEqual(80, cfg.PreTrials);
                Assert.AreEqual(0f, cfg.EmsOffsetMs);
                Assert.AreEqual(4f, cfg.EmsToTouchStabilitySdMs);
            }
            finally { if (File.Exists(path)) File.Delete(path); }
        }

        [Test]
        public void LoadOrCreate_ReadsExistingValues()
        {
            string path = Path.Combine(Path.GetTempPath(), "ec_" + Path.GetRandomFileName() + ".json");
            try
            {
                File.WriteAllText(path, "{\"PreTrials\":40,\"EmsOffsetMs\":40.0}");
                var cfg = ExperimentConfig.LoadOrCreate(path);
                Assert.AreEqual(40, cfg.PreTrials);
                Assert.AreEqual(40f, cfg.EmsOffsetMs);
            }
            finally { if (File.Exists(path)) File.Delete(path); }
        }
    }
}
