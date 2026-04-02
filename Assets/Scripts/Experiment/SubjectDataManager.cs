using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEngine;

namespace ReactionTest.Experiment
{
    /// <summary>
    /// 被験者データ管理クラス
    /// Subject IDごとにデータを保存・読み込み
    /// 再実行時は session_1, session_2 のようにサブフォルダを作成
    /// </summary>
    [Serializable]
    public class SubjectConfig
    {
        public string SubjectId;
        public GroupType Group;
        public int LatestCalibrationSession;
        public int LatestValidationSession;
        public string LastUpdated;
        
        // 最新のキャリブレーション結果
        public float SRT_Offset;
        public float DRT_Offset;
        public float CRT_Offset;
        public float BaselineRT_SRT;
        public float BaselineRT_DRT;
        public float BaselineRT_CRT;
        public float EMSLatency_SRT;
        public float EMSLatency_DRT;
        public float EMSLatency_CRT;
        
        // キャリブレーション完了フラグ
        public bool CalibrationCompleted;
    }

    public class SubjectDataManager : MonoBehaviour
    {
        [SerializeField] private string dataFolderName = "ExperimentData";
        
        private string _rootPath;
        private SubjectConfig _currentConfig;
        private string _currentSessionPath;
        
        public SubjectConfig CurrentConfig => _currentConfig;
        public string CurrentSessionPath => _currentSessionPath;
        public string RootPath => _rootPath;
        public bool HasCalibrationData => _currentConfig != null && _currentConfig.CalibrationCompleted;

        private void Awake()
        {
            // プロジェクトフォルダ直下に保存
            // Application.dataPath = {ProjectRoot}/Assets
            string projectRoot = Directory.GetParent(Application.dataPath).FullName;
            _rootPath = Path.Combine(projectRoot, dataFolderName);
            
            if (!Directory.Exists(_rootPath))
            {
                Directory.CreateDirectory(_rootPath);
            }
            
            Debug.Log($"SubjectDataManager: Data root = {_rootPath}");
        }

        /// <summary>
        /// 被験者データを読み込み、なければ新規作成
        /// </summary>
        public void LoadOrCreateSubject(string subjectId, GroupType group)
        {
            string subjectPath = GetSubjectPath(subjectId);
            string configPath = Path.Combine(subjectPath, "config.json");

            if (File.Exists(configPath))
            {
                // 既存データを読み込み
                string json = File.ReadAllText(configPath);
                _currentConfig = JsonUtility.FromJson<SubjectConfig>(json);
                _currentConfig.Group = group; // グループは更新可能
                Debug.Log($"Loaded subject data: {subjectId} (Calibration: {_currentConfig.CalibrationCompleted})");
            }
            else
            {
                // 新規作成
                Directory.CreateDirectory(subjectPath);
                _currentConfig = new SubjectConfig
                {
                    SubjectId = subjectId,
                    Group = group,
                    LatestCalibrationSession = 0,
                    LatestValidationSession = 0,
                    CalibrationCompleted = false,
                    LastUpdated = DateTime.Now.ToString("o")
                };
                SaveConfig();
                Debug.Log($"Created new subject: {subjectId}");
            }
        }

        /// <summary>
        /// 新しいセッションフォルダを作成
        /// </summary>
        public string CreateSessionFolder(ExperimentRunMode runMode)
        {
            if (_currentConfig == null)
            {
                Debug.LogError("Subject not loaded. Call LoadOrCreateSubject first.");
                return null;
            }

            string subjectPath = GetSubjectPath(_currentConfig.SubjectId);
            int sessionNum;
            string prefix;

            if (runMode == ExperimentRunMode.Calibration || runMode == ExperimentRunMode.Full)
            {
                _currentConfig.LatestCalibrationSession++;
                sessionNum = _currentConfig.LatestCalibrationSession;
                prefix = "calibration";
            }
            else
            {
                _currentConfig.LatestValidationSession++;
                sessionNum = _currentConfig.LatestValidationSession;
                prefix = "validation";
            }

            string sessionFolder = $"{prefix}_{sessionNum:D2}_{DateTime.Now:yyyyMMdd_HHmmss}";
            _currentSessionPath = Path.Combine(subjectPath, sessionFolder);
            Directory.CreateDirectory(_currentSessionPath);

            SaveConfig();
            Debug.Log($"Created session folder: {_currentSessionPath}");
            return _currentSessionPath;
        }

