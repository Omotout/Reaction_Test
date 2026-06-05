using System;
using System.IO;
using UnityEngine;

namespace ReactionTest.Experiment
{
    /// <summary>
    /// 事前/本実験で差し替え可能な実験設定。projectRoot/experiment_config.json に保存。
    /// JsonUtility互換のためpublicフィールドのみ。
    /// </summary>
    [Serializable]
    public class ExperimentConfig
    {
        // 試行数（各フェーズ独立設定）
        public int PreTrials = 80;
        public int EmsLatencyTrials = 30;
        public int Training1Trials = 60;
        public int Post1Trials = 60;
        public int Training2Trials = 60;
        public int Post2Trials = 60;

        // FastestBaseline 算出法
        public BaselineMethod BaselineMethod = BaselineMethod.Percentile;
        public float BaselinePercentileN = 10f;   // Percentile時: 下位 n%（既定 10 = Q10）
        public float BaselineSdMultiplier = 1.0f; // Sd時: mean − k × SD（既定 k=1.0）

        // EMS 介入方式（Fastest=既存ロジック / Deadline=deadline 時刻に発火）
        public InterventionMode InterventionMode = InterventionMode.Fastest;

        // Deadline mode: 左右別 deadline (ms, LED 点灯起点)
        // DeadlineInitMode=PreMedianOffset のときは Pre 終了後に Pre median から再計算される
        public float LeftDeadlineMs = 250f;
        public float RightDeadlineMs = 250f;

        // Deadline mode: 初期 deadline の決定方法
        public DeadlineInitMode DeadlineInitMode = DeadlineInitMode.Manual;
        // PreMedianOffset 時: deadline = preMedian(side) − DeadlineOffsetFromMedianMs
        public float DeadlineOffsetFromMedianMs = 0f;

        // Deadline mode: 適応的 deadline 更新
        public bool UseAdaptiveDeadline = false;
        public float TargetSuccessRateUpper = 0.70f;   // 超えれば deadline を縮める
        public float TargetSuccessRateLower = 0.50f;   // 下回れば deadline を伸ばす
        public float DeadlineStepMs = 10f;
        public float MinDeadlineMs = 100f;
        public float MaxDeadlineMs = 800f;
        public bool AdaptiveDeadlinePerSide = false;   // false=左右共通の平均で更新

        // Deadline mode: 誤反応後も deadline で EMS を発火するか（firmware 未対応のため警告のみ）
        public bool TriggerEmsAfterError = false;

        // Legacy compatibility only. EMSLatency now always runs in EMS sessions,
        // including Deadline mode, for intensity tuning and logging. Deadline firing
        // uses deadlineMs as the command time and does not subtract EMS_to_Touch.
        public bool RunEmsLatencyInDeadlineMode = false;

        // EMSタイミング（Fastest mode のみ使用）
        public float EmsOffsetMs = 0f;   // 0=FastestBaseline, >0=agency_EMS

        // ITI / 前置時間（秒）
        public float ItiMinSec = 2.0f;
        public float ItiMaxSec = 3.0f;

        // 固定タッチ閾値（手動BASELINEで調整した値）
        public int TouchThresholdRight = 30;
        public int TouchThresholdLeft = 30;

        // EMS波形（強度）
        public int EmsPulseWidthUs = 50;
        public int EmsPulseCount = 1;
        public int EmsBurstCount = 3;
        public int EmsPulseIntervalUs = 40000; // 40 ms

        // 除外基準（Unity記録時はanticipation/lapseMaxのみ。+3SDはPython側）
        public float RtAnticipationMs = 150f;
        public float RtLapseMaxMs = 1000f;
        public float LapseSdMultiplier = 3f;   // 個人内+3SD用。Python解析側でのみ使用（Unity実行時は未使用）

        // EMS_to_Touch 安定性（標本SDがこの値未満なら安定）
        public float EmsToTouchStabilitySdMs = 4f;

        /// <summary>
        /// 設定ファイルを読み込む。存在しなければ既定値を書き出して返す。
        /// 不正なJSON（手編集ミス等）は黙って既定値で上書きせず、明示メッセージで例外送出する
        /// （設定取り違えのまま実験が走るのを防ぐため）。IO例外もそのまま伝播する。
        /// </summary>
        public static ExperimentConfig LoadOrCreate(string path)
        {
            ExperimentConfig cfg;
            if (File.Exists(path))
            {
                string json = File.ReadAllText(path);
                try
                {
                    // JsonUtility はクラス型に対し null を返さない（不正JSONは ArgumentException を送出）。
                    cfg = JsonUtility.FromJson<ExperimentConfig>(json);
                }
                catch (ArgumentException e)
                {
                    throw new InvalidOperationException(
                        $"experiment_config.json の解析に失敗しました（書式を確認してください）: {path}", e);
                }
            }
            else
            {
                cfg = new ExperimentConfig();
                File.WriteAllText(path, JsonUtility.ToJson(cfg, true));
            }
            cfg.Validate();
            return cfg;
        }

