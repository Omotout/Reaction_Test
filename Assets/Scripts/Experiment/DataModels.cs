using System;

namespace ReactionTest.Experiment
{
    [Serializable]
    public class SessionMeta
    {
        public string SubjectId;
        public ExperimentCondition Condition;
        public int SessionNumber;
        public SRMapping Mapping;
        public string SessionDate;     // yyyy-MM-dd
        public string DatetimeStart;   // ISO 8601
        public string DatetimeEnd;     // ISO 8601 (Finish 時に上書き)
        public bool Aborted;           // true=中断 / false=完走
        public string AbortReason;     // 中断理由（空=完走）
        public string AppVersion;

        public int SeedPre;
        public int SeedEMSLatency;
        public int SeedTraining1;
        public int SeedPost1;
        public int SeedTraining2;
        public int SeedPost2;
    }

    [Serializable]
    public class TrialRecord
    {
        public string SubjectId;
        public ExperimentCondition Condition;
        public string SessionDate;
        public PhaseType Phase;
        public int TrialNumber;
        public StimColor StimColor;
        public UserAction CorrectHand;
        public UserAction ResponseSide;   // touched side, None=timeout
        public bool IsCorrect;
        public float ReactionTimeMs;      // raw, -1=timeout
        public int Peak;
        public ExclusionFlag ExclusionFlag;
        public bool EmsFired;
        public UserAction EmsSide;
        public float EmsFireTimingMs;     // 予定発火時刻 (LED起点 ms)。Fastest=baseline−offset−emsToTouch / Deadline=deadlineMs
        public float EmsToTouchMs;
        public string Timestamp;          // ISO 8601

        // Intervention extension（Fastest / Deadline 共通の解析を可能にする）
        public InterventionMode InterventionMode;
        public float DeadlineMs;          // Deadline mode の deadline。Fastest=-1
        public bool ResponseBeforeDeadline;
        public bool EmsScheduled;         // この試行で EMS が予定されていたか（Voluntary/Pre/Post=false）
        public bool EmsCanceled;          // 予定されていたが発火しなかった（タッチ先行で Arduino loop exit）
        public float TouchAfterEmsMs;     // EMS 発火から検出までの経過 (ms)。EMS未発火 or 反応なしは -1
        public TrialOutcome Outcome;
    }

    /// <summary>
    /// Deadline mode の block-by-block 適応イベント。deadline_adaptations.jsonl に1ブロック=1行で追記される。
    /// </summary>
    [Serializable]
    public class DeadlineAdaptationEvent
    {
        public PhaseType Phase;
        public int BlockTrials;           // このブロックの試行数
        public int CountCorrectBeforeDeadline;
        public int CountTotalNonTimeout;
        public float SuccessRate;         // CorrectBeforeDeadline / TotalNonTimeout
        public float DeadlineLeftMsBefore;
        public float DeadlineRightMsBefore;
        public float DeadlineLeftMsAfter;
        public float DeadlineRightMsAfter;
        public string Decision;           // "tighten" / "loosen" / "hold"
        public string Timestamp;
    }

    /// <summary>セッション毎のキャリブレーション結果（左右別、calibration.jsonに保存）。</summary>
    [Serializable]
    public class CalibrationData
    {
        public BaselineMethod BaselineMethod;
        public float BaselineParameter;   // Percentile時=n%、Sd時=k
        public float BaselineLeft;
        public float BaselineRight;
        public float EmsToTouchLeft;
        public float EmsToTouchRight;
    }
}
