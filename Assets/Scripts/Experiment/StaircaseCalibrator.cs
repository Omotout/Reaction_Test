using System.Collections.Generic;
using System.Linq;
using UnityEngine;

namespace ReactionTest.Experiment
{
    // ========================================================================
    // 適応的インターリーブ階段法（Adaptive Interleaved Staircase）
    //
    // 左右独立に Agency の限界オフセットを探索する。
    // 心理物理学の階段法に基づき、反転回数に応じてステップ幅を動的に縮小し、
    // Agency維持の限界オフセットに収束させる。
    //
    // アルゴリズム:
    //   1. 毎試行、ターゲット側を PickSide() で決定
    //      （両側未収束なら50/50ランダム、片側収束後は未収束側を確定選択）
    //   2. 該当する側の currentOffset でEMSを発火
    //   3. 事後のAgency回答が前回から反転すれば reversals を加算
    //   4. Yes → offset をマイナス方向（より速いEMS = 難しく）
    //      No  → offset をプラス方向（より遅いEMS = 簡単に）
    //   5. 両側とも TARGET_REVERSALS 回反転したら終了
    //   6. 最終値 = 反転時のオフセット値の平均
    //
    // 特殊処理:
    //   - エラー試行（IsCorrect==false）: Agency回答無効、更新しない
    //   - キャッチ試行（両側収束時の残試行のみ発生しうる）:
    //     反転時の平均オフセットを固定使用、Agency UIは表示するが回答は破棄
    // ========================================================================

    public class StaircaseCalibrator
    {
        // ── 定数 ──
        public const int TARGET_REVERSALS = 5;

        // 先行研究 (Kasahara et al. CHI'21) の Agency 閾値が概ね 40〜80ms のため、
        // その近傍から開始して収束試行数を減らす。
        public const float INITIAL_OFFSET = 40f;  // ms

        // ── 左右独立のステート ──
        private readonly StaircaseLadder _left;
        private readonly StaircaseLadder _right;

        public StaircaseCalibrator()
        {
            _left = new StaircaseLadder(INITIAL_OFFSET);
            _right = new StaircaseLadder(INITIAL_OFFSET);
        }

        // ── 収束判定 ──
        public bool IsConverged => _left.IsConverged && _right.IsConverged;
        public bool IsLeftConverged => _left.IsConverged;
        public bool IsRightConverged => _right.IsConverged;

        /// <summary>
        /// 次試行のターゲット側を決定する。
        /// 片側が収束済みで反対側が未収束なら未収束側を確定的に選ぶ（キャッチ試行で試行数を浪費しないため）。
        /// 両側とも未収束、または両側とも収束済みの場合は50/50ランダム。
        /// </summary>
        public UserAction PickSide()
        {
            if (_left.IsConverged && !_right.IsConverged) return UserAction.Right;
            if (!_left.IsConverged && _right.IsConverged) return UserAction.Left;
            return Random.value < 0.5f ? UserAction.Left : UserAction.Right;
        }

        /// <summary>
        /// 指定サイドの現在のオフセットを取得。
        /// 収束済みの場合は反転時オフセットの平均値（固定）を返す。
        /// </summary>
        public float GetCurrentOffset(UserAction side)
        {
            var ladder = GetLadder(side);
            return ladder.IsConverged ? ladder.GetFinalOffset() : ladder.CurrentOffset;
        }

        /// <summary>
        /// 指定サイドがキャッチ試行かどうか（収束済み側がランダムで選ばれた場合）
        /// </summary>
        public bool IsCatchTrial(UserAction side)
        {
            return GetLadder(side).IsConverged;
        }

        /// <summary>
        /// Agency回答に基づいて階段を更新する。
        /// エラー試行・キャッチ試行は自動的にスキップされる。
        /// </summary>
        /// <param name="side">ターゲット側</param>
        /// <param name="agencyYes">主体感があったか (Yes/No)</param>
        /// <param name="isCorrect">正答フラグ（falseなら更新しない）</param>
        public void Update(UserAction side, bool agencyYes, bool isCorrect)
        {
            // エラー試行は破棄（Offset値や反転回数は一切更新しない）
            if (!isCorrect) return;

            var ladder = GetLadder(side);

            // 収束済みならダミー試行 → 更新しない
            if (ladder.IsConverged) return;

            ladder.Update(agencyYes);
        }

        /// <summary>
        /// 最終的なAgency限界オフセット（反転時のオフセット値の平均）
        /// </summary>
        public float GetFinalOffset(UserAction side)
        {
            return GetLadder(side).GetFinalOffset();
        }

        /// <summary>
        /// 現在の反転回数
        /// </summary>
        public int GetReversals(UserAction side)
        {
            return GetLadder(side).Reversals;
        }

        private StaircaseLadder GetLadder(UserAction side)
        {
            return side == UserAction.Left ? _left : _right;
        }
    }

    // ========================================================================
    // 片側分の階段ステート
    // ========================================================================
    internal class StaircaseLadder
    {
        public float CurrentOffset;
        public int Reversals;
        public readonly List<float> ReversalOffsets = new List<float>();

        // 前回のAgency回答（null = まだ回答なし）
        private bool? _lastAnswer;

        public bool IsConverged => Reversals >= StaircaseCalibrator.TARGET_REVERSALS;

        public StaircaseLadder(float initialOffset)
        {
            CurrentOffset = initialOffset;
            Reversals = 0;
        }

        /// <summary>
        /// 適応的ステップサイズ（反転回数に応じて縮小）
        /// 反転 0〜1回: 10ms
        /// 反転 2〜3回: 5ms
        /// 反転 4回以上: 3ms（ハードウェア限界）
        /// </summary>
        public float GetStepSize()
        {
            if (Reversals <= 1) return 10f;
            if (Reversals <= 3) return 5f;
            return 3f;
        }

        /// <summary>
        /// 最終オフセット = 反転時のオフセット値の平均
        /// 反転が未発生の場合は現在のオフセットを返す
        /// </summary>
        public float GetFinalOffset()
        {
            if (ReversalOffsets.Count == 0) return CurrentOffset;
            return ReversalOffsets.Average();
        }

        /// <summary>
        /// Agency回答に基づいてオフセットを更新
        /// </summary>
        /// <param name="agencyYes">true = 主体感あり, false = 主体感なし</param>
        public void Update(bool agencyYes)
        {
            // 反転チェック: 前回と今回で回答が切り替わったか
            if (_lastAnswer.HasValue && _lastAnswer.Value != agencyYes)
            {
                Reversals++;
                ReversalOffsets.Add(CurrentOffset);

                // この反転で収束に達した場合、これ以上オフセットを動かさない
                if (IsConverged) 
                {
                    _lastAnswer = agencyYes;
                    return;
                }
            }

            _lastAnswer = agencyYes;

            float step = GetStepSize();
            if (agencyYes)
            {
                // 主体感あり → オフセットをマイナス方向に（より速いEMS = 難しく）
                CurrentOffset -= step;
            }
            else
            {
                // 主体感なし → オフセットをプラス方向に（より遅いEMS = 簡単に）
                CurrentOffset += step;
            }
        }
    }
}
