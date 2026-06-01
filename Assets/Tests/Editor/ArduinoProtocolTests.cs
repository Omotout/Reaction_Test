using NUnit.Framework;
using ReactionTest.Experiment;

namespace ReactionTest.Experiment.Tests
{
    public class ArduinoProtocolTests
    {
        [Test]
        public void FormatTrial_NoEms()
        {
            Assert.AreEqual("TRIAL,R,R,N,0",
                ArduinoProtocol.FormatTrial(StimColor.Red, UserAction.Right, UserAction.None, 0));
        }

        [Test]
        public void FormatTrial_WithEms()
        {
            Assert.AreEqual("TRIAL,G,L,L,210000",
                ArduinoProtocol.FormatTrial(StimColor.Green, UserAction.Left, UserAction.Left, 210000));
            // emsSide=Right も明示的に検証（Side のフォールスルー回帰防止）
            Assert.AreEqual("TRIAL,R,R,R,150000",
                ArduinoProtocol.FormatTrial(StimColor.Red, UserAction.Right, UserAction.Right, 150000));
        }

        [Test]
        public void FormatSimpleCommands()
        {
            Assert.AreEqual("EMSLAT,R", ArduinoProtocol.FormatEmsLatency(UserAction.Right));
            Assert.AreEqual("THR,L,30", ArduinoProtocol.FormatThreshold(UserAction.Left, 30));
            Assert.AreEqual("EMSCFG,50,1,3,40000", ArduinoProtocol.FormatEmsConfig(50, 1, 3, 40000));
            // integrated_full 既存コマンドはコロン式に踏襲
            Assert.AreEqual("EMS:R", ArduinoProtocol.FormatEmsManual(UserAction.Right));
            Assert.AreEqual("LED:OFF", ArduinoProtocol.LedOff);
            Assert.AreEqual("RESET", ArduinoProtocol.Reset);
        }

        [Test]
        public void Side_None_Throws()
        {
            Assert.Throws<System.ArgumentOutOfRangeException>(() => ArduinoProtocol.Side(UserAction.None));
        }

        [Test]
        public void ParseTrialResult_Touched()
        {
            Assert.IsTrue(ArduinoProtocol.TryParseTrialResult("TRIAL_RESULT,R,243187,58,1", out var r));
            Assert.AreEqual(UserAction.Right, r.TouchedSide);
            Assert.AreEqual(243.187f, r.RtMs, 1e-3f);
            Assert.AreEqual(58, r.Peak);
            Assert.IsTrue(r.EmsFired);
            Assert.IsFalse(r.TimedOut);
        }

        [Test]
        public void ParseTrialResult_Timeout()
        {
            Assert.IsTrue(ArduinoProtocol.TryParseTrialResult("TRIAL_RESULT,NONE,-1,0,0", out var r));
            Assert.AreEqual(UserAction.None, r.TouchedSide);
            Assert.AreEqual(-1f, r.RtMs);
            Assert.IsTrue(r.TimedOut);
            Assert.IsFalse(r.EmsFired);
        }

        [Test]
        public void ParseTrialResult_TimeoutWithEmsFired()
        {
            // EMSは発火したが応答ウィンドウ内にタッチがなかった正当なケース
            Assert.IsTrue(ArduinoProtocol.TryParseTrialResult("TRIAL_RESULT,NONE,-1,0,1", out var r));
            Assert.IsTrue(r.TimedOut);
            Assert.IsTrue(r.EmsFired);
            Assert.AreEqual(-1f, r.RtMs);
        }

        [Test]
        public void ParseTrialResult_RejectsOtherLines()
        {
            Assert.IsFalse(ArduinoProtocol.TryParseTrialResult("OK:LED:R", out _));
            Assert.IsFalse(ArduinoProtocol.TryParseTrialResult("", out _));
            Assert.IsFalse(ArduinoProtocol.TryParseTrialResult("TRIAL_RESULT,R,243187", out _));
            // 非数値の rtUs（部分受信・ノイズ）は false
            Assert.IsFalse(ArduinoProtocol.TryParseTrialResult("TRIAL_RESULT,R,abc,58,1", out _));
        }

        [Test]
        public void ParseTrialResult_ToleratesTrailingFields()
        {
            // 前方互換のため余剰フィールドは許容（>=5 で判定）
            Assert.IsTrue(ArduinoProtocol.TryParseTrialResult("TRIAL_RESULT,R,100000,50,1,EXTRA", out var r));
            Assert.AreEqual(UserAction.Right, r.TouchedSide);
            Assert.AreEqual(100f, r.RtMs, 1e-3f);
        }

        [Test]
        public void ParseEmsLatency_OkAndTimeout()
        {
            Assert.IsTrue(ArduinoProtocol.TryParseEmsLatency("EMSLAT_RESULT,L,52310", out var ok));
            Assert.AreEqual(UserAction.Left, ok.Side);
            Assert.AreEqual(52.310f, ok.LatencyMs, 1e-3f);
            Assert.IsFalse(ok.TimedOut);

            Assert.IsTrue(ArduinoProtocol.TryParseEmsLatency("EMSLAT_RESULT,R,-1", out var to));
            Assert.AreEqual(UserAction.Right, to.Side);
            Assert.AreEqual(-1f, to.LatencyMs);
            Assert.IsTrue(to.TimedOut);

            Assert.IsFalse(ArduinoProtocol.TryParseEmsLatency("TRIAL_RESULT,R,1,1,1", out _));
        }
    }
}
