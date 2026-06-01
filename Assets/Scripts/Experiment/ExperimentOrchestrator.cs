using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using UnityEngine;

namespace ReactionTest.Experiment
{
    /// <summary>
    /// FastestBaseline 実験の司令塔。1セッション＝1条件（EMS or Voluntary、別日カウンターバランス）。
    /// フェーズ: Pre → (EMSLatency: EMS条件のみ) → Training1 → Post1 → 休憩 → Training2 → Post2。
    /// 刺激提示・RT計測・EMS発火はArduino側。Unityはフェーズ進行・Q10算出・EMSタイミング計算・記録。
    /// </summary>
    public class ExperimentOrchestrator : MonoBehaviour
    {
        [Header("References")]
        [SerializeField] private ArduinoLink arduinoLink;
        [SerializeField] private TrialEngine trialEngine;
        [SerializeField] private DataLogger dataLogger;
        [SerializeField] private SubjectDataManager subjectDataManager;
        [SerializeField] private PhaseTransitionUI phaseTransitionUI; // 任意
        [SerializeField] private EMSController emsController;          // 任意

        [Header("Participant")]
        [SerializeField] private string subjectId = "P001";
        [Tooltip("被験者番号（0始まり）。カウンターバランス（条件順序・S-Rマッピング）の割当に使用。")]
        [SerializeField] private int subjectIndex = 0;

        private ExperimentConfig _config;
        private ExperimentCondition _condition;
        private SRMapping _mapping;
        private string _sessionDate;
        private string _sessionPath;
        private float _q10L, _q10R, _e2tL, _e2tR;
        private bool _aborted;

        [Serializable]
        private class SummaryData
        {
            public string SubjectId;
            public string Condition;
            public string SessionDate;
            public float Q10Left, Q10Right, EmsToTouchLeft, EmsToTouchRight;
            public float MedianPre, MedianPost1, MedianPost2, Gain;
        }

        private IEnumerator Start()
        {
            if (!ValidateRefs()) yield break;

            string projectRoot = Directory.GetParent(Application.dataPath).FullName;
            _config = ExperimentConfig.LoadOrCreate(Path.Combine(projectRoot, "experiment_config.json"));

            subjectDataManager.LoadOrCreateSubject(subjectId, subjectIndex);
            _sessionPath = subjectDataManager.CreateSessionFolder();
            _condition = subjectDataManager.ConditionForCurrentSession();
            _mapping = subjectDataManager.CurrentMapping;
            _sessionDate = DateTime.Now.ToString("yyyy-MM-dd");
            int sessionNumber = subjectDataManager.CurrentSessionNumber;

            if (arduinoLink != null)
            {
                arduinoLink.SendThreshold(UserAction.Left, _config.TouchThresholdLeft);
                arduinoLink.SendThreshold(UserAction.Right, _config.TouchThresholdRight);
                arduinoLink.SendEmsConfig(_config.EmsPulseWidthUs, _config.EmsPulseCount,
                    _config.EmsBurstCount, _config.EmsPulseIntervalUs);
            }

            var meta = new SessionMeta
            {
                SubjectId = subjectId,
                Condition = _condition,
                SessionNumber = sessionNumber,
                Mapping = _mapping,
                SessionDate = _sessionDate,
                DatetimeStart = DateTime.UtcNow.ToString("o"),
                AppVersion = Application.version,
                SeedPre = TrialListGenerator.DerivePhaseSeed(subjectId, _sessionPath, PhaseType.Pre),
                SeedEMSLatency = TrialListGenerator.DerivePhaseSeed(subjectId, _sessionPath, PhaseType.EMSLatency),
                SeedTraining1 = TrialListGenerator.DerivePhaseSeed(subjectId, _sessionPath, PhaseType.Training1),
                SeedPost1 = TrialListGenerator.DerivePhaseSeed(subjectId, _sessionPath, PhaseType.Post1),
                SeedTraining2 = TrialListGenerator.DerivePhaseSeed(subjectId, _sessionPath, PhaseType.Training2),
                SeedPost2 = TrialListGenerator.DerivePhaseSeed(subjectId, _sessionPath, PhaseType.Post2)
            };
            dataLogger.InitializeWithPath(meta, _sessionPath);
            Debug.Log($"Session {sessionNumber}: condition={_condition}, mapping={_mapping}, subjectIndex={subjectIndex}");

            // ── Pre（EMSなし）→ Q10(左右別) ──
            var preRTs = new List<float>();
            var preL = new List<float>();
            var preR = new List<float>();
            yield return ShowTransition("Pre", $"赤/緑のLEDが点きます。対応する指でできるだけ速くタッチ。\n{_config.PreTrials} 試行");
            yield return RunBlock(PhaseType.Pre, _config.PreTrials, meta.SeedPre, preRTs, preL, preR);
            if (_aborted) { yield return Finish(true); yield break; }
            _q10L = RtStatistics.Q10(preL);
            _q10R = RtStatistics.Q10(preR);
            Debug.Log($"Q10 Left={_q10L:F1}ms (n={preL.Count}), Right={_q10R:F1}ms (n={preR.Count})");
            if (preL.Count < 5 || preR.Count < 5)
            {
                Debug.LogWarning($"Pre correct-trial count is low (L={preL.Count}, R={preR.Count}). " +
                                 $"Q10 may be unreliable; EMS fire timing for a side with 0 correct trials would clamp to 0.");
            }

            // ── EMSLatency（EMS条件のみ）──
            _e2tL = 0f; _e2tR = 0f;
            if (_condition == ExperimentCondition.EMS)
            {
                yield return RunEMSLatency();
                if (_aborted) { yield return Finish(true); yield break; }
            }

            subjectDataManager.SaveCalibration(new CalibrationData
            {
                Q10Left = _q10L, Q10Right = _q10R, EmsToTouchLeft = _e2tL, EmsToTouchRight = _e2tR
            });

            // ── Training1 → Post1 → 休憩 → Training2 → Post2 ──
            var post1 = new List<float>();
            var post2 = new List<float>();

            yield return ShowTransition("Training 1", BlockInstruction(_config.TrainingTrials));
            yield return RunBlock(PhaseType.Training1, _config.TrainingTrials, meta.SeedTraining1, null, null, null);
            if (_aborted) { yield return Finish(true); yield break; }

            yield return ShowTransition("Post 1", BlockInstruction(_config.PostTrials));
            yield return RunBlock(PhaseType.Post1, _config.PostTrials, meta.SeedPost1, post1, null, null);
            if (_aborted) { yield return Finish(true); yield break; }

            yield return ShowTransition("休憩", "少し休憩してください。\n準備ができたら続行します。");

            yield return ShowTransition("Training 2", BlockInstruction(_config.TrainingTrials));
            yield return RunBlock(PhaseType.Training2, _config.TrainingTrials, meta.SeedTraining2, null, null, null);
            if (_aborted) { yield return Finish(true); yield break; }

            yield return ShowTransition("Post 2", BlockInstruction(_config.PostTrials));
            yield return RunBlock(PhaseType.Post2, _config.PostTrials, meta.SeedPost2, post2, null, null);
            if (_aborted) { yield return Finish(true); yield break; }

            // ── median / gain ──
            float medPre = RtStatistics.Median(preRTs);
            float medPost1 = RtStatistics.Median(post1);
            float medPost2 = RtStatistics.Median(post2);
            float gain = (medPost1 + medPost2) / 2f - medPre;
            WriteSummary(medPre, medPost1, medPost2, gain);

            yield return Finish(false);
        }

