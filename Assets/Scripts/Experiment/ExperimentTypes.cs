using System;

namespace ReactionTest.Experiment
{
    // ========================================================================
    // V3: CRT特化リファクタリング
    // - TaskType (SRT/DRT/CRT) を完全削除 → 常にCRT（左右2択）
    // - ExperimentRunMode で本実験/テスト用ゲームモードを切り替え
    // - StimulusColor を削除 → TargetSide (Left/Right) で表現
    // - PhaseType に通常6フェーズとテスト用フェーズを定義
    // ========================================================================

    /// <summary>
    /// 実験群
    /// </summary>
    public enum GroupType
    {
        AgencyEMS,
        Voluntary
    }

    public enum ExperimentRunMode
    {
        FullExperiment,
        TestGame
    }

    public enum TrialInputMode
    {
        MouseButtons,
        ArrowKeys,
        CtrlAndRightArrow
    }

    /// <summary>
    /// 実験フェーズ
    /// Practice → Baseline → EMSLatency → Calibration → Training → PostTest
    /// </summary>
    public enum PhaseType
    {
        Practice,       // 習熟: EMSなし、10〜20試行
        Baseline,       // HDDMベースライン: EMSなし、30〜50試行
        EMSLatency,     // EMSレイテンシ測定: 視覚刺激なし、左右各15〜20試行
        Calibration,    // Agency閾値探索: EMSあり、-80〜+20ms/10ms刻み
        Training,       // 介入: 群別EMS適用、30〜50試行
        PostTest,       // HDDM事後測定: EMSなし、30〜50試行
        Test            // テスト用ゲームモード: EMSなし、Ctrl/右矢印入力
    }

    /// <summary>
    /// ユーザー入力（左クリック / 右クリック / 無入力）
    /// CRT特化後もターゲット側・応答側の表現として使用
    /// </summary>
    public enum UserAction
    {
        None,
        Left,
        Right
    }

    /// <summary>
    /// エラー種別（CRT特化版）
    /// Commission は廃止（CRTでは常に左右どちらかを押す）
    /// </summary>
    public enum ErrorType
    {
        None,
        WrongSide,  // 左右誤り
        Omission    // タイムアウト（応答なし）
    }

    /// <summary>
    /// EMS発火の決定情報
    ///
    /// OffsetMs と FireTimingMs は物理的に異なる量:
    /// - OffsetMs     : 「BaselineRT より何ms前倒しして押させたいか」= Agency研究の pre-emptive gain
    /// - FireTimingMs : 「刺激提示から実際にEMSを発火するまでのms」= BaselineRT − OffsetMs − EMSLatency
    ///
    /// TrialEngine は FireTimingMs で待機・発火する。CSVには両方記録する。
    /// </summary>
    [Serializable]
    public struct EMSDecision
    {
        public bool Enabled;
        public float OffsetMs;
        public float FireTimingMs;

        public EMSDecision(bool enabled, float offsetMs, float fireTimingMs)
        {
            Enabled = enabled;
            OffsetMs = offsetMs;
            FireTimingMs = fireTimingMs;
        }
    }
}
