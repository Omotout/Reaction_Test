using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;

namespace ReactionTest.Experiment
{
    // ========================================================================
    // V3.1: CRT特化 6フェーズシーケンス
    //
    // フロー:
    //   1. Practice     — EMSなし、習熟（10〜20試行）
    //   2. Baseline     — EMSなし、HDDMベースライン（30〜50試行）
    //   3. EMSLatency   — 視覚刺激なし、EMS→キー押下レイテンシ測定（左右各15〜20試行）
    //   4. Calibration  — EMSあり、適応的階段法でAgency閾値探索（最大80試行）
    //   5. Training     — 介入あり（群別）（30〜50試行）
    //   6. PostTest     — EMSなし、HDDM事後測定（30〜50試行）
    //
    // V3.1 変更点:
    //   - Baseline RT / EMSLatency: IQR外れ値排除 → 平均
    //   - Calibration: 最大試行数80のガード
    //   - Escキーによる緊急停止（EMS即時無効化 + データFlush）
    //   - 全フェーズで試行後にabortチェック
    // ========================================================================

    public class ExperimentOrchestrator : MonoBehaviour
    {
        [Header("References")]
        [SerializeField] private TrialEngine trialEngine;
        [SerializeField] private AgencySurveyUI agencySurveyUI;
        [SerializeField] private DataLogger dataLogger;
        [SerializeField] private SubjectDataManager subjectDataManager;
        [SerializeField] private PhaseTransitionUI phaseTransitionUI;
        [SerializeField] private EMSController emsController;

        [Header("Participant")]
        [SerializeField] private string subjectId = "P001";
        [SerializeField] private GroupType groupType = GroupType.AgencyEMS;

        [Header("Calibration Safety")]
        [Tooltip("Calibrationフェーズの最大試行数（無限ループ防止）")]
        [SerializeField] private int maxCalibrationTrials = 80;

        // ============================================================
        // ランタイム保持: EMSLatencyフェーズで測定したレイテンシ
        // ============================================================
        private float _emsLatencyLeft = 50f;   // デフォルト値（フォールバック用）
        private float _emsLatencyRight = 50f;
        private float _baselineRTLeft = 300f;  // Baselineフェーズで左右別に算出
        private float _baselineRTRight = 300f;

        // Calibration結果: 左右別のAgencyオフセット
        private float _agencyOffsetLeft = 0f;
        private float _agencyOffsetRight = 0f;

        // 緊急停止フラグ
        private bool _experimentAborted = false;