        private string BlockInstruction(int trials)
            => $"赤/緑のLEDが点きます。対応する指でできるだけ速くタッチ。\n{trials} 試行";

        private bool ValidateRefs()
        {
            if (trialEngine == null || dataLogger == null || subjectDataManager == null || arduinoLink == null)
            {
                Debug.LogError("ExperimentOrchestrator: assign ArduinoLink, TrialEngine, DataLogger, SubjectDataManager.");
                enabled = false;
                return false;
            }
            return true;
        }

        /// <summary>1ブロック（Pre/Post/Training）を実行。correctRTs等はnull可（収集不要なら）。</summary>
        private IEnumerator RunBlock(PhaseType phase, int trials, int seed,
            List<float> correctRTs, List<float> leftRTs, List<float> rightRTs)
        {
            StimColor[] colors = TrialListGenerator.GenerateBalancedColors(trials, seed);
            for (int i = 1; i <= trials; i++)
            {
                StimColor color = colors[i - 1];
                UserAction correctHand = Counterbalance.CorrectHand(color, _mapping);
                var (emsSide, emsDelayUs, _) = ComputeEms(phase, correctHand);

                float iti = UnityEngine.Random.Range(_config.ItiMinSec, _config.ItiMaxSec);
                yield return new WaitForSeconds(iti);

                TrialRecord rec = null;
                yield return StartCoroutine(trialEngine.RunTrial(
                    phase, i, color, correctHand, emsSide, emsDelayUs, _condition, _sessionDate,
                    r => rec = r));

                rec.SubjectId = subjectId;
                rec.EmsToTouchMs = emsSide == UserAction.Left ? _e2tL
                    : (emsSide == UserAction.Right ? _e2tR : 0f);
                rec.ExclusionFlag = RtStatistics.Classify(
                    rec.ReactionTimeMs, _config.RtAnticipationMs, _config.RtLapseMaxMs, 0f);
                dataLogger.AppendTrial(rec);

                if (rec.IsCorrect && rec.ReactionTimeMs > 0f)
                {
                    correctRTs?.Add(rec.ReactionTimeMs);
                    if (correctHand == UserAction.Left) leftRTs?.Add(rec.ReactionTimeMs);
                    else rightRTs?.Add(rec.ReactionTimeMs);
                }

                if (trialEngine.IsAborted) { _aborted = true; yield break; }
            }
            dataLogger.FlushBuffer();
        }

