using UnityEngine;

namespace ReactionTest.Experiment
{
    // ========================================================================
    // V3: CRT固定化
    // - TaskType引数を全メソッドから削除
    // - 常にCRT（左右2択）として振る舞う
    // - 刺激: 50%で左、50%で右
    // - 正解: ターゲット側と同じ側をクリック
    // ========================================================================

    public static class TaskRule
    {
        /// <summary>
        /// ターゲット側をランダムに決定（CRT: 左右50%）
        /// </summary>
        public static UserAction PickTargetSide()
        {
            return Random.value < 0.5f ? UserAction.Left : UserAction.Right;
        }

        /// <summary>
        /// 期待される応答を返す（CRT: ターゲットと同じ側）
        /// </summary>
        public static UserAction GetExpectedAction(UserAction targetSide)
        {
            return targetSide;
        }

        /// <summary>
        /// 応答を評価する
        /// CRT固定のため Commission エラーは発生しない（常に左右どちらかを押す）
        /// 【重要】エラー試行もデータとして記録する（DDM解析で必須）
        /// </summary>
        public static bool Evaluate(UserAction targetSide, UserAction actualAction, out ErrorType errorType)
        {
            if (actualAction == UserAction.None)
            {
                errorType = ErrorType.Omission;
                return false;
            }

            if (actualAction == targetSide)
            {
                errorType = ErrorType.None;
                return true;
            }

            errorType = ErrorType.WrongSide;
            return false;
        }
    }
}
