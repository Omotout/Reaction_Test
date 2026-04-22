namespace ReactionTest.Experiment
{
    // ========================================================================
    // V3: CRT特化 + 左右別EMSレイテンシ対応
    // - TaskType引数を削除
    // - 発火タイミング = BaselineRT - Offset - EMSLatency（左右別）
    //
    // 例: BaselineRT=300ms, Offset=40ms, EMSLatency(Left)=50ms
    //     → FireTiming = 300 - 40 - 50 = 210ms（刺激提示から210ms後にEMS）
    //     → 実際のボタン押下 ≈ 210 + 50 = 260ms（BaselineRTより40ms速い）
    // ========================================================================

    public static class EMSPolicy
    {
        /// <summary>
        /// Trainingフェーズ用: 群とターゲット側に応じたEMS決定
        /// </summary>
        /// <param name="group">実験群</param>
        /// <param name="targetSide">ターゲット側（Left/Right）</param>
        /// <param name="baselineRtMs">ベースライン反応時間（ms）</param>
        /// <param name="agencyOffsetMs">Agency維持オフセット（= 速めたい量、ターゲット側に対応する値）</param>
        /// <param name="emsLatencyMs">EMSレイテンシ（ターゲット側に対応する値）</param>
        public static EMSDecision ComputeDecision(
            GroupType group,
            UserAction targetSide,
            float baselineRtMs,
            float agencyOffsetMs,
            float emsLatencyMs)
        {
            switch (group)
            {
                case GroupType.AgencyEMS:
                    float fireTiming = baselineRtMs - agencyOffsetMs - emsLatencyMs;
                    return new EMSDecision(true, agencyOffsetMs, fireTiming);
                case GroupType.Voluntary:
                default:
                    return new EMSDecision(false, 0f, 0f);
            }
        }

        /// <summary>
        /// Calibrationフェーズ用: 候補オフセットでのEMS発火タイミング計算
        /// </summary>
        /// <param name="baselineRtMs">ベースライン反応時間（ms、ターゲット側に対応する値）</param>
        /// <param name="candidateOffsetMs">階段法の候補オフセット（= 速めたい量、ms）</param>
        /// <param name="emsLatencyMs">EMSレイテンシ（ターゲット側に対応する値）</param>
        public static EMSDecision ComputeCalibrationDecision(
            float baselineRtMs,
            float candidateOffsetMs,
            float emsLatencyMs)
        {
            float fireTiming = baselineRtMs - candidateOffsetMs - emsLatencyMs;
            return new EMSDecision(true, candidateOffsetMs, fireTiming);
        }
    }
}