        private IEnumerator Start()
        {
            ValidateReferences();

            // 被験者データを読み込みまたは新規作成
            // 既存被験者の場合、保存済みGroupが優先される（Inspector値との不一致はSubjectDataManager側でエラーログ）
            groupType = subjectDataManager.LoadOrCreateSubject(subjectId, groupType);

            // セッションフォルダを作成
            string sessionPath = subjectDataManager.CreateSessionFolder();

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

            // === 6フェーズ シーケンシャル実行 ===
            yield return RunPractice();
            if (_experimentAborted) { yield return HandleAbort(); yield break; }

            yield return RunBaseline();
            if (_experimentAborted) { yield return HandleAbort(); yield break; }

            yield return RunEMSLatency();
            if (_experimentAborted) { yield return HandleAbort(); yield break; }

            yield return RunCalibration();
            if (_experimentAborted) { yield return HandleAbort(); yield break; }

            yield return RunTraining();
            if (_experimentAborted) { yield return HandleAbort(); yield break; }

            yield return RunPostTest();
            if (_experimentAborted) { yield return HandleAbort(); yield break; }

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

        // ============================================================
        // 緊急停止処理
        // ============================================================

        /// <summary>
        /// 試行後にabort状態をチェック → trueなら呼び出し元でyield breakすること
        /// </summary>
        private void CheckAbortState()
        {
            if (trialEngine.IsAborted && !_experimentAborted)
            {
                _experimentAborted = true;
                if (emsController != null) emsController.EmergencyStop();
                dataLogger.FlushBuffer();
                Debug.LogError("EXPERIMENT ABORTED by user (Escape key).");
            }
        }

        private IEnumerator HandleAbort()
        {
            dataLogger.FlushBuffer();
            yield return ShowPhaseTransition("実験中断",
                "Escapeキーにより実験が中断されました。\n" +
                "記録済みデータは保存されています。");
            Debug.LogError($"Experiment aborted. Logs: {dataLogger.GetOutputDirectory()}");
        }

        // ============================================================
        // IQR外れ値排除 → 平均
        // ============================================================

        /// <summary>
        /// 四分位範囲法（IQR）で外れ値を除外した後、平均を返す。
        /// データが4件未満の場合はIQRが安定しないため単純平均を使用。
        /// </summary>
        private float ComputeIQRFilteredMean(List<float> values)
        {
            if (values.Count == 0) return 0f;
            if (values.Count < 4) return values.Average();

            var sorted = values.OrderBy(v => v).ToList();
            int n = sorted.Count;

            // Q1, Q3 を線形補間で算出
            float q1 = Percentile(sorted, 0.25f);
            float q3 = Percentile(sorted, 0.75f);
            float iqr = q3 - q1;

            float lower = q1 - 1.5f * iqr;
            float upper = q3 + 1.5f * iqr;

            var filtered = sorted.Where(v => v >= lower && v <= upper).ToList();

            if (filtered.Count == 0)
            {
                Debug.LogWarning("IQR filter removed all data. Falling back to median.");
                return sorted[n / 2];
            }

            int removed = n - filtered.Count;
            if (removed > 0)
            {
                Debug.Log($"IQR filter: {removed}/{n} outliers removed " +
                          $"(range: {lower:F1}–{upper:F1}ms, Q1={q1:F1}, Q3={q3:F1})");
            }

            return filtered.Average();
        }

        /// <summary>
        /// ソート済みリストからパーセンタイルを線形補間で算出
        /// </summary>
        private float Percentile(List<float> sorted, float percentile)
        {
            float index = percentile * (sorted.Count - 1);
            int lower = (int)Math.Floor(index);
            int upper = (int)Math.Ceiling(index);
            if (lower == upper) return sorted[lower];
            float frac = index - lower;
            return sorted[lower] * (1f - frac) + sorted[upper] * frac;
        }

        // ============================================================
        // データ読み込み
        // ============================================================

        private void LoadCalibrationDataFromSubject()
        {
            AgencyOffsetConfig config = subjectDataManager.GetAgencyOffsetConfig();
            if (config == null)
            {
                Debug.Log("No calibration data available for this subject.");
                return;
            }

            _agencyOffsetLeft = config.OffsetLeft;
            _agencyOffsetRight = config.OffsetRight;
            _baselineRTLeft = config.BaselineRTLeft;
            _baselineRTRight = config.BaselineRTRight;
            _emsLatencyLeft = config.EMSLatencyLeft;
            _emsLatencyRight = config.EMSLatencyRight;

            Debug.Log($"Loaded calibration: OffsetL={config.OffsetLeft}ms, OffsetR={config.OffsetRight}ms, " +
                      $"BaselineL={config.BaselineRTLeft}ms, BaselineR={config.BaselineRTRight}ms, " +
                      $"LatencyL={config.EMSLatencyLeft}ms, LatencyR={config.EMSLatencyRight}ms");
        }

        // ============================================================
        // Phase 1: Practice（習熟）
        // ============================================================

        private IEnumerator RunPractice()
        {
            int trials = trialEngine.PracticeTrials;
            yield return ShowPhaseTransition("プラクティス",
                $"練習セッションです。EMSなしでタスクに慣れてください。\n" +
                $"緑 → 左クリック、赤 → 右クリック\n{trials} 試行");

            for (int i = 1; i <= trials; i++)
            {
                TrialRecord record = null;
                yield return StartCoroutine(trialEngine.RunSingleTrial(
                    PhaseType.Practice,
                    i,
                    new EMSDecision(false, 0f, 0f),
                    (r, _) => { record = r; FillSubjectInfo(record); }));

                dataLogger.AppendTrial(record);

                CheckAbortState();
                if (_experimentAborted) yield break;
            }

            dataLogger.FlushBuffer();
            Debug.Log("Practice phase completed.");
        }

        // ============================================================
        // Phase 2: Baseline（HDDMベースライン）
        // ============================================================

        private IEnumerator RunBaseline()
        {
            int trials = trialEngine.BaselineTrials;
            yield return ShowPhaseTransition("ベースライン測定",
                $"EMSなしで反応時間を測定します。\n" +
                $"緑 → 左クリック、赤 → 右クリック\n{trials} 試行");

            List<float> correctRTsLeft = new List<float>();
            List<float> correctRTsRight = new List<float>();

            for (int i = 1; i <= trials; i++)
            {
                TrialRecord record = null;
                yield return StartCoroutine(trialEngine.RunSingleTrial(
                    PhaseType.Baseline,
                    i,
                    new EMSDecision(false, 0f, 0f),
                    (r, _) => { record = r; FillSubjectInfo(record); }));

                dataLogger.AppendTrial(record);

                // 正解試行のRTを左右別に収集（ベースラインRT算出用）
                if (record.IsCorrect && record.ReactionTimeMs > 0)
                {
                    if (record.TargetSide == UserAction.Left)
                        correctRTsLeft.Add(record.ReactionTimeMs);
                    else if (record.TargetSide == UserAction.Right)
                        correctRTsRight.Add(record.ReactionTimeMs);
                }

                CheckAbortState();
                if (_experimentAborted) yield break;
            }

            // ベースラインRT: IQR外れ値排除 → 平均（左右別）
            if (correctRTsLeft.Count > 0)
            {
                _baselineRTLeft = ComputeIQRFilteredMean(correctRTsLeft);
                Debug.Log($"Baseline RT Left (IQR-filtered mean): {_baselineRTLeft:F1}ms (from {correctRTsLeft.Count} correct trials)");
            }
            else
            {
                Debug.LogWarning("No correct LEFT trials in Baseline. Using default RT.");
            }

            if (correctRTsRight.Count > 0)
            {
                _baselineRTRight = ComputeIQRFilteredMean(correctRTsRight);
                Debug.Log($"Baseline RT Right (IQR-filtered mean): {_baselineRTRight:F1}ms (from {correctRTsRight.Count} correct trials)");
            }
            else
            {
                Debug.LogWarning("No correct RIGHT trials in Baseline. Using default RT.");
            }

            dataLogger.FlushBuffer();
            Debug.Log("Baseline phase completed.");
        }

        // ============================================================
        // Phase 3: EMSLatency（通電→キー押下のレイテンシ測定）
        // ============================================================

        private IEnumerator RunEMSLatency()
        {
            int trialsPerSide = trialEngine.EMSLatencyTrialsPerSide;
            yield return ShowPhaseTransition("EMSレイテンシ測定",
                $"画面に刺激は表示されません。\n" +
                $"EMSで筋肉が動いたら、該当する側のボタンを押してください。\n" +
                $"左右各 {trialsPerSide} 試行 = 計 {trialsPerSide * 2} 試行");

            List<float> leftLatencies = new List<float>();
            List<float> rightLatencies = new List<float>();

            // 左チャンネル
            yield return ShowPhaseTransition("EMSレイテンシ - 左手",
                "左手のEMS刺激です。\n筋肉が動いたら左クリックしてください。");

            for (int i = 1; i <= trialsPerSide; i++)
            {
                TrialRecord record = null;
                yield return StartCoroutine(trialEngine.RunEMSLatencyTrial(
                    UserAction.Left, i,
                    r => { record = r; FillSubjectInfo(record); }));

                dataLogger.AppendTrial(record);

                if (record.ReactionTimeMs > 0)
                {
                    leftLatencies.Add(record.ReactionTimeMs);
                }

                CheckAbortState();
                if (_experimentAborted) yield break;
            }

            // 右チャンネル
            yield return ShowPhaseTransition("EMSレイテンシ - 右手",
                "右手のEMS刺激です。\n筋肉が動いたら右クリックしてください。");

            for (int i = 1; i <= trialsPerSide; i++)
            {
                TrialRecord record = null;
                yield return StartCoroutine(trialEngine.RunEMSLatencyTrial(
                    UserAction.Right, i,
                    r => { record = r; FillSubjectInfo(record); }));

                dataLogger.AppendTrial(record);

                if (record.ReactionTimeMs > 0)
                {
                    rightLatencies.Add(record.ReactionTimeMs);
                }

                CheckAbortState();
                if (_experimentAborted) yield break;
            }

            // IQR外れ値排除 → 平均でレイテンシを算出
            if (leftLatencies.Count > 0)
            {
                _emsLatencyLeft = ComputeIQRFilteredMean(leftLatencies);
                Debug.Log($"EMS Latency Left (IQR-filtered mean): {_emsLatencyLeft:F1}ms (from {leftLatencies.Count} trials)");
            }
            else
            {
                Debug.LogWarning("No valid left latency data. Using default.");
            }

            if (rightLatencies.Count > 0)
            {
                _emsLatencyRight = ComputeIQRFilteredMean(rightLatencies);
                Debug.Log($"EMS Latency Right (IQR-filtered mean): {_emsLatencyRight:F1}ms (from {rightLatencies.Count} trials)");
            }
            else
            {
                Debug.LogWarning("No valid right latency data. Using default.");
            }

            dataLogger.FlushBuffer();
            Debug.Log($"EMSLatency phase completed. Left={_emsLatencyLeft:F1}ms, Right={_emsLatencyRight:F1}ms");
        }

        // ============================================================
        // Phase 4: Calibration（適応的インターリーブ階段法）
        // ============================================================
        //
        // アルゴリズム:
        //   - 左右独立の階段: currentOffset_L, currentOffset_R
        //   - 毎試行 staircase.PickSide() でターゲット側決定
        //     （両側未収束なら50/50ランダム、片側収束後は未収束側を確定選択）
        //   - 該当する側の BaselineRT・currentOffset・EMSLatency でEMS発火
        //   - Agency回答が前回から反転 → reversals++
        //   - Yes → offset をマイナス方向（難しく）
        //   - No  → offset をプラス方向（簡単に）
        //   - 適応的ステップ: 反転0-1→10ms, 2-3→5ms, 4+→3ms
        //   - エラー試行: Agency回答無効、更新しない
        //   - 終了条件: 左右両方とも5回反転 OR 最大試行数到達
        //   - 最終値: 反転時のオフセット平均 → Training で使用
        // ============================================================

        private IEnumerator RunCalibration()
        {
            var staircase = new StaircaseCalibrator();

            yield return ShowPhaseTransition("Agency キャリブレーション（階段法）",
                "様々なタイミングでEMSを発火し、主体感を評価します。\n" +
                "各試行後に1〜7で評価してください。\n" +
                "左右ランダムに提示されます。\n" +
                $"左右それぞれ {StaircaseCalibrator.TARGET_REVERSALS} 回反転で収束します。");

            int trialIndex = 0;

            while (!staircase.IsConverged && trialIndex < maxCalibrationTrials)
            {
                trialIndex++;

                // ── 1. ターゲット側を決定（未収束側があれば優先、なければ50/50ランダム）──
                UserAction side = staircase.PickSide();

                bool isCatchTrial = staircase.IsCatchTrial(side);

                // ── 2. 該当する側のBaselineRT・オフセット・レイテンシでEMSタイミングを計算 ──
                float offset = staircase.GetCurrentOffset(side);
                float sideBaselineRT = GetBaselineRT(side);
                float sideLatency = GetEMSLatency(side);
                EMSDecision emsDecision = EMSPolicy.ComputeCalibrationDecision(
                    sideBaselineRT, offset, sideLatency);

                // ── 3. 試行実行（ターゲット側を強制指定 → EMS発火チャンネルと一致） ──
                // EMSOffsetMs / EMSFireTimingMs は TrialEngine 側で emsDecision から設定済み
                TrialRecord record = null;
                yield return StartCoroutine(trialEngine.RunSingleTrial(
                    PhaseType.Calibration,
                    trialIndex,
                    emsDecision,
                    (r, _) =>
                    {
                        record = r;
                        FillSubjectInfo(record);
                    },
                    forcedTargetSide: side));

                // ── 4. Agency回答（UIは常に表示） ──
                bool agencyAnswer = false;
                yield return StartCoroutine(agencySurveyUI.AskAgency(a => agencyAnswer = a));

                record.AgencyYes = agencyAnswer;
                dataLogger.AppendTrial(record);

                // ── 5. 階段更新 ──
                if (!isCatchTrial)
                {
                    staircase.Update(side, agencyAnswer, record.IsCorrect);
                }

                Debug.Log($"Calibration #{trialIndex}: side={side}, offset={offset:F1}ms, " +
                          $"agency={agencyAnswer}, correct={record.IsCorrect}, " +
                          $"reversals L={staircase.GetReversals(UserAction.Left)}/{StaircaseCalibrator.TARGET_REVERSALS}, " +
                          $"R={staircase.GetReversals(UserAction.Right)}/{StaircaseCalibrator.TARGET_REVERSALS}" +
                          $"{(isCatchTrial ? " [CATCH]" : "")}" +
                          $"{(!record.IsCorrect ? " [ERROR→SKIP]" : "")}");

                CheckAbortState();
                if (_experimentAborted) yield break;
            }

            // 最大試行数に到達した場合の警告
            if (!staircase.IsConverged)
            {
                Debug.LogWarning($"Calibration did NOT converge within {maxCalibrationTrials} trials. " +
                                 $"Using best available estimates. " +
                                 $"Reversals: L={staircase.GetReversals(UserAction.Left)}, " +
                                 $"R={staircase.GetReversals(UserAction.Right)}");
            }

            // ── 最終オフセット確定 ──
            _agencyOffsetLeft = staircase.GetFinalOffset(UserAction.Left);
            _agencyOffsetRight = staircase.GetFinalOffset(UserAction.Right);

            // キャリブレーション結果を保存
            subjectDataManager.SaveCalibrationResult(
                _agencyOffsetLeft, _agencyOffsetRight,
                _baselineRTLeft, _baselineRTRight,
                _emsLatencyLeft, _emsLatencyRight);

            dataLogger.FlushBuffer();

            string convergenceInfo = staircase.IsConverged
                ? $"（{trialIndex} 試行で収束）"
                : $"（{trialIndex} 試行で打ち切り — 未収束）";

            Debug.Log($"Calibration completed: FinalOffset L={_agencyOffsetLeft:F1}ms, R={_agencyOffsetRight:F1}ms {convergenceInfo}");

            yield return ShowPhaseTransition("キャリブレーション完了",
                $"Agency限界オフセットが確定しました。\n" +
                $"左手: {_agencyOffsetLeft:F1}ms\n" +
                $"右手: {_agencyOffsetRight:F1}ms\n" +
                convergenceInfo);
        }

        // ============================================================
        // Phase 5: Training（介入）
        // ============================================================
        //
        // forcedTargetSide を活用: ターゲット側を事前にランダム決定し、
        // 対応する左右別のAgencyオフセットとEMSレイテンシを使って
        // EMS発火タイミングを正確に計算する。
        // ============================================================

        private IEnumerator RunTraining()
        {
            int trials = trialEngine.TrainingTrials;
            string groupInfo = groupType == GroupType.AgencyEMS
                ? $"EMSあり（オフセット: 左={_agencyOffsetLeft:F1}ms, 右={_agencyOffsetRight:F1}ms）"
                : "EMSなし（対照群）";

            yield return ShowPhaseTransition("トレーニング",
                $"介入フェーズです。\n{groupInfo}\n" +
                $"緑 → 左クリック、赤 → 右クリック\n{trials} 試行");

            for (int i = 1; i <= trials; i++)
            {
                // ターゲット側を事前にランダム決定
                UserAction targetSide = TaskRule.PickTargetSide();

                // 左右別のBaselineRT・オフセット・レイテンシで正確なEMS発火タイミングを計算
                EMSDecision decision = EMSPolicy.ComputeDecision(
                    groupType,
                    targetSide,
                    GetBaselineRT(targetSide),
                    GetAgencyOffset(targetSide),
                    GetEMSLatency(targetSide));

                TrialRecord record = null;
                yield return StartCoroutine(trialEngine.RunSingleTrial(
                    PhaseType.Training,
                    i,
                    decision,
                    (r, _) =>
                    {
                        record = r;
                        FillSubjectInfo(record);
                    },
                    forcedTargetSide: targetSide));

                dataLogger.AppendTrial(record);

                CheckAbortState();
                if (_experimentAborted) yield break;
            }

            dataLogger.FlushBuffer();
            Debug.Log("Training phase completed.");
        }

        // ============================================================
        // Phase 6: PostTest（HDDM事後測定）
        // ============================================================

        private IEnumerator RunPostTest()
        {
            int trials = trialEngine.PostTestTrials;
            yield return ShowPhaseTransition("ポストテスト",
                $"EMSなしで反応時間を測定します。\n" +
                $"緑 → 左クリック、赤 → 右クリック\n{trials} 試行");

            for (int i = 1; i <= trials; i++)
            {
                TrialRecord record = null;
                yield return StartCoroutine(trialEngine.RunSingleTrial(
                    PhaseType.PostTest,
                    i,
                    new EMSDecision(false, 0f, 0f),
                    (r, _) => { record = r; FillSubjectInfo(record); }));

                dataLogger.AppendTrial(record);

                CheckAbortState();
                if (_experimentAborted) yield break;
            }

            dataLogger.FlushBuffer();
            Debug.Log("PostTest phase completed.");
        }

        // ============================================================
        // Helpers
        // ============================================================

        /// <summary>
        /// TrialRecordにSubjectId/Groupを埋める共通処理
        /// （TrialEngineはSubjectIdを知らないため、Orchestrator側で補完）
        /// </summary>
        private void FillSubjectInfo(TrialRecord record)
        {
            record.SubjectId = subjectId;
            record.Group = groupType;
        }

        /// <summary>
        /// 左右それぞれのEMSレイテンシを取得
        /// </summary>
        private float GetEMSLatency(UserAction side)
        {
            return side == UserAction.Left ? _emsLatencyLeft : _emsLatencyRight;
        }

        /// <summary>
        /// 左右それぞれのAgencyオフセットを取得
        /// </summary>
        private float GetAgencyOffset(UserAction side)
        {
            return side == UserAction.Left ? _agencyOffsetLeft : _agencyOffsetRight;
        }

        /// <summary>
        /// 左右それぞれのベースライン反応時間を取得
        /// </summary>
        private float GetBaselineRT(UserAction side)
        {
            return side == UserAction.Left ? _baselineRTLeft : _baselineRTRight;
        }
    }
}
