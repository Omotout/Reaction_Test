namespace ReactionTest.Experiment
{
    /// <summary>
    /// EMSタイミング決定ポリシー
    /// 
    /// オフセットの考え方:
    /// - baselineRtMs: EMSなしでの平均反応時間（刺激→ボタン押下）
    /// - agencyOffsetMs: ボタンフィードバックを速める量（正の値）
    /// - emsLatencyMs: EMS発火→ボタン押下の遅延時間
    /// - 実際のEMS発火タイミング = baselineRtMs - agencyOffsetMs - emsLatencyMs
    /// 
    /// 例: baselineRtMs=300ms, agencyOffsetMs=40ms, emsLatencyMs=50ms の場合
    ///     EMS発火タイミング = 300 - 40 - 50 = 210ms（刺激提示から210ms後にEMS）
    ///     実際のボタン押下 = 210 + 50 = 260ms
    ///     速くなった量 = 300 - 260 = 40ms ✓
    /// </summary>
    public static class EMSPolicy
    {
        public static EMSDecision ComputeDecision(
            GroupType group,
            TaskType task,
            float baselineRtMs,
            float agencyOffsetMs,
            float emsLatencyMs)
        {
            switch (group)
            {
                case GroupType.AgencyEMS:
                    // EMSタイミング = ベースライン反応時間 - オフセット - EMSレイテンシ
                    float emsTiming = baselineRtMs - agencyOffsetMs - emsLatencyMs;
                    return new EMSDecision(true, emsTiming);
                case GroupType.Voluntary:
                default:
                    return new EMSDecision(false, 0f);
            }
        }
    }
}
