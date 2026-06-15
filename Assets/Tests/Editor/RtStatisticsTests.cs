using System.Collections.Generic;
using NUnit.Framework;
using ReactionTest.Experiment;

namespace ReactionTest.Experiment.Tests
{
    public class RtStatisticsTests
    {
        [Test]
        public void Percentile_LinearInterpolation_Q10()
        {
            // 1..10 の Q10 は線形補間で index=0.9 → 1*0.1+2*0.9 = 1.9
            var data = new List<float> { 1,2,3,4,5,6,7,8,9,10 };
            Assert.AreEqual(1.9f, RtStatistics.Q10(data), 1e-4f);
        }

        [Test]
        public void Median_OddAndEven()
        {
            Assert.AreEqual(3f, RtStatistics.Median(new List<float>{1,2,3,4,5}), 1e-4f);
            Assert.AreEqual(2.5f, RtStatistics.Median(new List<float>{1,2,3,4}), 1e-4f);
        }

        [Test]
        public void SampleStdDev_KnownValue()
        {
            // {2,4,4,4,5,5,7,9} の標本SD = 2.138...
            var data = new List<float>{2,4,4,4,5,5,7,9};
            Assert.AreEqual(2.13809f, RtStatistics.SampleStdDev(data), 1e-3f);
        }

        [Test]
        public void Classify_AnticipationLapseNormalTimeout()
        {
            Assert.AreEqual(ExclusionFlag.Anticipation, RtStatistics.Classify(120f, 150f, 1000f, 0f));
            Assert.AreEqual(ExclusionFlag.Lapse,        RtStatistics.Classify(1200f, 150f, 1000f, 0f));
            Assert.AreEqual(ExclusionFlag.Normal,       RtStatistics.Classify(300f, 150f, 1000f, 0f));
            // タイムアウト（rt<=0）は Anticipation ではなく Timeout として分離
            Assert.AreEqual(ExclusionFlag.Timeout,      RtStatistics.Classify(-1f, 150f, 1000f, 0f));
            Assert.AreEqual(ExclusionFlag.Timeout,      RtStatistics.Classify(0f, 150f, 1000f, 0f));
        }

        [Test]
        public void Empty_ReturnsZero()
        {
            Assert.AreEqual(0f, RtStatistics.Q10(new List<float>()));
            Assert.AreEqual(0f, RtStatistics.Median(new List<float>()));
        }

        [Test]
        public void Classify_UpperSdBound_PromotesToLapse()
        {
            // upperSdBound>0 のとき lapseMax 以下でも上限超過は Lapse（個人内+3SD用）
            Assert.AreEqual(ExclusionFlag.Lapse,  RtStatistics.Classify(700f, 150f, 1000f, 600f));
            Assert.AreEqual(ExclusionFlag.Normal, RtStatistics.Classify(500f, 150f, 1000f, 600f));
            // upperSdBound<=0 は無効（センチネル）。同じ700msでも Normal に戻る
            Assert.AreEqual(ExclusionFlag.Normal, RtStatistics.Classify(700f, 150f, 1000f, 0f));
        }

        [Test]
        public void MeanAndSampleStdDev_EmptyAndSingle()
        {
            Assert.AreEqual(0f, RtStatistics.Mean(new List<float>()));
            Assert.AreEqual(4f, RtStatistics.Mean(new List<float>{2,4,6}), 1e-4f);
            Assert.AreEqual(0f, RtStatistics.SampleStdDev(new List<float>()));
            Assert.AreEqual(0f, RtStatistics.SampleStdDev(new List<float>{42}));
        }

        [Test]
        public void Qn_MatchesQ10AndClampsRange()
        {
            var data = new List<float> { 1,2,3,4,5,6,7,8,9,10 };
            Assert.AreEqual(1.9f, RtStatistics.Qn(data, 10f), 1e-4f);
            Assert.AreEqual(RtStatistics.Median(data), RtStatistics.Qn(data, 50f), 1e-4f);
            // 範囲外は [0,100] にクランプ
            Assert.AreEqual(1f, RtStatistics.Qn(data, -5f), 1e-4f);
            Assert.AreEqual(10f, RtStatistics.Qn(data, 150f), 1e-4f);
        }

        [Test]
        public void MeanMinusKsd_KnownValue()
        {
            // {2,4,4,4,5,5,7,9}: mean=5, SD=2.13809... → mean-1×SD = 2.8619, mean-2×SD = 0.7238
            var data = new List<float>{2,4,4,4,5,5,7,9};
            Assert.AreEqual(5f - 2.13809f, RtStatistics.MeanMinusKsd(data, 1f), 1e-3f);
            Assert.AreEqual(5f - 2f * 2.13809f, RtStatistics.MeanMinusKsd(data, 2f), 1e-3f);
            Assert.AreEqual(0f, RtStatistics.MeanMinusKsd(new List<float>(), 1f));
        }

        [Test]
        public void ComputeBaseline_DispatchesByMethod()
        {
            var data = new List<float>{2,4,4,4,5,5,7,9};
            // Percentile経路はQnと一致
            Assert.AreEqual(RtStatistics.Qn(data, 10f),
                RtStatistics.ComputeBaseline(data, BaselineMethod.Percentile, 10f, 99f), 1e-4f);
            // SD経路はMeanMinusKsdと一致（nは無視）
            Assert.AreEqual(RtStatistics.MeanMinusKsd(data, 1f),
                RtStatistics.ComputeBaseline(data, BaselineMethod.Sd, 99f, 1f), 1e-3f);
        }
    }
}
