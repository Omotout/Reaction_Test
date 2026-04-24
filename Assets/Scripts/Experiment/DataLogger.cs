using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using UnityEngine;

namespace ReactionTest.Experiment
{
    // ========================================================================
    // V3: HDDM解析対応 + メモリバッファ方式
    // - CSVヘッダーをHDDM仕様に厳格化
    // - agency_log.csv を廃止、全データを trial_log.csv に統一
    // - 毎試行のFile.AppendAllText を廃止 → メモリバッファ + フェーズ終了時一括書き出し
    // - 360fps環境でのUpdate()内I/O負荷を回避
    // - 【超重要】エラー試行も IsCorrect=0 として絶対に破棄しない
    // ========================================================================

    public class DataLogger : MonoBehaviour
    {
        [SerializeField] private string trialFileName = "trial_log.csv";

        [Tooltip("N試行ごとに自動Flush（クラッシュ時のデータ消失防止）。0で無効。")]
        [SerializeField] private int autoFlushInterval = 10;

        private string _outputDir;
        private string _trialPath;

        // メモリバッファ: フェーズ終了時に FlushBuffer() で一括書き出し
        private readonly List<TrialRecord> _buffer = new List<TrialRecord>();

        /// <summary>
        /// CSVヘッダー（HDDM解析用）
        /// EMSOffset_ms     : 速めたい量（= BaselineRTより何ms前倒しして押させたいか）
        /// </summary>
        private const string CsvHeader =
            "SubjectID,Group,Phase,TrialNumber,TargetSide,ResponseSide,IsCorrect,ReactionTime_ms,EMSOffset_ms,EMSFireTiming_ms,AgencyYes,Timestamp";

        /// <summary>
        /// 従来の初期化（後方互換性用）
        /// </summary>
        public void Initialize(SessionMeta session)
        {
            string outputFolderName = "ReactionTestLogs";
            string dir = Path.Combine(Application.persistentDataPath, outputFolderName,
                session.SubjectId + "_" + DateTime.Now.ToString("yyyyMMdd_HHmmss"));
            InitializeWithPath(session, dir);
        }

        /// <summary>
        /// 指定されたパスに初期化（SubjectDataManager連携用）
        /// </summary>
        public void InitializeWithPath(SessionMeta session, string outputDir)
        {
            _outputDir = outputDir;
            Directory.CreateDirectory(_outputDir);

            _trialPath = Path.Combine(_outputDir, trialFileName);

            // CSVヘッダーを書き込み（ファイルが存在しない場合のみ）
            if (!File.Exists(_trialPath))
            {
                File.WriteAllText(_trialPath, CsvHeader + Environment.NewLine, Encoding.UTF8);
            }

            // セッション情報をsession_info.jsonとして保存
            SaveSessionInfo(session);

            Debug.Log($"DataLogger: Output directory = {_outputDir}");
        }

        private void SaveSessionInfo(SessionMeta session)
        {
            string sessionInfoPath = Path.Combine(_outputDir, "session_info.json");
            string json = JsonUtility.ToJson(session, true);
            File.WriteAllText(sessionInfoPath, json, Encoding.UTF8);
        }

        public string GetOutputDirectory()
        {
            return _outputDir;
        }

        /// <summary>
        /// 試行データをメモリバッファに追加（ディスクI/O発生なし）
        /// エラー試行も IsCorrect=false のまま必ず追加する
        /// autoFlushInterval > 0 の場合、N試行ごとに自動Flush（クラッシュ保護）
        /// </summary>
        public void AppendTrial(TrialRecord row)
        {
            _buffer.Add(row);

            if (autoFlushInterval > 0 && _buffer.Count >= autoFlushInterval)
            {
                FlushBuffer();
            }
        }

        /// <summary>
        /// バッファ内の全データをCSVに一括書き出し
        /// フェーズ終了時に呼ぶこと
        /// </summary>
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

        /// <summary>
        /// 1試行分のCSV行を生成（RFC 4180 準拠エスケープ）
        /// </summary>
        private string FormatTrialLine(TrialRecord row)
        {
            return string.Join(",",
                CsvEscape(row.SubjectId),
                CsvEscape(row.Group.ToString()),
                CsvEscape(row.Phase.ToString()),
                row.TrialNumber.ToString(System.Globalization.CultureInfo.InvariantCulture),
                CsvEscape(row.TargetSide.ToString()),
                CsvEscape(row.ResponseSide.ToString()),
                row.IsCorrect ? "1" : "0",
                row.ReactionTimeMs.ToString("F3", System.Globalization.CultureInfo.InvariantCulture),
                row.EMSOffsetMs.ToString("F3", System.Globalization.CultureInfo.InvariantCulture),
                row.EMSFireTimingMs.ToString("F3", System.Globalization.CultureInfo.InvariantCulture),
                row.AgencyYes ? "1" : "0",
                CsvEscape(row.Timestamp));
        }

        /// <summary>
        /// RFC 4180 準拠の CSV フィールドエスケープ。
        /// 値にカンマ、ダブルクオート、改行が含まれる場合は値全体をダブルクオートで
        /// 囲み、内部のダブルクオートは 2 連化する。被験者IDや自由記述が将来的に
        /// 拡張されても列崩れが起きないようにする。
        /// </summary>
        private static string CsvEscape(string value)
        {
            if (value == null) return string.Empty;
            bool needsQuoting = value.IndexOfAny(new[] { ',', '"', '\n', '\r' }) >= 0;
            if (!needsQuoting) return value;
            return "\"" + value.Replace("\"", "\"\"") + "\"";
        }

        /// <summary>
        /// アプリケーション終了時にバッファを確実に書き出す
        /// </summary>
        private void OnApplicationQuit()
        {
            FlushBuffer();
        }

        /// <summary>
        /// オブジェクト破棄時にもバッファを書き出す（安全弁）
        /// </summary>
        private void OnDestroy()
        {
            FlushBuffer();
        }
    }
}
