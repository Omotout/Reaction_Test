using System;

namespace ReactionTest.Experiment
{
    // ========================================================================
    // V3: HDDM解析対応データモデル
    // - TrialRecord: 1試行 = 1行の統一フォーマット（Agency回答も統合）
    // - AgencyRecord: 削除（TrialRecord.AgencyLikert に統合）
    // - AgencyOffsetConfig: SRT/DRTフィールド削除、左右別に簡素化
    // - 【超重要】エラー試行も IsCorrect=0 として必ず記録（DDM解析で必須）
    // ========================================================================

    [Serializable]
    public class SessionMeta
    {
        public string SubjectId;
        public GroupType Group;
        public string DatetimeStart;
        public string AppVersion;
        public string RunMode;

        // ランダム化のシード値（再現性用）
        public int TrialListSeedPractice;
        public int TrialListSeedBaseline;
        public int TrialListSeedTraining;
        public int TrialListSeedPostTest;
        public int TrialListSeedTest;
    }

    /// <summary>
    /// CSVヘッダー: SubjectID,Group,Phase,TrialNumber,TargetSide,ResponseSide,IsCorrect,ReactionTime_ms,EMSOffset_ms,EMSFireTiming_ms,AgencyYes,Timestamp
    /// </summary>
    [Serializable]
    public class TrialRecord
    {
        /// <summary>被験者ID</summary>
        public string SubjectId;

        /// <summary>実験群 (AgencyEMS / Voluntary)</summary>
        public GroupType Group;

        /// <summary>実験フェーズ</summary>
        public PhaseType Phase;

        /// <summary>フェーズ内の試行番号（1-indexed）</summary>
        public int TrialNumber;

        /// <summary>ターゲット側 (Left / Right)。EMSLatencyフェーズではEMS発火チャンネル</summary>
        public UserAction TargetSide;

        /// <summary>応答側 (Left / Right / None=タイムアウト)</summary>
        public UserAction ResponseSide;

        /// <summary>正解フラグ（DDM解析でエラー時のRTが必須のため、エラーも必ず記録）</summary>
        public bool IsCorrect;

        /// <summary>反応時間（ミリ秒）。タイムアウト時は-1</summary>
        public float ReactionTimeMs;

        /// <summary>
        /// EMSオフセット（= BaselineRTより速めたい量、ms）。Agency研究の pre-emptive gain。
        /// Calibrationでは候補値、Trainingでは確定値。EMSなしの場合は0。
        /// </summary>
        public float EMSOffsetMs;

        /// <summary>
        /// 実発火タイミング（= 刺激提示からEMS発火までのms）。
        /// = BaselineRT - EMSOffsetMs - EMSLatency。EMSなしの場合は0。
        /// </summary>
        public float EMSFireTimingMs;

        /// <summary>Agency評価（true=自分で押した、false=勝手に動いた）。Calibrationフェーズのみ使用</summary>
        public bool AgencyYes;

        /// <summary>タイムスタンプ (ISO 8601)</summary>
        public string Timestamp;
    }

    /// <summary>
    /// キャリブレーション結果（左右別）
    /// EMSタイミング = BaselineRT(side) - AgencyOffset(side) - EMSLatency(side)
    /// </summary>
    [Serializable]
    public class AgencyOffsetConfig
    {
        /// <summary>左チャンネルのAgency維持オフセット（ms）</summary>
        public float OffsetLeft;

        /// <summary>右チャンネルのAgency維持オフセット（ms）</summary>
        public float OffsetRight;

        /// <summary>左ターゲットのベースライン反応時間（EMSなし、IQR外れ値除去→平均）</summary>
        public float BaselineRTLeft;

        /// <summary>右ターゲットのベースライン反応時間（EMSなし、IQR外れ値除去→平均）</summary>
        public float BaselineRTRight;

        /// <summary>左チャンネルのEMSレイテンシ（通電→キー押下）</summary>
        public float EMSLatencyLeft;

        /// <summary>右チャンネルのEMSレイテンシ（通電→キー押下）</summary>
        public float EMSLatencyRight;
    }
}
