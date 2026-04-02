using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using UnityEngine;

namespace ReactionTest.Experiment
{
    public class ExperimentOrchestrator : MonoBehaviour
    {
        [Header("References")]
        [SerializeField] private TrialEngine trialEngine;
        [SerializeField] private AgencySurveyUI agencySurveyUI;
        [SerializeField] private DataLogger dataLogger;
        [SerializeField] private SubjectDataManager subjectDataManager;
        [SerializeField] private PhaseTransitionUI phaseTransitionUI;

        [Header("Participant")]
        [SerializeField] private string subjectId = "P001";
        [SerializeField] private GroupType groupType = GroupType.AgencyEMS;

        [Header("Schedule")]
        [SerializeField] private ExperimentRunMode runMode = ExperimentRunMode.Full;

        [Header("Trial Counts")]
        [SerializeField] private int trialsPerTask = 30;
        [SerializeField] private int emsLatencyTrials = 20;

        [Header("Agency Search")]
        [SerializeField] private int offsetStartMs = -200;
        [SerializeField] private int offsetEndMs = 100;
        [SerializeField] private int offsetStepMs = 5;

        private readonly Dictionary<TaskType, float> _agencyOffset = new Dictionary<TaskType, float>();
        private readonly Dictionary<TaskType, float> _baselineRT = new Dictionary<TaskType, float>();
        private readonly Dictionary<TaskType, float> _emsLatency = new Dictionary<TaskType, float>();

        private IEnumerator Start()
        {
            ValidateReferences();

            // 被験者データを読み込みまたは新規作成
            subjectDataManager.LoadOrCreateSubject(subjectId, groupType);

            // セッションフォルダを作成
            string sessionPath = subjectDataManager.CreateSessionFolder(runMode);

            SessionMeta session = new SessionMeta
            {
                SubjectId = subjectId,
                Group = groupType,
                DatetimeStart = DateTime.UtcNow.ToString("o"),
                AppVersion = Application.version
            };

            // DataLoggerを初期化（セッションフォルダを使用）
            dataLogger.InitializeWithPath(session, sessionPath);

            // 既存のキャリブレーションデータがあれば読み込み
            LoadCalibrationDataFromSubject();

            if (runMode == ExperimentRunMode.Full)
            {
                yield return RunBaseline();
                yield return RunEMSLatencyMeasurement();
                yield return RunAgencySearch();
                yield return RunTrainingAndPostTest();
            }
            else if (runMode == ExperimentRunMode.Calibration)
            {
                yield return RunBaseline();
                yield return RunEMSLatencyMeasurement();
                yield return RunAgencySearch();
                
                yield return ShowPhaseTransition("キャリブレーション完了", 
                    "Python解析を実行後、同じSubject IDでValidationを実行してください。");
            }
            else // Validation
            {
                if (!subjectDataManager.HasCalibrationData)
                {
                    Debug.LogError($"No calibration data for {subjectId}. Run Calibration first.");
                    yield break;
                }

                yield return RunTrainingAndPostTest();
            }

            yield return ShowPhaseTransition("実験終了", "お疲れさまでした。");
            Debug.Log("Experiment finished.");
            Debug.Log($"Logs: {dataLogger.GetOutputDirectory()}");
        }

        private void ValidateReferences()
        {
            if (trialEngine == null || agencySurveyUI == null || dataLogger == null || subjectDataManager == null)
            {
                Debug.LogError("ExperimentOrchestrator: assign TrialEngine, AgencySurveyUI, DataLogger, SubjectDataManager.");
                enabled = false;
            }
        }

        private IEnumerator ShowPhaseTransition(string phaseName, string instruction)
        {
            if (phaseTransitionUI != null)
            {
                yield return phaseTransitionUI.ShowPhaseAndWait(phaseName, instruction);
            }
            else
            {
                Debug.Log($"[Phase] {phaseName}: {instruction}");
            }
        }

