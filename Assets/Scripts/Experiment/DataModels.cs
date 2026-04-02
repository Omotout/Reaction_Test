using System;

namespace ReactionTest.Experiment
{
    [Serializable]
    public class SessionMeta
    {
        public string SubjectId;
        public GroupType Group;
        public string DatetimeStart;
        public string AppVersion;
    }

    [Serializable]
    public class TrialRecord
    {
        public PhaseType Phase;
        public TaskType Task;
        public int TrialIndex;
        public StimulusColor StimulusColor;
        public UserAction ExpectedAction;
        public UserAction ActualAction;
        public bool IsCorrect;
        public ErrorType ErrorType;
        public float ReactionTimeMs;
        public bool EMSEnabled;
        public float EMSOffsetMs;
        public string Timestamp;
    }

    [Serializable]
    public class AgencyRecord
    {
        public TaskType Task;
        public float CandidateOffsetMs;
        public int AgencyLikert7;
        public string Timestamp;
    }

    /// <summary>
    /// agency_offset.json の形式
    /// - SRT/DRT/CRT: 主体感を維持するオフセット値（ボタンフィードバックを速める量）
    /// - BaselineRT_SRT/DRT/CRT: EMSなしでの平均反応時間
    /// - EMSLatency_SRT/DRT/CRT: EMS発火→ボタン押下の遅延時間
    /// </summary>
    [Serializable]
    public class AgencyOffsetConfig
    {
        // 主体感維持オフセット（ボタンフィードバックを速める量、正の値）
        public float SRT;
        public float DRT;
        public float CRT;
        
        // ベースライン反応時間（EMSなしでの平均RT）
        public float BaselineRT_SRT;
        public float BaselineRT_DRT;
        public float BaselineRT_CRT;
        
        // EMSレイテンシ（EMS発火→ボタン押下の遅延時間）
        public float EMSLatency_SRT;
        public float EMSLatency_DRT;
        public float EMSLatency_CRT;
    }
}
