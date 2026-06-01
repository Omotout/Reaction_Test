using System;
using System.Collections.Generic;
using System.Linq;

namespace ReactionTest.Experiment
{
    /// <summary>RT分布の純粋統計ユーティリティ（UnityEngine非依存・テスト容易）。</summary>
    public static class RtStatistics
    {
        /// <summary>線形補間パーセンタイル（p: 0..1）。入力は非破壊（内部でソートコピー）。</summary>
        public static float Percentile(IEnumerable<float> values, float p)
        {
            var sorted = values.OrderBy(v => v).ToList();
            if (sorted.Count == 0) return 0f;
            if (sorted.Count == 1) return sorted[0];

            float index = p * (sorted.Count - 1);
            int lo = (int)Math.Floor(index);
            int hi = (int)Math.Ceiling(index);
            if (lo == hi) return sorted[lo];

            float frac = index - lo;
            return sorted[lo] * (1f - frac) + sorted[hi] * frac;
        }

        /// <summary>FastestBaseline = 正答RTの下位10パーセンタイル。</summary>
        public static float Q10(IEnumerable<float> correctRTs) => Percentile(correctRTs, 0.10f);

        public static float Median(IEnumerable<float> values) => Percentile(values, 0.50f);

        public static float Mean(IEnumerable<float> values)
        {
            var list = values.ToList();
            return list.Count == 0 ? 0f : list.Average();
        }

        /// <summary>標本標準偏差（n-1）。2件未満は0。</summary>
        public static float SampleStdDev(IEnumerable<float> values)
        {
            var list = values.ToList();
            if (list.Count < 2) return 0f;
            float mean = list.Average();
            double sumSq = list.Sum(v => (v - mean) * (double)(v - mean));
            return (float)Math.Sqrt(sumSq / (list.Count - 1));
        }

        /// <summary>
        /// 除外分類。生データは保持し、分類のみ返す。
        /// upperSdBound>0 のとき rt>upperSdBound も Lapse とみなす（個人内+3SD用。
        /// Unity記録時は 0 を渡して anticipation/&gt;lapseMax のみ判定し、+3SDはPython側で再計算）。
        /// </summary>
        public static ExclusionFlag Classify(float rtMs, float anticipationMs, float lapseMaxMs, float upperSdBound)
        {
            if (rtMs < anticipationMs) return ExclusionFlag.Anticipation;
            if (rtMs > lapseMaxMs) return ExclusionFlag.Lapse;
            if (upperSdBound > 0f && rtMs > upperSdBound) return ExclusionFlag.Lapse;
            return ExclusionFlag.Normal;
        }
    }
}