        private void LoadCalibrationDataFromSubject()
        {
            AgencyOffsetConfig config = subjectDataManager.GetAgencyOffsetConfig();
            if (config == null)
            {
                Debug.Log("No calibration data available for this subject.");
                return;
            }

            // 主体感維持オフセット
            _agencyOffset[TaskType.SRT] = config.SRT;
            _agencyOffset[TaskType.DRT] = config.DRT;
            _agencyOffset[TaskType.CRT] = config.CRT;

            // ベースライン反応時間
            _baselineRT[TaskType.SRT] = config.BaselineRT_SRT;
            _baselineRT[TaskType.DRT] = config.BaselineRT_DRT;
            _baselineRT[TaskType.CRT] = config.BaselineRT_CRT;

            // EMSレイテンシ
            _emsLatency[TaskType.SRT] = config.EMSLatency_SRT;
            _emsLatency[TaskType.DRT] = config.EMSLatency_DRT;
            _emsLatency[TaskType.CRT] = config.EMSLatency_CRT;

            Debug.Log($"Loaded calibration data - SRT: offset={config.SRT}ms, baseline={config.BaselineRT_SRT}ms, latency={config.EMSLatency_SRT}ms");
        }

        /// <summary>
        /// Python解析後にキャリブレーション結果を保存
        /// Inspector上のボタンまたは外部から呼び出し
        /// </summary>
        public void SaveCalibrationFromAnalysis(
            float srtOffset, float drtOffset, float crtOffset,
            float baselineSRT, float baselineDRT, float baselineCRT,
            float latencySRT, float latencyDRT, float latencyCRT)
        {
            subjectDataManager.SaveCalibrationResult(
                srtOffset, drtOffset, crtOffset,
                baselineSRT, baselineDRT, baselineCRT,
                latencySRT, latencyDRT, latencyCRT);
        }

        private IEnumerator RunBaseline()
        {
            yield return ShowPhaseTransition("ベースライン測定", 
                $"EMSなしで反応時間を測定します。\n各タスク {trialsPerTask} 試行 × 3タスク = {trialsPerTask * 3} 試行\n\n緑: 左クリック、赤: 右クリック（タスクによる）");

            foreach (TaskType task in Enum.GetValues(typeof(TaskType)))
            {
                yield return ShowPhaseTransition($"ベースライン - {GetTaskDescription(task)}", 
                    GetTaskInstruction(task));

                for (int i = 1; i <= trialsPerTask; i++)
                {
                    TrialRecord record = null;
                    yield return StartCoroutine(trialEngine.RunSingleTrial(
                        PhaseType.Baseline,
                        task,
                        i,
                        new EMSDecision(false, 0f),
                        r => record = r));

                    dataLogger.AppendTrial(record);
                }
            }
            Debug.Log("Baseline phase completed.");
        }

        private IEnumerator RunEMSLatencyMeasurement()
        {
            yield return ShowPhaseTransition("EMSレイテンシ測定", 
                $"EMS刺激に対する反応遅延を測定します。\n各タスク {emsLatencyTrials} 試行 × 3タスク = {emsLatencyTrials * 3} 試行");

            foreach (TaskType task in Enum.GetValues(typeof(TaskType)))
            {
                yield return ShowPhaseTransition($"EMSレイテンシ - {GetTaskDescription(task)}", 
                    GetTaskInstruction(task));

                for (int i = 1; i <= emsLatencyTrials; i++)
                {
                    TrialRecord record = null;
                    yield return StartCoroutine(trialEngine.RunSingleTrial(
                        PhaseType.EMSLatency,
                        task,
                        i,
                        new EMSDecision(true, 0f),
                        r => record = r));

                    dataLogger.AppendTrial(record);
                }
            }
            Debug.Log("EMS Latency measurement completed.");
        }

