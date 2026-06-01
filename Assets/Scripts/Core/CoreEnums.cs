namespace ReactionTest.Experiment
{
    /// <summary>左/右/無入力。ターゲット側・応答側・EMSチャンネルの表現に共用。</summary>
    public enum UserAction
    {
        None,
        Left,
        Right
    }

    /// <summary>刺激色（2色LED）。</summary>
    public enum StimColor
    {
        Red,
        Green
    }

    /// <summary>実験条件（被験者内2条件）。</summary>
    public enum ExperimentCondition
    {
        EMS,
        Voluntary
    }

    /// <summary>条件提示順（別日カウンターバランス）。</summary>
    public enum ConditionOrder
    {
        EmsFirst,
        VoluntaryFirst
    }

    /// <summary>刺激-反応マッピング。RedRight=赤→右手/緑→左手。RedLeft=その逆。</summary>
    public enum SRMapping
    {
        RedRight,
        RedLeft
    }

    /// <summary>除外フラグ（生データは保持し、解析用に分類のみ記録）。</summary>
    public enum ExclusionFlag
    {
        Normal,
        Anticipation,
        Lapse
    }

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
