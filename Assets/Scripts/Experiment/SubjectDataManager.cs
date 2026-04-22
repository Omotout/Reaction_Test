using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEngine;

namespace ReactionTest.Experiment
{
    // ========================================================================
    // V3: CRT特化 — SRT/DRTフィールド完全削除、左右別オフセット対応
    // - SubjectConfig: 左右別のAgencyオフセットとEMSレイテンシを保存
    // - ExperimentRunMode依存を削除 → セッション名を "session_XX" に統一
    // ========================================================================

    [Serializable]
    public class SubjectConfig
    {
        public string SubjectId;
        public GroupType Group;
        public int LatestSessionNumber;
        public string LastUpdated;

        // CRT用キャリブレーション結果（左右別）
        public float AgencyOffsetLeft;
        public float AgencyOffsetRight;
        public float BaselineRTLeft;
        public float BaselineRTRight;
        public float EMSLatencyLeft;
        public float EMSLatencyRight;

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
        /// 被験者データを読み込み、なければ新規作成。
        /// 既存被験者の場合は保存済みGroupを優先し、Inspector値との不一致はエラーログを出す。
        /// 群を変更したい場合は被験者フォルダを削除またはリネームして新規作成扱いにする。
        /// </summary>
        /// <returns>実際に採用された群（既存なら保存済み、新規ならInspector指定）</returns>
        public GroupType LoadOrCreateSubject(string subjectId, GroupType group)
        {
            string subjectPath = GetSubjectPath(subjectId);
            string configPath = Path.Combine(subjectPath, "config.json");

            if (File.Exists(configPath))
            {
                string json = File.ReadAllText(configPath);
                _currentConfig = JsonUtility.FromJson<SubjectConfig>(json);

                if (_currentConfig.Group != group)
                {
                    Debug.LogError(
                        $"Group mismatch for {subjectId}: saved={_currentConfig.Group}, inspector={group}. " +
                        $"Using SAVED group to preserve data integrity. " +
                        $"To change groups, delete or rename the subject folder.");
                }

                Debug.Log($"Loaded subject data: {subjectId} " +
                          $"(Group: {_currentConfig.Group}, Calibration: {_currentConfig.CalibrationCompleted})");
            }
            else
            {
                Directory.CreateDirectory(subjectPath);
                _currentConfig = new SubjectConfig
                {
                    SubjectId = subjectId,
                    Group = group,
                    LatestSessionNumber = 0,
                    CalibrationCompleted = false,
                    LastUpdated = DateTime.Now.ToString("o")
                };
                SaveConfig();
                Debug.Log($"Created new subject: {subjectId} (Group: {group})");
            }

            return _currentConfig.Group;
        }

        /// <summary>
        /// 新しいセッションフォルダを作成
        /// ExperimentRunMode廃止 → 統一的な "session_XX" 命名
        /// </summary>
        public string CreateSessionFolder()
        {
            if (_currentConfig == null)
            {
                Debug.LogError("Subject not loaded. Call LoadOrCreateSubject first.");
                return null;
            }

            string subjectPath = GetSubjectPath(_currentConfig.SubjectId);
            _currentConfig.LatestSessionNumber++;

            string sessionFolder = $"session_{_currentConfig.LatestSessionNumber:D2}_{DateTime.Now:yyyyMMdd_HHmmss}";
            _currentSessionPath = Path.Combine(subjectPath, sessionFolder);
            Directory.CreateDirectory(_currentSessionPath);

            SaveConfig();
            Debug.Log($"Created session folder: {_currentSessionPath}");
            return _currentSessionPath;
        }

        /// <summary>
        /// キャリブレーション結果を保存（左右別）
        /// </summary>
        public void SaveCalibrationResult(
            float agencyOffsetLeft, float agencyOffsetRight,
            float baselineRTLeft, float baselineRTRight,
            float emsLatencyLeft, float emsLatencyRight)
        {
            if (_currentConfig == null) return;

            _currentConfig.AgencyOffsetLeft = agencyOffsetLeft;
            _currentConfig.AgencyOffsetRight = agencyOffsetRight;
            _currentConfig.BaselineRTLeft = baselineRTLeft;
            _currentConfig.BaselineRTRight = baselineRTRight;
            _currentConfig.EMSLatencyLeft = emsLatencyLeft;
            _currentConfig.EMSLatencyRight = emsLatencyRight;
            _currentConfig.CalibrationCompleted = true;
            _currentConfig.LastUpdated = DateTime.Now.ToString("o");

            SaveConfig();
            Debug.Log($"Saved calibration result for {_currentConfig.SubjectId} " +
                      $"(OffsetL={agencyOffsetLeft}ms, OffsetR={agencyOffsetRight}ms, " +
                      $"BaselineL={baselineRTLeft}ms, BaselineR={baselineRTRight}ms, " +
                      $"LatencyL={emsLatencyLeft}ms, LatencyR={emsLatencyRight}ms)");
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
                OffsetLeft = _currentConfig.AgencyOffsetLeft,
                OffsetRight = _currentConfig.AgencyOffsetRight,
                BaselineRTLeft = _currentConfig.BaselineRTLeft,
                BaselineRTRight = _currentConfig.BaselineRTRight,
                EMSLatencyLeft = _currentConfig.EMSLatencyLeft,
                EMSLatencyRight = _currentConfig.EMSLatencyRight
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
                .Where(name => name.StartsWith("session_"))
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
