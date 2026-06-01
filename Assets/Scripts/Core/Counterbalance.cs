namespace ReactionTest.Experiment
{
    /// <summary>
    /// 被験者番号からの2×2カウンターバランス割当と、色→正解手の写像（純粋関数）。
    /// subjectIndex は 0 以上であること（負値は剰余の符号により割当が崩れる）。
    /// 割当は subjectIndex のビット0→条件順、ビット1→S-Rマッピング（直交2×2）で4被験者ごとに循環。
    /// </summary>
    public static class Counterbalance
    {
        /// <summary>条件提示順：被験者indexのビット0（偶奇）で割当。</summary>
        public static ConditionOrder OrderFor(int subjectIndex)
            => (subjectIndex % 2 == 0) ? ConditionOrder.EmsFirst : ConditionOrder.VoluntaryFirst;

        /// <summary>S-Rマッピング：被験者indexのビット1（2件ごとに反転）で割当。条件順と直交。</summary>
        public static SRMapping MappingFor(int subjectIndex)
            => ((subjectIndex / 2) % 2 == 0) ? SRMapping.RedRight : SRMapping.RedLeft;

        /// <summary>
        /// セッション番号(1 or 2)→条件。範囲外は設定ミスを早期に顕在化させるため例外を送出する
        /// （黙って誤った条件を割り当てると実データを汚染するため）。
        /// </summary>
        public static ExperimentCondition ConditionForSession(ConditionOrder order, int sessionNumber)
        {
            if (sessionNumber != 1 && sessionNumber != 2)
                throw new System.ArgumentOutOfRangeException(
                    nameof(sessionNumber), sessionNumber, "セッション番号は 1 または 2 のみ。");

            bool first = sessionNumber == 1;
            if (order == ConditionOrder.EmsFirst)
                return first ? ExperimentCondition.EMS : ExperimentCondition.Voluntary;
            return first ? ExperimentCondition.Voluntary : ExperimentCondition.EMS;
        }

        /// <summary>刺激色とマッピングから正解の手を返す。</summary>
        public static UserAction CorrectHand(StimColor color, SRMapping mapping)
        {
            bool redRight = (mapping == SRMapping.RedRight);
            if (color == StimColor.Red)   return redRight ? UserAction.Right : UserAction.Left;
            return redRight ? UserAction.Left : UserAction.Right; // Green
        }
    }
}
