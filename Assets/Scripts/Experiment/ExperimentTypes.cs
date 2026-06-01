namespace ReactionTest.Experiment
{
    /// <summary>
    /// 実験フェーズ（FastestBaseline 枠組み）。1セッション＝1条件（EMS or Voluntary）。
    /// Pre → (EMSLatency:EMS条件のみ) → Training1 → Post1 → 休憩 → Training2 → Post2
    /// </summary>
    public enum PhaseType
    {
        Pre,
        EMSLatency,
        Training1,
        Post1,
        Training2,
        Post2
    }
}
