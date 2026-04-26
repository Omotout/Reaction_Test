using System;
using System.Linq;

namespace ReactionTest.Experiment
{
    /// <summary>
    /// 各フェーズの試行数に応じて、左右同数の（バランスされた）シャッフル済みトライアルリストを生成するユーティリティ。
    /// HDDM解析における左右の対称性を担保し、ランダムな偏りによるベースラインRTのブレを防ぐ。
    /// </summary>
    public static class TrialListGenerator
    {
        /// <summary>
        /// 左右同数のターゲットリストを生成し、Fisher-Yatesアルゴリズムでシャッフルする。
        /// </summary>
        /// <param name="totalTrials">総試行数。奇数の場合は、床関数(L)と天井関数(R)で近似する。</param>
        /// <param name="seed">シャッフルのためのシード値。再現性確保のため指定する。</param>
        /// <returns>シャッフル済みのターゲット側（Left / Right）の配列</returns>
        public static UserAction[] GenerateBalanced(int totalTrials, int seed)
        {
            if (totalTrials <= 0) return new UserAction[0];

            int half = totalTrials / 2;
            int leftCount = half;
            int rightCount = totalTrials - half; // 奇数の場合はRightが1つ多くなる

            UserAction[] list = new UserAction[totalTrials];
            
            for (int i = 0; i < leftCount; i++)
            {
                list[i] = UserAction.Left;
            }
            for (int i = leftCount; i < totalTrials; i++)
            {
                list[i] = UserAction.Right;
            }

            // Fisher-Yates shuffle
            // UnityEngine.Random ではなく System.Random を使用して、決定論的かつ他システムから独立させる
            System.Random rng = new System.Random(seed);
            int n = list.Length;
            while (n > 1)
            {
                n--;
                int k = rng.Next(n + 1);
                UserAction value = list[k];
                list[k] = list[n];
                list[n] = value;
            }

            return list;
        }

        /// <summary>
        /// 被験者ID、セッションパス、フェーズ名から決定論的なシード値を生成する。
        /// これにより、同一セッション内でもフェーズごとに異なるシャッフル結果が得られ、
        /// かつ後から完全に再現可能となる。
        /// </summary>
        public static int DerivePhaseSeed(string subjectId, string sessionPath, PhaseType phase)
        {
            // unchecked を使用してオーバーフローを許容
            unchecked
            {
                int hash = 17;
                hash = hash * 31 + (subjectId != null ? subjectId.GetHashCode() : 0);
                hash = hash * 31 + (sessionPath != null ? sessionPath.GetHashCode() : 0);
                hash = hash * 31 + phase.GetHashCode();
                return hash;
            }
        }
    }
}
