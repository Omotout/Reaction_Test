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
                // 部分JSON: 指定外フィールドは既定値が保持される
                Assert.AreEqual(80, cfg.PostTrials);
                Assert.AreEqual(4f, cfg.EmsToTouchStabilitySdMs);
            }
            finally { if (File.Exists(path)) File.Delete(path); }
        }

        [Test]
        public void LoadOrCreate_RoundTrips_WrittenDefaults()
        {
            string path = Path.Combine(Path.GetTempPath(), "ec_" + Path.GetRandomFileName() + ".json");
            try
            {
                // 1回目: 既定値を書き出す。2回目: そのファイルを読み戻す。
                ExperimentConfig.LoadOrCreate(path);
                var reread = ExperimentConfig.LoadOrCreate(path);
                Assert.AreEqual(80, reread.PreTrials);
                Assert.AreEqual(30, reread.EmsLatencyTrials);
                Assert.AreEqual(40000, reread.EmsPulseIntervalUs);
                Assert.AreEqual(4f, reread.EmsToTouchStabilitySdMs);
            }
            finally { if (File.Exists(path)) File.Delete(path); }
        }

        [Test]
        public void LoadOrCreate_MalformedJson_Throws()
        {
            string path = Path.Combine(Path.GetTempPath(), "ec_" + Path.GetRandomFileName() + ".json");
            try
            {
                File.WriteAllText(path, "{ this is not valid json");
                Assert.Throws<System.InvalidOperationException>(
                    () => ExperimentConfig.LoadOrCreate(path));
            }
            finally { if (File.Exists(path)) File.Delete(path); }
        }
    }
}
