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
        Lapse,
        Timeout
    }

    /// <summary>FastestBaseline 算出法。Percentile=下位n%、Sd=mean − k×SD。</summary>
    public enum BaselineMethod
    {
        Percentile,
        Sd
    }

    /// <summary>
    /// EMS 介入方式。
    /// Fastest: 既存ロジック。baseline − offset − EMS_to_Touch のタイミングで先行発火し、参加者のタッチを補助する。
    /// Deadline: 刺激から deadlineMs 経過時点で EMS を発火する。deadline 前に参加者が（誤答含めて）タッチすれば
    ///           Arduino loop が exit して EMS は発火しない（既存ファーム挙動）。
    ///           triggerEmsAfterError=true (誤反応後も deadline で EMS を発火) は firmware 未対応のため警告のみ。
    /// </summary>
    public enum InterventionMode
    {
        Fastest,
        Deadline
    }

    /// <summary>1試行の結果分類（解析・モニタリング用）。</summary>
    public enum TrialOutcome
    {
        Timeout,                       // 反応なし
        CorrectBeforeDeadline,         // 正答 & EMS未発火（Fastest: 通常は Pre/Post/Voluntary、Deadline: deadline 前の正答）
        EmsTriggeredAfterDeadline,     // 正答 & EMS発火後（Fastest: 通常の Training, Deadline: deadline 後のEMS補助）
        ErrorBeforeDeadline,           // 誤反応 & EMS未発火
        ErrorAfterEms                  // 誤反応 & EMS発火後（現状ファームでは発生し得ないが将来拡張用）
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
