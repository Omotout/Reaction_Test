namespace ReactionTest.Experiment
{
    /// <summary>被験者番号からの2×2カウンターバランス割当と、色→正解手の写像（純粋関数）。</summary>
    public static class Counterbalance
    {
        /// <summary>条件提示順：被験者indexの偶奇で割当。</summary>
        public static ConditionOrder OrderFor(int subjectIndex)
            => (subjectIndex % 2 == 0) ? ConditionOrder.EmsFirst : ConditionOrder.VoluntaryFirst;

        /// <summary>S-Rマッピング：2件ごとに反転（順序と直交）。</summary>
        public static SRMapping MappingFor(int subjectIndex)
            => ((subjectIndex / 2) % 2 == 0) ? SRMapping.RedRight : SRMapping.RedLeft;

        /// <summary>セッション番号(1 or 2)→条件。</summary>
        public static ExperimentCondition ConditionForSession(ConditionOrder order, int sessionNumber)
        {
            bool first = sessionNumber <= 1;
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
