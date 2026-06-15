using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEngine;

namespace ReactionTest.Experiment
{
    [Serializable]
    public class SubjectConfig
    {
        public string SubjectId;
        public int SubjectIndex;
        public ConditionOrder Order;
        public SRMapping Mapping;
        public int LatestSessionNumber;
        public string LastUpdated;
    }

    public class SubjectDataManager : MonoBehaviour
    {
        [SerializeField] private string dataFolderName = "ExperimentData";

        [Header("Manual Session Override")]
        [Tooltip("ON: use the session number and condition below instead of the saved counterbalance session.")]
        [SerializeField] private bool useManualSessionSettings = false;
        [SerializeField, Range(1, 2)] private int manualSessionNumber = 1;
        [SerializeField] private ExperimentCondition manualCondition = ExperimentCondition.EMS;

        private string _rootPath;
        private SubjectConfig _currentConfig;
        private string _currentSessionPath;
        private int _currentSessionNumber;
        private ExperimentCondition _currentCondition;

        public SubjectConfig CurrentConfig => _currentConfig;
        public string CurrentSessionPath => _currentSessionPath;
        public string RootPath => _rootPath;
        public int CurrentSessionNumber => _currentSessionNumber;
        public SRMapping CurrentMapping => _currentConfig != null ? _currentConfig.Mapping : SRMapping.RedRight;

        private void Awake()
        {
            string projectRoot = Directory.GetParent(Application.dataPath).FullName;
            _rootPath = Path.Combine(projectRoot, dataFolderName);
            Debug.Log($"SubjectDataManager: Data root = {_rootPath}");
        }

        public SubjectConfig LoadOrCreateSubject(string subjectId, int subjectIndex)
        {
            string subjectPath = Path.Combine(_rootPath, subjectId);
            string configPath = Path.Combine(subjectPath, "config.json");

            if (File.Exists(configPath))
            {
                _currentConfig = JsonUtility.FromJson<SubjectConfig>(File.ReadAllText(configPath));
                if (_currentConfig.SubjectIndex != subjectIndex)
                {
                    Debug.LogError($"SubjectIndex mismatch for {subjectId}: saved={_currentConfig.SubjectIndex}, " +
                                   $"inspector={subjectIndex}. Using SAVED to preserve counterbalance integrity.");
                }
                Debug.Log($"Loaded subject {subjectId}: index={_currentConfig.SubjectIndex}, " +
                          $"order={_currentConfig.Order}, mapping={_currentConfig.Mapping}, " +
                          $"latestSession={_currentConfig.LatestSessionNumber}");
            }
            else
            {
                Directory.CreateDirectory(subjectPath);
                _currentConfig = new SubjectConfig
                {
                    SubjectId = subjectId,
                    SubjectIndex = subjectIndex,
                    Order = Counterbalance.OrderFor(subjectIndex),
                    Mapping = Counterbalance.MappingFor(subjectIndex),
                    LatestSessionNumber = 0,
                    LastUpdated = DateTime.Now.ToString("o")
                };
                SaveConfig();
                Debug.Log($"Created subject {subjectId}: index={subjectIndex}, " +
                          $"order={_currentConfig.Order}, mapping={_currentConfig.Mapping}");
            }
            return _currentConfig;
        }

        public string CreateSessionFolder()
        {
            if (_currentConfig == null) { Debug.LogError("Subject not loaded."); return null; }
            string subjectPath = Path.Combine(_rootPath, _currentConfig.SubjectId);
            if (useManualSessionSettings)
            {
                _currentSessionNumber = Mathf.Clamp(manualSessionNumber, 1, 2);
                _currentCondition = manualCondition;
                Debug.LogWarning($"Manual session settings active: session={_currentSessionNumber}, condition={_currentCondition}. " +
                                 "Saved counterbalance session count will not be advanced.");
            }
            else
            {
                _currentConfig.LatestSessionNumber++;
                _currentSessionNumber = _currentConfig.LatestSessionNumber;
                SaveConfig();
                if (_currentSessionNumber <= 2)
                    _currentCondition = Counterbalance.ConditionForSession(_currentConfig.Order, _currentSessionNumber);
            }

            string folder = $"session_{_currentSessionNumber:D2}_{DateTime.Now:yyyyMMdd_HHmmss}";
            _currentSessionPath = Path.Combine(subjectPath, folder);
            Directory.CreateDirectory(_currentSessionPath);
            Debug.Log($"Created session folder: {_currentSessionPath}");
            return _currentSessionPath;
        }

        public ExperimentCondition ConditionForCurrentSession()
        {
            if (useManualSessionSettings)
                return _currentCondition;

            int sessionNumber = _currentSessionNumber;

            if (sessionNumber > 2)
            {
                Debug.LogError($"Subject {_currentConfig.SubjectId} already has {sessionNumber - 1} completed/created sessions. " +
                               "This experiment supports only session 1 and 2 for counterbalancing. " +
                               "Use a new subject ID such as Test1/Test2 for pilot runs.");
            }

            return Counterbalance.ConditionForSession(_currentConfig.Order, sessionNumber);
        }

        public void SaveCalibration(CalibrationData data)
        {
            if (_currentSessionPath == null) return;
            File.WriteAllText(Path.Combine(_currentSessionPath, "calibration.json"),
                JsonUtility.ToJson(data, true));
        }

        public CalibrationData LoadCalibration()
        {
            if (_currentSessionPath == null) return null;
            string p = Path.Combine(_currentSessionPath, "calibration.json");
            return File.Exists(p) ? JsonUtility.FromJson<CalibrationData>(File.ReadAllText(p)) : null;
        }

        public List<string> GetAllSubjectIds()
        {
            if (!Directory.Exists(_rootPath)) return new List<string>();
            return Directory.GetDirectories(_rootPath).Select(Path.GetFileName)
                .Where(n => !n.StartsWith(".")).OrderBy(n => n).ToList();
        }

        private void SaveConfig()
        {
            if (_currentConfig == null) return;
            string configPath = Path.Combine(_rootPath, _currentConfig.SubjectId, "config.json");
            File.WriteAllText(configPath, JsonUtility.ToJson(_currentConfig, true));
        }
    }
}
