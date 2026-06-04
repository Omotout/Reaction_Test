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
        public float EmsFireTimingMs;
        public float EmsToTouchMs;
        public string Timestamp;          // ISO 8601
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