        private IEnumerator RunAgencySearch()
        {
            int offsetCount = (offsetEndMs - offsetStartMs) / offsetStepMs + 1;
            yield return ShowPhaseTransition("主体感探索", 
                $"様々なタイミングでEMSを発火し、主体感を評価します。\n各試行後に1〜7で評価してください。\n{offsetCount} オフセット × 3タスク = {offsetCount * 3} 試行");

            foreach (TaskType task in Enum.GetValues(typeof(TaskType)))
            {
                yield return ShowPhaseTransition($"主体感探索 - {GetTaskDescription(task)}", 
                    $"{GetTaskInstruction(task)}\n\n各試行後、主体感を1〜7で評価してください。\n※エラー時は同じオフセットで再試行されます。");

                for (int offset = offsetStartMs; offset <= offsetEndMs; offset += offsetStepMs)
                {
                    // エラー時はリトライ（正しい応答が得られるまで繰り返し）
                    bool validTrial = false;
                    while (!validTrial)
                    {
                        TrialRecord record = null;
                        yield return StartCoroutine(trialEngine.RunSingleTrial(
                            PhaseType.AgencySearch,
                            task,
                            offset,
                            new EMSDecision(true, offset),
                            r => record = r));

                        if (!record.IsCorrect)
                        {
                            // エラー時はリトライ（ログは残すがAgency評価はスキップ）
                            dataLogger.AppendTrial(record);
                            Debug.Log($"AgencySearch: Error at offset {offset}ms, retrying...");
                            yield return new WaitForSeconds(0.5f); // 少し待機
                            continue;
                        }

                        // 正しい応答の場合
                        dataLogger.AppendTrial(record);
                        validTrial = true;

                        int answer = 4;
                        yield return StartCoroutine(agencySurveyUI.AskAgency(a => answer = Mathf.Clamp(a, 1, 7)));

                        dataLogger.AppendAgency(new AgencyRecord
                        {
                            Task = task,
                            CandidateOffsetMs = offset,
                            AgencyLikert7 = answer,
                            Timestamp = DateTime.UtcNow.ToString("o")
                        });
                    }
                }
            }
            Debug.Log("Agency Search phase completed.");
        }

        private IEnumerator RunTrainingAndPostTest()
        {
            yield return ShowPhaseTransition("トレーニング & ポストテスト", 
                $"キャリブレーションで決定したタイミングでEMSを発火します。\n各タスク {trialsPerTask} 試行 × 3タスク × 2フェーズ = {trialsPerTask * 6} 試行");

            foreach (TaskType task in Enum.GetValues(typeof(TaskType)))
            {
                yield return ShowPhaseTransition($"トレーニング - {GetTaskDescription(task)}", 
                    GetTaskInstruction(task));

                for (int i = 1; i <= trialsPerTask; i++)
                {
                    TrialRecord training = null;
                    EMSDecision decision = EMSPolicy.ComputeDecision(
                        groupType,
                        task,
                        GetBaselineRT(task),
                        GetAgencyOffset(task),
                        GetEMSLatency(task));

                    yield return StartCoroutine(trialEngine.RunSingleTrial(
                        PhaseType.Training,
                        task,
                        i,
                        decision,
                        r => training = r));

                    dataLogger.AppendTrial(training);
                }

                yield return ShowPhaseTransition($"ポストテスト - {GetTaskDescription(task)}", 
                    $"EMSなしで反応時間を測定します。\n{GetTaskInstruction(task)}");

                for (int i = 1; i <= trialsPerTask; i++)
                {
                    TrialRecord postTest = null;
                    yield return StartCoroutine(trialEngine.RunSingleTrial(
                        PhaseType.PostTest,
                        task,
                        i,
                        new EMSDecision(false, 0f),
                        r => postTest = r));

                    dataLogger.AppendTrial(postTest);
                }
            }
            Debug.Log("Training and PostTest completed.");
        }

        private string GetTaskDescription(TaskType task)
        {
            return task switch
            {
                TaskType.SRT => "単純反応課題 (SRT)",
                TaskType.DRT => "弁別反応課題 (DRT)",
                TaskType.CRT => "選択反応課題 (CRT)",
                _ => task.ToString()
            };
        }

        private string GetTaskInstruction(TaskType task)
        {
            return task switch
            {
                TaskType.SRT => "刺激が表示されたら、できるだけ速く左クリックしてください。",
                TaskType.DRT => "緑の刺激には左クリック、赤の刺激には反応しないでください。",
                TaskType.CRT => "緑の刺激には左クリック、赤の刺激には右クリックしてください。",
                _ => ""
            };
        }

        private float GetBaselineRT(TaskType task)
        {
            if (_baselineRT.TryGetValue(task, out float value))
            {
                return value;
            }
            return 300f;
        }

        private float GetEMSLatency(TaskType task)
        {
            if (_emsLatency.TryGetValue(task, out float value))
            {
                return value;
            }
            return 50f;
        }

        private float GetAgencyOffset(TaskType task)
        {
            if (_agencyOffset.TryGetValue(task, out float value))
            {
                return value;
            }
            return 0f;
        }
    }
}
