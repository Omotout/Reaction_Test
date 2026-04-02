using UnityEngine;

namespace ReactionTest.Experiment
{
    public static class TaskRule
    {
        public static StimulusColor PickStimulus(TaskType taskType)
        {
            if (taskType == TaskType.SRT)
            {
                return StimulusColor.Green;
            }

            return Random.value < 0.5f ? StimulusColor.Green : StimulusColor.Red;
        }

        public static UserAction GetExpectedAction(TaskType taskType, StimulusColor stimulusColor)
        {
            switch (taskType)
            {
                case TaskType.SRT:
                    return UserAction.Left;
                case TaskType.DRT:
                    return stimulusColor == StimulusColor.Green ? UserAction.Left : UserAction.None;
                case TaskType.CRT:
                    return stimulusColor == StimulusColor.Green ? UserAction.Left : UserAction.Right;
                default:
                    return UserAction.None;
            }
        }

        public static bool Evaluate(TaskType taskType, StimulusColor stimulusColor, UserAction actualAction, out ErrorType errorType)
        {
            UserAction expectedAction = GetExpectedAction(taskType, stimulusColor);
            bool isCorrect = expectedAction == actualAction;

            if (isCorrect)
            {
                errorType = ErrorType.None;
                return true;
            }

            if (expectedAction == UserAction.None && actualAction != UserAction.None)
            {
                errorType = ErrorType.Commission;
                return false;
            }

            if (expectedAction != UserAction.None && actualAction == UserAction.None)
            {
                errorType = ErrorType.Omission;
                return false;
            }

            errorType = ErrorType.WrongSide;
            return false;
        }
    }
}
