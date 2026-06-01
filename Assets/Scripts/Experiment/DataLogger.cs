using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using UnityEngine;

namespace ReactionTest.Experiment
{
    /// <summary>
    /// 試行データCSV書き出し（FastestBaseline）。メモリバッファ＋フェーズ終了時一括Flush。
    /// 生RTは無加工で保持（エラー試行も IsCorrect=0 で必ず記録）。
    /// </summary>
    public class DataLogger : MonoBehaviour
    {
        [SerializeField] private string trialFileName = "trial_log.csv";

        [Tooltip("N試行ごとに自動Flush（クラッシュ時のデータ消失防止）。0で無効。")]
        [SerializeField] private int autoFlushInterval = 10;

        private string _outputDir;
        private string _trialPath;
        private readonly List<TrialRecord> _buffer = new List<TrialRecord>();

        private const string CsvHeader =
            "SubjectID,Condition,SessionDate,Phase,TrialNumber,StimColor,CorrectHand,ResponseSide,IsCorrect," +
            "ReactionTime_ms,Peak,ExclusionFlag,EmsFired,EmsSide,EmsFireTiming_ms,EmsToTouch_ms,Timestamp";

        public void InitializeWithPath(SessionMeta session, string outputDir)
        {
            _outputDir = outputDir;
            Directory.CreateDirectory(_outputDir);

            _trialPath = Path.Combine(_outputDir, trialFileName);
            if (!File.Exists(_trialPath))
            {
                File.WriteAllText(_trialPath, CsvHeader + Environment.NewLine, Encoding.UTF8);
            }

            SaveSessionInfo(session);
            Debug.Log($"DataLogger: Output directory = {_outputDir}");
        }

        private void SaveSessionInfo(SessionMeta session)
        {
            string sessionInfoPath = Path.Combine(_outputDir, "session_info.json");
            File.WriteAllText(sessionInfoPath, JsonUtility.ToJson(session, true), Encoding.UTF8);
        }

        public string GetOutputDirectory() => _outputDir;

        /// <summary>試行データをメモリバッファに追加（エラー試行も必ず追加）。autoFlushIntervalで定期Flush。</summary>
        public void AppendTrial(TrialRecord row)
        {
            _buffer.Add(row);
            if (autoFlushInterval > 0 && _buffer.Count >= autoFlushInterval)
            {
                FlushBuffer();
            }
        }

        /// <summary>バッファ内の全データをCSVに一括書き出し（フェーズ終了時に呼ぶ）。</summary>
        public void FlushBuffer()
        {
            if (_buffer.Count == 0) return;

            var sb = new StringBuilder();
            foreach (var row in _buffer)
            {
                sb.AppendLine(FormatTrialLine(row));
            }

            File.AppendAllText(_trialPath, sb.ToString(), Encoding.UTF8);
            Debug.Log($"DataLogger: Flushed {_buffer.Count} trials to {_trialPath}");
            _buffer.Clear();
        }

        /// <summary>1試行分のCSV行を生成（RFC 4180 準拠エスケープ）。</summary>
        private string FormatTrialLine(TrialRecord r)
        {
            var inv = System.Globalization.CultureInfo.InvariantCulture;
            return string.Join(",",
                CsvEscape(r.SubjectId),
                CsvEscape(r.Condition.ToString()),
                CsvEscape(r.SessionDate),
                CsvEscape(r.Phase.ToString()),
                r.TrialNumber.ToString(inv),
                CsvEscape(r.StimColor.ToString()),
                CsvEscape(r.CorrectHand.ToString()),
                CsvEscape(r.ResponseSide.ToString()),
                r.IsCorrect ? "1" : "0",
                r.ReactionTimeMs.ToString("F3", inv),
                r.Peak.ToString(inv),
                CsvEscape(r.ExclusionFlag.ToString()),
                r.EmsFired ? "1" : "0",
                CsvEscape(r.EmsSide.ToString()),
                r.EmsFireTimingMs.ToString("F3", inv),
                r.EmsToTouchMs.ToString("F3", inv),
                CsvEscape(r.Timestamp));
        }

        /// <summary>
        /// RFC 4180 準拠の CSV フィールドエスケープ。カンマ/ダブルクオート/改行を含む値は
        /// 全体をダブルクオートで囲み、内部のダブルクオートを2連化する。
        /// </summary>
        private static string CsvEscape(string value)
        {
            if (value == null) return string.Empty;
            bool needsQuoting = value.IndexOfAny(new[] { ',', '"', '\n', '\r' }) >= 0;
            if (!needsQuoting) return value;
            return "\"" + value.Replace("\"", "\"\"") + "\"";
        }

        private void OnApplicationQuit() => FlushBuffer();
        private void OnDestroy() => FlushBuffer();
    }
}