        /// <summary>
        /// 範囲・整合性チェック。実験開始前に呼ぶことで、無効な値で実験が走るのを防ぐ。
        /// arduinoResponseWindowMs は Arduino integrated_full.ino の RESP_WINDOW_MS と一致させる必要がある
        /// (現状 2000ms)。deadline がこれを超えると Arduino が timeout して EMS が発火しないので拒否する。
        /// </summary>
        public void Validate(float arduinoResponseWindowMs = 2000f)
        {
            var errs = new System.Collections.Generic.List<string>();

            // 試行数
            if (PreTrials <= 0) errs.Add($"PreTrials({PreTrials}) must be > 0");
            if (EmsLatencyTrials <= 0) errs.Add($"EmsLatencyTrials({EmsLatencyTrials}) must be > 0");
            if (Training1Trials <= 0) errs.Add($"Training1Trials({Training1Trials}) must be > 0");
            if (Training2Trials <= 0) errs.Add($"Training2Trials({Training2Trials}) must be > 0");
            if (Post1Trials <= 0) errs.Add($"Post1Trials({Post1Trials}) must be > 0");
            if (Post2Trials <= 0) errs.Add($"Post2Trials({Post2Trials}) must be > 0");

            // Baseline 系
            if (BaselinePercentileN < 0f || BaselinePercentileN > 100f)
                errs.Add($"BaselinePercentileN({BaselinePercentileN}) must be in [0, 100]");
            if (BaselineSdMultiplier < 0f)
                errs.Add($"BaselineSdMultiplier({BaselineSdMultiplier}) must be >= 0");

            // ITI
            if (ItiMinSec < 0f || ItiMaxSec < ItiMinSec)
                errs.Add($"ITI: need 0 <= ItiMinSec({ItiMinSec}) <= ItiMaxSec({ItiMaxSec})");

            // EMS 波形
            if (EmsPulseWidthUs <= 0) errs.Add($"EmsPulseWidthUs({EmsPulseWidthUs}) must be > 0");
            if (EmsPulseCount <= 0) errs.Add($"EmsPulseCount({EmsPulseCount}) must be > 0");
            if (EmsBurstCount <= 0) errs.Add($"EmsBurstCount({EmsBurstCount}) must be > 0");
            if (EmsPulseIntervalUs < 0) errs.Add($"EmsPulseIntervalUs({EmsPulseIntervalUs}) must be >= 0");

            // Deadline mode 範囲
            if (MinDeadlineMs <= 0f) errs.Add($"MinDeadlineMs({MinDeadlineMs}) must be > 0");
            if (MaxDeadlineMs <= MinDeadlineMs)
                errs.Add($"MaxDeadlineMs({MaxDeadlineMs}) must be > MinDeadlineMs({MinDeadlineMs})");
            if (MaxDeadlineMs > arduinoResponseWindowMs)
                errs.Add($"MaxDeadlineMs({MaxDeadlineMs}) > Arduino RESP_WINDOW({arduinoResponseWindowMs}). " +
                         "EMS won't fire before firmware timeout.");
            if (LeftDeadlineMs < MinDeadlineMs || LeftDeadlineMs > MaxDeadlineMs)
                errs.Add($"LeftDeadlineMs({LeftDeadlineMs}) outside [{MinDeadlineMs}, {MaxDeadlineMs}]");
            if (RightDeadlineMs < MinDeadlineMs || RightDeadlineMs > MaxDeadlineMs)
                errs.Add($"RightDeadlineMs({RightDeadlineMs}) outside [{MinDeadlineMs}, {MaxDeadlineMs}]");

            // Adaptive 系
            if (!(0f <= TargetSuccessRateLower
                  && TargetSuccessRateLower < TargetSuccessRateUpper
                  && TargetSuccessRateUpper <= 1f))
                errs.Add($"need 0 <= TargetSuccessRateLower({TargetSuccessRateLower}) " +
                         $"< TargetSuccessRateUpper({TargetSuccessRateUpper}) <= 1");
            if (DeadlineStepMs <= 0f) errs.Add($"DeadlineStepMs({DeadlineStepMs}) must be > 0");

            // 除外
            if (RtAnticipationMs < 0f) errs.Add($"RtAnticipationMs({RtAnticipationMs}) must be >= 0");
            if (RtLapseMaxMs <= RtAnticipationMs)
                errs.Add($"RtLapseMaxMs({RtLapseMaxMs}) must be > RtAnticipationMs({RtAnticipationMs})");

            if (errs.Count > 0)
            {
                throw new InvalidOperationException(
                    "experiment_config.json validation failed:\n - " + string.Join("\n - ", errs));
            }
        }
    }
}
