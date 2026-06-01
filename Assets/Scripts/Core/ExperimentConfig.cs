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
        // 試行数
        public int PreTrials = 80;
        public int EmsLatencyTrials = 30;
        public int TrainingTrials = 60;
        public int PostTrials = 80;

        // EMSタイミング
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
            if (File.Exists(path))
            {
                string json = File.ReadAllText(path);
                try
                {
                    // JsonUtility はクラス型に対し null を返さない（不正JSONは ArgumentException を送出）。
                    return JsonUtility.FromJson<ExperimentConfig>(json);
                }
                catch (ArgumentException e)
                {
                    throw new InvalidOperationException(
                        $"experiment_config.json の解析に失敗しました（書式を確認してください）: {path}", e);
                }
            }
            var def = new ExperimentConfig();
            File.WriteAllText(path, JsonUtility.ToJson(def, true));
            return def;
        }
    }
}