        /// <summary>
        /// キャリブレーション結果を保存
        /// </summary>
        public void SaveCalibrationResult(
            float srtOffset, float drtOffset, float crtOffset,
            float baselineSRT, float baselineDRT, float baselineCRT,
            float latencySRT, float latencyDRT, float latencyCRT)
        {
            if (_currentConfig == null) return;

            _currentConfig.SRT_Offset = srtOffset;
            _currentConfig.DRT_Offset = drtOffset;
            _currentConfig.CRT_Offset = crtOffset;
            _currentConfig.BaselineRT_SRT = baselineSRT;
            _currentConfig.BaselineRT_DRT = baselineDRT;
            _currentConfig.BaselineRT_CRT = baselineCRT;
            _currentConfig.EMSLatency_SRT = latencySRT;
            _currentConfig.EMSLatency_DRT = latencyDRT;
            _currentConfig.EMSLatency_CRT = latencyCRT;
            _currentConfig.CalibrationCompleted = true;
            _currentConfig.LastUpdated = DateTime.Now.ToString("o");

            SaveConfig();
            Debug.Log($"Saved calibration result for {_currentConfig.SubjectId}");
        }

        /// <summary>
        /// AgencyOffsetConfig形式で取得（EMSPolicy用）
        /// </summary>
        public AgencyOffsetConfig GetAgencyOffsetConfig()
        {
            if (_currentConfig == null || !_currentConfig.CalibrationCompleted)
            {
                return null;
            }

            return new AgencyOffsetConfig
            {
                SRT = _currentConfig.SRT_Offset,
                DRT = _currentConfig.DRT_Offset,
                CRT = _currentConfig.CRT_Offset,
                BaselineRT_SRT = _currentConfig.BaselineRT_SRT,
                BaselineRT_DRT = _currentConfig.BaselineRT_DRT,
                BaselineRT_CRT = _currentConfig.BaselineRT_CRT,
                EMSLatency_SRT = _currentConfig.EMSLatency_SRT,
                EMSLatency_DRT = _currentConfig.EMSLatency_DRT,
                EMSLatency_CRT = _currentConfig.EMSLatency_CRT
            };
        }

        /// <summary>
        /// 全被験者IDのリストを取得
        /// </summary>
        public List<string> GetAllSubjectIds()
        {
            if (!Directory.Exists(_rootPath))
            {
                return new List<string>();
            }

            return Directory.GetDirectories(_rootPath)
                .Select(Path.GetFileName)
                .Where(name => !name.StartsWith("."))
                .OrderBy(name => name)
                .ToList();
        }

        /// <summary>
        /// 被験者のセッション一覧を取得
        /// </summary>
        public List<string> GetSessionList(string subjectId)
        {
            string subjectPath = GetSubjectPath(subjectId);
            if (!Directory.Exists(subjectPath))
            {
                return new List<string>();
            }

            return Directory.GetDirectories(subjectPath)
                .Select(Path.GetFileName)
                .Where(name => name.StartsWith("calibration_") || name.StartsWith("validation_"))
                .OrderByDescending(name => name)
                .ToList();
        }

        private string GetSubjectPath(string subjectId)
        {
            return Path.Combine(_rootPath, subjectId);
        }

        private void SaveConfig()
        {
            if (_currentConfig == null) return;

            string subjectPath = GetSubjectPath(_currentConfig.SubjectId);
            string configPath = Path.Combine(subjectPath, "config.json");
            string json = JsonUtility.ToJson(_currentConfig, true);
            File.WriteAllText(configPath, json);
        }
    }
}