        /// <summary>Training かつ EMS条件のときのみ発火。emsSide=correctHand, delay=Q10-offset-EMS_to_Touch。</summary>
        private (UserAction emsSide, int emsDelayUs, float fireMs) ComputeEms(PhaseType phase, UserAction correctHand)
        {
            bool isTraining = phase == PhaseType.Training1 || phase == PhaseType.Training2;
            if (!(isTraining && EMSPolicy.ShouldFire(_condition)))
                return (UserAction.None, 0, 0f);

            float q10 = correctHand == UserAction.Left ? _q10L : _q10R;
            float e2t = correctHand == UserAction.Left ? _e2tL : _e2tR;
            float fireMs = EMSPolicy.ComputeFireTimingMs(q10, _config.EmsOffsetMs, e2t);
            if (fireMs < 0f)
            {
                Debug.LogWarning($"Fire timing < 0 ({fireMs:F1}ms) → clamp 0.");
                fireMs = 0f;
            }
            return (correctHand, Mathf.RoundToInt(fireMs * 1000f), fireMs);
        }

        private IEnumerator RunEMSLatency()
        {
            yield return ShowTransition("EMS Latency",
                "オペレータがEMS強度を調整します。\n筋肉が動いたら、その指でタッチしてください。");
            int perSide = Mathf.Max(1, _config.EmsLatencyTrials / 2);
            yield return MeasureLatencySide(UserAction.Left, perSide, v => _e2tL = v);
            if (_aborted) yield break;
            yield return MeasureLatencySide(UserAction.Right, perSide, v => _e2tR = v);
        }

        private IEnumerator MeasureLatencySide(UserAction side, int perSide, Action<float> store)
        {
            bool gotValid = false;
            for (int attempt = 1; attempt <= 3; attempt++)
            {
                var lat = new List<float>();
                for (int i = 1; i <= perSide; i++)
                {
                    float iti = UnityEngine.Random.Range(_config.ItiMinSec, _config.ItiMaxSec);
                    yield return new WaitForSeconds(iti);

                    float v = -1f;
                    yield return StartCoroutine(trialEngine.RunEMSLatencyTrial(side, i, x => v = x));
                    if (v > 0f) lat.Add(v);
                    if (trialEngine.IsAborted) { _aborted = true; yield break; }
                }

                if (lat.Count == 0)
                {
                    Debug.LogWarning($"EMS_to_Touch {side}: no valid samples (attempt {attempt}/3).");
                    continue; // 0msを保存しない（下のガードで中断判定）
                }

                gotValid = true;
                float median = RtStatistics.Median(lat);
                float sd = RtStatistics.SampleStdDev(lat);
                store(median);

                if (sd < _config.EmsToTouchStabilitySdMs)
                {
                    Debug.Log($"EMS_to_Touch {side}: {median:F1}ms (SD={sd:F2}, n={lat.Count}) stable.");
                    yield break;
                }
                Debug.LogWarning($"EMS_to_Touch {side} unstable (SD={sd:F2} >= {_config.EmsToTouchStabilitySdMs}ms, " +
                                 $"attempt {attempt}/3). Re-measuring.");
            }

            if (!gotValid)
            {
                // 有効サンプルが一つも得られない＝EMS_to_Touch=0ms起点で通電する危険を避け、セッションを中断。
                Debug.LogError($"EMS_to_Touch {side}: NO valid latency samples after 3 attempts. Aborting session " +
                               $"to avoid firing EMS off a 0ms latency. Check electrode contact / EMS intensity / touch threshold.");
                _aborted = true;
                yield break;
            }
            Debug.LogWarning($"EMS_to_Touch {side}: stability not reached after 3 attempts. Using last valid median.");
        }

        private IEnumerator ShowTransition(string phaseName, string instruction)
        {
            if (phaseTransitionUI != null)
                yield return phaseTransitionUI.ShowPhaseAndWait(phaseName, instruction);
            else
                Debug.Log($"[Phase] {phaseName}: {instruction}");
        }

        private void WriteSummary(float medPre, float medPost1, float medPost2, float gain)
        {
            var summary = new SummaryData
            {
                SubjectId = subjectId,
                Condition = _condition.ToString(),
                SessionDate = _sessionDate,
                Q10Left = _q10L, Q10Right = _q10R,
                EmsToTouchLeft = _e2tL, EmsToTouchRight = _e2tR,
                MedianPre = medPre, MedianPost1 = medPost1, MedianPost2 = medPost2, Gain = gain
            };
            File.WriteAllText(Path.Combine(_sessionPath, "summary.json"), JsonUtility.ToJson(summary, true));
            Debug.Log($"Summary: medianPre={medPre:F1}, post1={medPost1:F1}, post2={medPost2:F1}, gain={gain:F1}ms");
        }

        private IEnumerator Finish(bool aborted)
        {
            if (arduinoLink != null) arduinoLink.SendReset();
            dataLogger.FlushBuffer();
            if (aborted)
            {
                if (emsController != null) emsController.EmergencyStop();
                yield return ShowTransition("中断", "実験が中断されました。\n記録済みデータは保存されています。");
                Debug.LogError($"Experiment aborted. Logs: {dataLogger.GetOutputDirectory()}");
            }
            else
            {
                yield return ShowTransition("実験終了", "お疲れさまでした。");
                Debug.Log($"Experiment finished. Logs: {dataLogger.GetOutputDirectory()}");
            }
        }
    }
}
