namespace ReactionTest.Experiment
{
    /// <summary>
    /// EMS発火タイミング（純粋ロジック）。
    /// 発火時刻(LED点灯基準, ms) = Q10(side) − offset − EMS_to_Touch(side)。
    /// </summary>
    public static class EMSPolicy
    {
        public static float ComputeFireTimingMs(float q10Ms, float offsetMs, float emsToTouchMs)
            => q10Ms - offsetMs - emsToTouchMs;

        /// <summary>EMS条件のみ発火。Voluntaryは発火しない。</summary>
        public static bool ShouldFire(ExperimentCondition condition)
            => condition == ExperimentCondition.EMS;
    }
}
