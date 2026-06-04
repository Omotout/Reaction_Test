namespace ReactionTest.Experiment
{
    /// <summary>
    /// EMS発火タイミング（純粋ロジック）。
    /// 発火時刻(LED点灯基準, ms) = baseline(side) − offset − EMS_to_Touch(side)。
    /// baseline は Percentile(下位n%) または mean−k×SD を呼び出し側で算出して渡す。
    /// </summary>
    public static class EMSPolicy
    {
        public static float ComputeFireTimingMs(float baselineMs, float offsetMs, float emsToTouchMs)
            => baselineMs - offsetMs - emsToTouchMs;

        /// <summary>EMS条件のみ発火。Voluntaryは発火しない。</summary>
        public static bool ShouldFire(ExperimentCondition condition)
            => condition == ExperimentCondition.EMS;
    }
}
