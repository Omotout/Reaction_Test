using System;

namespace ReactionTest.Experiment
{
    public enum TaskType
    {
        SRT,
        DRT,
        CRT
    }

    public enum GroupType
    {
        AgencyEMS,
        Voluntary
    }

    public enum PhaseType
    {
        Baseline,
        EMSLatency,     // EMSレイテンシ測定（0msオフセットで複数試行）
        AgencySearch,
        Training,
        PostTest
    }

    public enum ExperimentRunMode
    {
        Full,
        Calibration,    // 実験1: Baseline + EMSLatency + AgencySearch
        Validation      // 実験2: Training + PostTest
    }

    public enum StimulusColor
    {
        Green,
        Red
    }

    public enum UserAction
    {
        None,
        Left,
        Right
    }

    public enum ErrorType
    {
        None,
        Commission,
        Omission,
        WrongSide
    }

    [Serializable]
    public struct EMSDecision
    {
        public bool Enabled;
        public float OffsetMs;

        public EMSDecision(bool enabled, float offsetMs)
        {
            Enabled = enabled;
            OffsetMs = offsetMs;
        }
    }
}
