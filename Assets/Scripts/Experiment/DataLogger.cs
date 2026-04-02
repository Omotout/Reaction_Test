using System;
using System.IO;
using System.Text;
using UnityEngine;

namespace ReactionTest.Experiment
{
    public class DataLogger : MonoBehaviour
    {
        [SerializeField] private string trialFileName = "trial_log.csv";
        [SerializeField] private string agencyFileName = "agency_log.csv";

        private string _outputDir;
        private string _trialPath;
        private string _agencyPath;

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
            _agencyPath = Path.Combine(_outputDir, agencyFileName);

            if (!File.Exists(_trialPath))
            {
                File.WriteAllText(_trialPath,
                    "phase,task,trial_index,stimulus_color,expected_action,actual_action,is_correct,error_type,reaction_time_ms,ems_enabled,ems_offset_ms,timestamp" + Environment.NewLine,
                    Encoding.UTF8);
            }

            if (!File.Exists(_agencyPath))
            {
                File.WriteAllText(_agencyPath,
                    "task,candidate_offset_ms,agency_likert_7,timestamp" + Environment.NewLine,
                    Encoding.UTF8);
            }

            // セッション情報をsession_info.jsonとして保存
            SaveSessionInfo(session);

            Debug.Log($"Log output directory: {_outputDir}");
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

        public void AppendTrial(TrialRecord row)
        {
            string line = string.Join(",",
                row.Phase,
                row.Task,
                row.TrialIndex,
                row.StimulusColor,
                row.ExpectedAction,
                row.ActualAction,
                row.IsCorrect ? 1 : 0,
                row.ErrorType,
                row.ReactionTimeMs.ToString("F3"),
                row.EMSEnabled ? 1 : 0,
                row.EMSOffsetMs.ToString("F3"),
                row.Timestamp);

            File.AppendAllText(_trialPath, line + Environment.NewLine, Encoding.UTF8);
        }

        public void AppendAgency(AgencyRecord row)
        {
            string line = string.Join(",",
                row.Task,
                row.CandidateOffsetMs.ToString("F3"),
                row.AgencyLikert7,
                row.Timestamp);

            File.AppendAllText(_agencyPath, line + Environment.NewLine, Encoding.UTF8);
        }
    }
}
