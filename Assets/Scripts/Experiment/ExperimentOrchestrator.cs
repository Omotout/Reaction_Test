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
    /// 刺激提示・RT計測・EMS発火はArduino側。Unityはフェーズ進行・FastestBaseline算出・EMSタイミング計算・記録。
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

        [Header("Debug")]
        [Tooltip("Game View に介入モード・現在の deadline・直近ブロック成功率を表示")]
        [SerializeField] private bool showRuntimeDebugOverlay = true;

        private ExperimentConfig _config;
        private ExperimentCondition _condition;
        private SRMapping _mapping;
        private string _sessionDate;
        private string _sessionPath;
        private float _baselineL, _baselineR, _e2tL, _e2tR;
        private bool _aborted;
        private string _abortReason = string.Empty;

        // Deadline mode 状態（adaptive 更新で書き換わる）
        private float _deadlineLeftMs;
        private float _deadlineRightMs;
        // 直近の Training block 適応情報（debug display 用）
        private float _lastBlockSuccessRate = -1f;
        private PhaseType? _lastBlockPhase;

        [Serializable]
        private class SummaryData
        {
            public string SubjectId;
            public string Condition;
            public string SessionDate;
            public string BaselineMethod;
            public float BaselineParameter;
            public float BaselineLeft, BaselineRight, EmsToTouchLeft, EmsToTouchRight;
            public float MedianPre, MedianPost1, MedianPost2, Gain;
            public string InterventionMode;
            public float FinalDeadlineLeftMs;
            public float FinalDeadlineRightMs;
        }

        private IEnumerator Start()
        {
            if (!ValidateRefs()) yield break;

            string projectRoot = Directory.GetParent(Application.dataPath).FullName;
            _config = ExperimentConfig.LoadOrCreate(Path.Combine(projectRoot, "experiment_config.json"));

            // Deadline mode の初期 deadline を config から取り込む（adaptive 更新で書き換え）
            _deadlineLeftMs = _config.LeftDeadlineMs;
            _deadlineRightMs = _config.RightDeadlineMs;
            if (_config.InterventionMode == InterventionMode.Deadline && _config.TriggerEmsAfterError)
            {
                Debug.LogWarning("TriggerEmsAfterError=true は現行ファームウェアでは未対応のため false として扱います " +
                                 "(Arduino loop は どちらの手でも touch で exit して EMS をキャンセルする)。");
            }

            subjectDataManager.LoadOrCreateSubject(subjectId, subjectIndex);
            _sessionPath = subjectDataManager.CreateSessionFolder();
            _condition = subjectDataManager.ConditionForCurrentSession();
            _mapping = subjectDataManager.CurrentMapping;
            _sessionDate = DateTime.Now.ToString("yyyy-MM-dd");
            int sessionNumber = subjectDataManager.CurrentSessionNumber;

            if (arduinoLink != null)
            {
                yield return SendSetupAndAwaitAcks();
                if (_aborted)
                {
                    // SetupAck で session フォルダだけ作成済み・ロガー未初期化のため、
                    // session_info を最低限残すために dataLogger を空 meta で初期化してから Finish。
                    var failMeta = new SessionMeta
                    {
                        SubjectId = subjectId, Condition = _condition, SessionNumber = sessionNumber,
                        Mapping = _mapping, SessionDate = _sessionDate,
                        DatetimeStart = DateTime.UtcNow.ToString("o"), AppVersion = Application.version
                    };
                    dataLogger.InitializeWithPath(failMeta, _sessionPath);
                    yield return Finish(true, _abortReason);
                    yield break;
                }
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

            // ── Pre（EMSなし）→ FastestBaseline(左右別) ──
            var preRTs = new List<float>();
            var preL = new List<float>();
            var preR = new List<float>();
            yield return ShowTransition("Pre", $"赤/緑のLEDが点きます。対応する指でできるだけ速くタッチ。\n{_config.PreTrials} 試行");
            yield return RunBlock(PhaseType.Pre, _config.PreTrials, meta.SeedPre, preRTs, preL, preR);
            if (_aborted) { yield return Finish(true, _abortReason); yield break; }
            _baselineL = RtStatistics.ComputeBaseline(preL, _config.BaselineMethod, _config.BaselinePercentileN, _config.BaselineSdMultiplier);
            _baselineR = RtStatistics.ComputeBaseline(preR, _config.BaselineMethod, _config.BaselinePercentileN, _config.BaselineSdMultiplier);
            string baselineDesc = _config.BaselineMethod == BaselineMethod.Sd
                ? $"mean−{_config.BaselineSdMultiplier:F2}×SD"
                : $"Q{_config.BaselinePercentileN:F0}";
            Debug.Log($"Baseline({baselineDesc}) Left={_baselineL:F1}ms (n={preL.Count}), Right={_baselineR:F1}ms (n={preR.Count})");
            if (preL.Count < 5 || preR.Count < 5)
            {
                Debug.LogWarning($"Pre correct-trial count is low (L={preL.Count}, R={preR.Count}). " +
                                 $"Baseline may be unreliable; EMS fire timing for a side with 0 correct trials would clamp to 0.");
            }

            // ── EMSLatency（EMS条件のみ）──
            _e2tL = 0f; _e2tR = 0f;
            if (_condition == ExperimentCondition.EMS)
            {
                yield return RunEMSLatency();
                if (_aborted) { yield return Finish(true, _abortReason); yield break; }
            }

            subjectDataManager.SaveCalibration(new CalibrationData
            {
                BaselineMethod = _config.BaselineMethod,
                BaselineParameter = _config.BaselineMethod == BaselineMethod.Sd
                    ? _config.BaselineSdMultiplier : _config.BaselinePercentileN,
                BaselineLeft = _baselineL, BaselineRight = _baselineR,
                EmsToTouchLeft = _e2tL, EmsToTouchRight = _e2tR
            });

            // ── Training1 → Post1 → 休憩 → Training2 → Post2 ──
            var post1 = new List<float>();
            var post2 = new List<float>();

            yield return ShowTransition("Training 1", BlockInstruction(_config.Training1Trials));
            yield return RunBlock(PhaseType.Training1, _config.Training1Trials, meta.SeedTraining1, null, null, null);
            if (_aborted) { yield return Finish(true, _abortReason); yield break; }

            yield return ShowTransition("Post 1", BlockInstruction(_config.Post1Trials));
            yield return RunBlock(PhaseType.Post1, _config.Post1Trials, meta.SeedPost1, post1, null, null);
            if (_aborted) { yield return Finish(true, _abortReason); yield break; }

            yield return ShowTransition("休憩", "少し休憩してください。\n準備ができたら続行します。");

            yield return ShowTransition("Training 2", BlockInstruction(_config.Training2Trials));
            yield return RunBlock(PhaseType.Training2, _config.Training2Trials, meta.SeedTraining2, null, null, null);
            if (_aborted) { yield return Finish(true, _abortReason); yield break; }

            yield return ShowTransition("Post 2", BlockInstruction(_config.Post2Trials));
            yield return RunBlock(PhaseType.Post2, _config.Post2Trials, meta.SeedPost2, post2, null, null);
            if (_aborted) { yield return Finish(true, _abortReason); yield break; }

            // ── median / gain ──
            float medPre = RtStatistics.Median(preRTs);
            float medPost1 = RtStatistics.Median(post1);
            float medPost2 = RtStatistics.Median(post2);
            float gain = (medPost1 + medPost2) / 2f - medPre;
            WriteSummary(medPre, medPost1, medPost2, gain);

            yield return Finish(false, string.Empty);
        }

        private string BlockInstruction(int trials)
            => $"赤/緑のLEDが点きます。対応する指でできるだけ速くタッチ。\n{trials} 試行";

        /// <summary>
        /// THR/EMSCFG を送って OK:THR / OK:EMSCFG をACKとして待つ。
        /// ERR:THR / ERR:EMSCFG を受けたら abort（Arduino 側で値が拒否された＝古い設定で実験が走るのを防ぐ）。
        /// シミュレーションモード（!IsConnected）では待たずに通過する。
        /// </summary>
        private IEnumerator SendSetupAndAwaitAcks()
        {
            int okCount = 0;
            string errLine = null;
            const int expectedOks = 3; // THR L, THR R, EMSCFG

            void OnOk(string line)
            {
                if (line.StartsWith("OK:THR:") || line.StartsWith("OK:EMSCFG:")) okCount++;
            }
            void OnErr(string line)
            {
                if (line.StartsWith("ERR:THR") || line.StartsWith("ERR:EMSCFG"))
                {
                    if (errLine == null) errLine = line;
                }
            }

            arduinoLink.OnOtherLine += OnOk;
            arduinoLink.OnErrorLine += OnErr;
            try
            {
                arduinoLink.SendThreshold(UserAction.Left, _config.TouchThresholdLeft);
                arduinoLink.SendThreshold(UserAction.Right, _config.TouchThresholdRight);
                arduinoLink.SendEmsConfig(_config.EmsPulseWidthUs, _config.EmsPulseCount,
                    _config.EmsBurstCount, _config.EmsPulseIntervalUs);

                if (!arduinoLink.IsConnected) yield break; // シミュレーション時はACKを待たない

                const float timeoutSec = 2.0f;
                float deadline = Time.realtimeSinceStartup + timeoutSec;
                while (errLine == null && okCount < expectedOks && Time.realtimeSinceStartup < deadline)
                    yield return null;

                if (errLine != null)
                {
                    _aborted = true;
                    _abortReason = $"Arduino setup rejected: {errLine}";
                    Debug.LogError($"Setup handshake failed: {errLine}");
                }
                else if (okCount < expectedOks)
                {
                    _aborted = true;
                    _abortReason = $"Arduino setup ACK timeout: {okCount}/{expectedOks} OKs in {timeoutSec}s";
                    Debug.LogError(_abortReason);
                }
                else
                {
                    Debug.Log($"Setup handshake OK ({okCount}/{expectedOks}).");
                }
            }
            finally
            {
                arduinoLink.OnOtherLine -= OnOk;
                arduinoLink.OnErrorLine -= OnErr;
            }
        }

        /// <summary>介入モード・現在 deadline・直近ブロック成功率を画面右上にミニ表示（デバッグ用）。</summary>
        private void OnGUI()
        {
            if (!showRuntimeDebugOverlay || _config == null) return;
            string lastBlock = _lastBlockSuccessRate < 0f
                ? "—"
                : $"{_lastBlockPhase} {_lastBlockSuccessRate:P0}";
            string text = $"Mode: {_config.InterventionMode}\n" +
                          $"Deadline: L={_deadlineLeftMs:F0}ms R={_deadlineRightMs:F0}ms\n" +
                          $"Last block: {lastBlock}";
            if (_aborted) text += $"\nABORTED: {_abortReason}";
            GUI.Label(new Rect(Screen.width - 280, 8, 270, 80), text,
                new GUIStyle(GUI.skin.box) { alignment = TextAnchor.UpperLeft, fontSize = 12 });
        }

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

        /// <summary>1ブロック（Pre/Post/Training）を実行。correctRTs等はnull可（収集不要なら）。
        /// Training & Deadline mode の場合、ブロック終了時に adaptive deadline を更新する。</summary>
        private IEnumerator RunBlock(PhaseType phase, int trials, int seed,
            List<float> correctRTs, List<float> leftRTs, List<float> rightRTs)
        {
            StimColor[] colors = TrialListGenerator.GenerateBalancedColors(trials, seed);
            int blockCorrectBeforeDeadline = 0;
            int blockNonTimeout = 0;
            float deadlineLeftAtBlockStart = _deadlineLeftMs;
            float deadlineRightAtBlockStart = _deadlineRightMs;

            for (int i = 1; i <= trials; i++)
            {
                StimColor color = colors[i - 1];
                UserAction correctHand = Counterbalance.CorrectHand(color, _mapping);
                var emsPlan = ComputeEms(phase, correctHand);

                float iti = UnityEngine.Random.Range(_config.ItiMinSec, _config.ItiMaxSec);
                yield return new WaitForSeconds(iti);

                TrialRecord rec = null;
                yield return StartCoroutine(trialEngine.RunTrial(
                    phase, i, color, correctHand, emsPlan.emsSide, emsPlan.emsDelayUs, _condition, _sessionDate,
                    r => rec = r));

                rec.SubjectId = subjectId;
                rec.EmsToTouchMs = emsPlan.emsSide == UserAction.Left ? _e2tL
                    : (emsPlan.emsSide == UserAction.Right ? _e2tR : 0f);
                rec.ExclusionFlag = RtStatistics.Classify(
                    rec.ReactionTimeMs, _config.RtAnticipationMs, _config.RtLapseMaxMs, 0f);

                // Intervention extension
                rec.InterventionMode = _config.InterventionMode;
                rec.EmsScheduled = emsPlan.emsSide != UserAction.None;
                rec.EmsCanceled = rec.EmsScheduled && !rec.EmsFired;
                rec.DeadlineMs = emsPlan.deadlineMs;          // -1 if Fastest or no-EMS
                bool isTimeout = rec.ExclusionFlag == ExclusionFlag.Timeout;
                rec.ResponseBeforeDeadline = !isTimeout
                    && rec.DeadlineMs > 0f
                    && rec.ReactionTimeMs > 0f
                    && rec.ReactionTimeMs < rec.DeadlineMs;
                rec.TouchAfterEmsMs = (rec.EmsFired && rec.ReactionTimeMs > 0f)
                    ? (rec.ReactionTimeMs - rec.EmsFireTimingMs)
                    : -1f;
                rec.Outcome = TrialOutcomeClassifier.Classify(isTimeout, rec.IsCorrect, rec.EmsFired);

                dataLogger.AppendTrial(rec);

                // Baseline/Post 集計は anticipation(<150ms) / lapse(>1000ms) / timeout を除外。
                if (rec.IsCorrect && rec.ReactionTimeMs > 0f && rec.ExclusionFlag == ExclusionFlag.Normal)
                {
                    correctRTs?.Add(rec.ReactionTimeMs);
                    if (correctHand == UserAction.Left) leftRTs?.Add(rec.ReactionTimeMs);
                    else rightRTs?.Add(rec.ReactionTimeMs);
                }

                // Adaptive deadline 用カウンタ（Training & Deadline mode のみ意味を持つ）
                if (!isTimeout) blockNonTimeout++;
                if (rec.Outcome == TrialOutcome.CorrectBeforeDeadline) blockCorrectBeforeDeadline++;

                if (trialEngine.IsAborted)
                {
                    _aborted = true;
                    _abortReason = !string.IsNullOrEmpty(trialEngine.AbortReason)
                        ? $"{trialEngine.AbortReason} (phase {phase}, trial {i})"
                        : $"Operator abort (Esc) during {phase} trial {i}";
                    yield break;
                }
            }
            dataLogger.FlushBuffer();

            // Block 終了: adaptive deadline 更新（Deadline mode かつ Training かつ EMS条件のみ）
            bool isTraining = phase == PhaseType.Training1 || phase == PhaseType.Training2;
            if (_config.InterventionMode == InterventionMode.Deadline
                && isTraining
                && EMSPolicy.ShouldFire(_condition))
            {
                AdaptDeadlineAfterBlock(phase, blockCorrectBeforeDeadline, blockNonTimeout,
                    deadlineLeftAtBlockStart, deadlineRightAtBlockStart);
            }
        }

        /// <summary>
        /// 介入方式に応じて EMS 予定 (emsSide, emsDelayUs, fireMs[=DeadlineMs]) を決定。
        /// Training かつ EMS 条件のときのみ発火対象。
        ///  - Fastest: fireMs = baseline − offset − emsToTouch（先行発火）
        ///  - Deadline: fireMs = leftDeadlineMs / rightDeadlineMs（deadline 時刻、emsToTouch 補正なし）
        /// 戻り値 deadlineMs は CSV 記録専用（Fastest 時は -1）。
        /// </summary>
        private (UserAction emsSide, int emsDelayUs, float fireMs, float deadlineMs) ComputeEms(
            PhaseType phase, UserAction correctHand)
        {
            bool isTraining = phase == PhaseType.Training1 || phase == PhaseType.Training2;
            if (!(isTraining && EMSPolicy.ShouldFire(_condition)))
                return (UserAction.None, 0, 0f, -1f);

            float fireMs;
            float deadlineMs;
            if (_config.InterventionMode == InterventionMode.Deadline)
            {
                deadlineMs = correctHand == UserAction.Left ? _deadlineLeftMs : _deadlineRightMs;
                fireMs = deadlineMs;
            }
            else
            {
                // Fastest mode: 既存ロジックを維持
                float baseline = correctHand == UserAction.Left ? _baselineL : _baselineR;
                float e2t = correctHand == UserAction.Left ? _e2tL : _e2tR;
                fireMs = EMSPolicy.ComputeFireTimingMs(baseline, _config.EmsOffsetMs, e2t);
                deadlineMs = -1f;
            }
            if (fireMs < 0f)
            {
                Debug.LogWarning($"Fire timing < 0 ({fireMs:F1}ms) → clamp 0.");
                fireMs = 0f;
            }
            return (correctHand, Mathf.RoundToInt(fireMs * 1000f), fireMs, deadlineMs);
        }

        /// <summary>ブロック終了時に成功率を見て deadline を更新（adaptive）。
        /// 純粋ロジックは [[DeadlineAdapter]] に分離し、ここではセッション状態への反映＋ログ記録のみ。
        /// AdaptiveDeadlinePerSide はフックとして残置（現状は左右へ同 delta）。
        /// </summary>
        private void AdaptDeadlineAfterBlock(PhaseType phase, int correctBefore, int totalNonTimeout,
            float deadlineLeftBefore, float deadlineRightBefore)
        {
            float rate = totalNonTimeout > 0 ? correctBefore / (float)totalNonTimeout : 0f;
            _lastBlockSuccessRate = rate;
            _lastBlockPhase = phase;

            var dec = DeadlineAdapter.Adapt(
                _deadlineLeftMs, correctBefore, totalNonTimeout,
                _config.TargetSuccessRateUpper, _config.TargetSuccessRateLower,
                _config.DeadlineStepMs, _config.MinDeadlineMs, _config.MaxDeadlineMs,
                _config.UseAdaptiveDeadline);
            float newLeft = dec.NewDeadlineMs;
            // 同 delta を右にも適用（左右別カウンタは将来拡張）
            float delta = newLeft - _deadlineLeftMs;
            float newRight = Mathf.Clamp(_deadlineRightMs + delta, _config.MinDeadlineMs, _config.MaxDeadlineMs);
            _deadlineLeftMs = newLeft;
            _deadlineRightMs = newRight;

            var ev = new DeadlineAdaptationEvent
            {
                Phase = phase,
                BlockTrials = totalNonTimeout,
                CountCorrectBeforeDeadline = correctBefore,
                CountTotalNonTimeout = totalNonTimeout,
                SuccessRate = rate,
                DeadlineLeftMsBefore = deadlineLeftBefore,
                DeadlineRightMsBefore = deadlineRightBefore,
                DeadlineLeftMsAfter = _deadlineLeftMs,
                DeadlineRightMsAfter = _deadlineRightMs,
                Decision = dec.Action,
                Timestamp = DateTime.UtcNow.ToString("o")
            };
            dataLogger.AppendDeadlineAdaptation(ev);
            Debug.Log($"[Adaptive] {phase}: rate={rate:P0} ({correctBefore}/{totalNonTimeout}), decision={dec.Action}, " +
                      $"deadline L={_deadlineLeftMs:F0}ms R={_deadlineRightMs:F0}ms");
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
                    if (trialEngine.IsAborted)
                    {
                        _aborted = true;
                        _abortReason = !string.IsNullOrEmpty(trialEngine.AbortReason)
                            ? $"{trialEngine.AbortReason} (EMSLatency {side} trial {i}, attempt {attempt})"
                            : $"Operator abort (Esc) during EMSLatency {side} trial {i} (attempt {attempt})";
                        yield break;
                    }
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
                _abortReason = $"EMS_to_Touch {side}: no valid latency samples after 3 attempts";
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
                BaselineMethod = _config.BaselineMethod.ToString(),
                BaselineParameter = _config.BaselineMethod == BaselineMethod.Sd
                    ? _config.BaselineSdMultiplier : _config.BaselinePercentileN,
                BaselineLeft = _baselineL, BaselineRight = _baselineR,
                EmsToTouchLeft = _e2tL, EmsToTouchRight = _e2tR,
                MedianPre = medPre, MedianPost1 = medPost1, MedianPost2 = medPost2, Gain = gain,
                InterventionMode = _config.InterventionMode.ToString(),
                FinalDeadlineLeftMs = _deadlineLeftMs,
                FinalDeadlineRightMs = _deadlineRightMs
            };
            File.WriteAllText(Path.Combine(_sessionPath, "summary.json"), JsonUtility.ToJson(summary, true));
            Debug.Log($"Summary: medianPre={medPre:F1}, post1={medPost1:F1}, post2={medPost2:F1}, gain={gain:F1}ms");
        }

        private IEnumerator Finish(bool aborted, string reason)
        {
            if (arduinoLink != null) arduinoLink.SendReset();
            dataLogger.FlushBuffer();
            dataLogger.FinalizeSession(aborted, reason);
            if (aborted)
            {
                if (emsController != null) emsController.EmergencyStop();
                yield return ShowTransition("中断", "実験が中断されました。\n記録済みデータは保存されています。");
                Debug.LogError($"Experiment aborted: {reason}. Logs: {dataLogger.GetOutputDirectory()}");
            }
            else
            {
                yield return ShowTransition("実験終了", "お疲れさまでした。");
                Debug.Log($"Experiment finished. Logs: {dataLogger.GetOutputDirectory()}");
            }
        }
    }
}
