# FastestBaseline 移行 Phase C+D 実装計画（試行実行・フェーズ進行・データ記録）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** EMS反応時間実験を、旧Agency枠組み（画面刺激＋マウス入力＋6フェーズ階段法）から、FastestBaseline枠組み（Arduino主導のLED刺激＋静電容量タッチ＋Pre/EMSLatency/Train×2/Post×2）へ、試行実行・フェーズ進行・データ記録まで一気通貫で移行する。

**Architecture:** Unityは司令塔に徹する。刺激提示・RT計測・EMS発火スケジューリングはArduino（[integrated_full.ino](../../../integrated_full.ino)系）が担い、Unityは[ArduinoLink](../../Assets/Scripts/Experiment/ArduinoLink.cs)経由で `TRIAL`/`EMSLAT` を送り `TRIAL_RESULT`/`EMSLAT_RESULT` を受ける。条件（EMS/Voluntary）はカウンターバランスで別日セッションに割り当て、EMS発火タイミングは `Q10(side) − offset − EMS_to_Touch(side)`（LED点灯基準）で計算する。Phase CとPhase Dは DataModels/SubjectDataManager/Orchestrator を通じて密結合のため、一体の計画として実装する。

**Tech Stack:** Unity (C#, MonoBehaviour, Coroutine, Unity Test Framework/NUnit EditMode), [ReactionTest.Core](../../Assets/Scripts/Core) 純粋ロジックアセンブリ, System.IO.Ports（ArduinoLinkが所有）, JSON設定（experiment_config.json / config.json / session_info.json）。

**検証手段:** 純粋ロジック（EMSPolicy/TrialListGenerator/RtStatistics）はEditModeテスト（batchmode）。MonoBehaviour（TrialEngine/Orchestrator/DataLogger等）はコンパイル通過＋（B5実機検証時に）手動確認。batchmode実行は **Unityを閉じてから**（Temp/UnityLockfile有の間は別インスタンス不可）:
`"C:/Program Files/Unity/Hub/Editor/6000.2.9f1/Editor/Unity.exe" -runTests -batchmode -nographics -projectPath "c:/Users/tomoa/Unity/Projects/Reaction_Test" -testPlatform EditMode -testResults "<root>/test_results.xml" -logFile "<root>/test_run.log"`

---

## 0. 確定した設計判断（2026-06-01、ユーザー回答済み）

- TrialEngine は**クラス名・ファイル名を維持**して中身をArduino主導へ書き換える（シーンのSerializeField参照を温存し再配線を避ける）。
- TestGame モード（画面刺激×Ctrl/右矢印）と `ExperimentRunMode` は**削除**（新枠組のスコープ外）。
- **Voluntary セッションは EMSLatency フェーズをスキップ**し、一切EMSを発火しない。EMS_to_Touch は EMS セッションでのみ実測する。
- EMSLatency の EMS 強度調整は**手動（オペレータがInspector/キーでEMSCFGを調整）**。ソフトは「EMS発火→レイテンシ測定→安定性チェック(SD<config.EmsToTouchStabilitySdMs)→不安定なら警告して再測定」まで。
- タイミング式（既存 [EmsSafetyGate](../../Assets/Scripts/Core/EmsSafetyGate.cs) は手動発火の安全機構として既に導入済み）：`発火時刻ms(LED点灯基準) = Q10(side) − offset − EMS_to_Touch(side)`。offset は `experiment_config.json` の `EmsOffsetMs`（0=FastestBaseline）。負値は0にクランプして警告。
- **Arduinoがスケジュール発火する分の発火回数・安全上限はArduinoファームウェアの責務**（B5/Arduino担当）。Unity側 EMSController の安全ゲートは手動発火（EMSLatency調整・テスト発火）にのみ適用。緊急停止(Esc)は `ArduinoLink.SendReset()` でArduinoを停止させ、`EMSController.EmergencyStop()` で以後のPC送信を遮断する。
- 旧Agency資産 [StaircaseCalibrator.cs](../../Assets/Scripts/Experiment/StaircaseCalibrator.cs) / [AgencySurveyUI.cs](../../Assets/Scripts/Experiment/AgencySurveyUI.cs) は `GroupType`/`EMSDecision`/旧EMSPolicy へ依存しコンパイルを阻害するため**削除**する（git履歴で復元可能）。能動フローからの除外＝物理削除とする。

---

## 1. ファイル構成（変更マップ）

| ファイル | 区分 | 責務 |
|---|---|---|
| `Assets/Scripts/Experiment/ExperimentTypes.cs` | 改修 | `PhaseType` を新6フェーズに再定義。`GroupType`/`ExperimentRunMode`/`TrialInputMode`/`EMSDecision`/`ErrorType` を削除 |
| `Assets/Scripts/Experiment/EMSPolicy.cs` | 改修 | `ComputeFireTimingMs(q10,offset,emsToTouch)` と `ShouldFire(condition)` のみに簡素化（旧2メソッド削除） |
| `Assets/Scripts/Experiment/TrialListGenerator.cs` | 改修 | `GenerateBalancedColors(total,seed)` を追加（既存 `GenerateBalanced`/`DerivePhaseSeed` は流用、`DerivePhaseSeed`は新PhaseTypeで動作） |
| `Assets/Scripts/Experiment/DataModels.cs` | 改修 | `SessionMeta`/`TrialRecord` を新列へ。`AgencyOffsetConfig`→`CalibrationData`（Q10/EmsToTouch）へ改名・再定義 |
| `Assets/Scripts/Experiment/SubjectDataManager.cs` | 改修 | `SubjectConfig` に SubjectIndex/ConditionOrder/SRMapping。カウンターバランス割当・セッション条件解決・CalibrationData保存/読込。Test系メソッド削除 |
| `Assets/Scripts/Experiment/DataLogger.cs` | 改修 | 新CSVヘッダ＋FormatTrialLine。`includeInterventionColumns`/Test系を削除 |
| `Assets/Scripts/Experiment/TrialEngine.cs` | 改修(全面) | 画面刺激＋マウス撤廃。ArduinoLink経由で `TRIAL`/`EMSLAT` 送信→結果イベント待ち→採点→RTモニタ表示→Esc中断 |
| `Assets/Scripts/Experiment/ExperimentOrchestrator.cs` | 改修(全面) | 新フェーズ列・条件駆動・Q10算出・EMSLatency安定性・median/gain出力。Percentile自前実装を撤去しRtStatistics利用 |
| `Assets/Scripts/Experiment/StaircaseCalibrator.cs` | 削除 | 旧Agency階段法（gitで復元可） |
| `Assets/Scripts/Experiment/AgencySurveyUI.cs` | 削除 | 旧Agencyアンケート（gitで復元可） |
| `Assets/Tests/Editor/EMSPolicyTests.cs` | 新規 | ComputeFireTimingMs/ShouldFire の単体テスト |
| `Assets/Tests/Editor/TrialListGeneratorTests.cs` | 新規 | GenerateBalancedColors の単体テスト |

> `TaskRule.cs`（PickTargetSide/Evaluate）への依存はTrialEngine全面改修で除去する。TaskRuleが他から未参照になれば削除可だが、本計画では触らず残置（採点はTrialEngine内でinline）。実装時 `grep TaskRule` で参照を確認すること。

---

## 2. 新データモデル定義（先に型を固定）

実装の各タスクが参照する確定スキーマ。フィールド名はこの節を正本とする。

### SessionMeta（新）
```
SubjectId:string, Condition:ExperimentCondition, SessionNumber:int, SRMapping:SRMapping,
SessionDate:string(yyyy-MM-dd), DatetimeStart:string(ISO8601), AppVersion:string,
SeedPre:int, SeedEMSLatency:int, SeedTraining1:int, SeedPost1:int, SeedTraining2:int, SeedPost2:int
```

### TrialRecord（新）— 生RTは無加工保持
```
SubjectId:string, Condition:ExperimentCondition, SessionDate:string, Phase:PhaseType, TrialNumber:int,
StimColor:StimColor, CorrectHand:UserAction, ResponseSide:UserAction(touched, None=timeout),
IsCorrect:bool, ReactionTimeMs:float(raw, -1=timeout), Peak:int,
ExclusionFlag:ExclusionFlag, EmsFired:bool, EmsSide:UserAction, EmsFireTimingMs:float, EmsToTouchMs:float,
Timestamp:string(ISO8601)
```

### CalibrationData（AgencyOffsetConfigから改名）
```
Q10Left:float, Q10Right:float, EmsToTouchLeft:float, EmsToTouchRight:float
```

### SubjectConfig（新）
```
SubjectId:string, SubjectIndex:int, Order:ConditionOrder, Mapping:SRMapping,
LatestSessionNumber:int, LastUpdated:string
```
（Q10/EmsToTouch はセッション毎に変わるためセッションフォルダの `calibration.json`(CalibrationData) に保存し、SubjectConfigには持たせない。）

### CSVヘッダ（DataLogger）
```
SubjectID,Condition,SessionDate,Phase,TrialNumber,StimColor,CorrectHand,ResponseSide,IsCorrect,ReactionTime_ms,Peak,ExclusionFlag,EmsFired,EmsSide,EmsFireTiming_ms,EmsToTouch_ms,Timestamp
```

---

## 3. タスク

### Task 1: PhaseType 再定義と旧enum/struct削除

**Files:**
- Modify: `Assets/Scripts/Experiment/ExperimentTypes.cs`

- [ ] **Step 1: ExperimentTypes.cs を新内容で置換**

`ExperimentTypes.cs` 全体を以下にする（`GroupType`/`ExperimentRunMode`/`TrialInputMode`/`EMSDecision`/`ErrorType` を削除、`PhaseType` を再定義）:
```csharp
namespace ReactionTest.Experiment
{
    /// <summary>
    /// 実験フェーズ（FastestBaseline 枠組み）。1セッション＝1条件（EMS or Voluntary）。
    /// Pre → (EMSLatency:EMS条件のみ) → Training1 → Post1 → 休憩 → Training2 → Post2
    /// </summary>
    public enum PhaseType
    {
        Pre,
        EMSLatency,
        Training1,
        Post1,
        Training2,
        Post2
    }
}
```

- [ ] **Step 2: コンパイルは後続タスクで通す**

この時点では `GroupType` 等を参照する DataModels/Orchestrator/TrialEngine 等がコンパイルエラーになる（想定内）。Task 2〜10 完了で解消する。単独でのビルド確認はしない。

- [ ] **Step 3: Commit**
```bash
git add Assets/Scripts/Experiment/ExperimentTypes.cs
git commit -m "refactor: redefine PhaseType to FastestBaseline phases, drop legacy enums/EMSDecision"
```

### Task 2: EMSPolicy を新タイミング式へ（TDD）

**Files:**
- Modify: `Assets/Scripts/Experiment/EMSPolicy.cs`
- Create(test): `Assets/Tests/Editor/EMSPolicyTests.cs`

> EMSPolicy は `ReactionTest.Experiment`（Assembly-CSharp）にあり Core ではない。テストアセンブリ `ReactionTest.Core.Tests` は Core のみ参照するため EMSPolicy を直接テストできない。**EMSPolicy を Core へ移設**してテスト可能にする（UnityEngine非依存の純粋ロジックなので問題なし）。
> - Move: `Assets/Scripts/Experiment/EMSPolicy.cs` → `Assets/Scripts/Core/EMSPolicy.cs`（namespace `ReactionTest.Experiment` は不変）

- [ ] **Step 1: 失敗するテストを書く**

`Assets/Tests/Editor/EMSPolicyTests.cs`:
```csharp
using NUnit.Framework;
using ReactionTest.Experiment;

namespace ReactionTest.Experiment.Tests
{
    public class EMSPolicyTests
    {
        [Test]
        public void ComputeFireTimingMs_SubtractsOffsetAndEmsToTouch()
        {
            // Q10=300, offset=0, emsToTouch=50 → 250
            Assert.AreEqual(250f, EMSPolicy.ComputeFireTimingMs(300f, 0f, 50f), 1e-4f);
            // offset=40 → 210
            Assert.AreEqual(210f, EMSPolicy.ComputeFireTimingMs(300f, 40f, 50f), 1e-4f);
        }

        [Test]
        public void ShouldFire_OnlyForEmsCondition()
        {
            Assert.IsTrue(EMSPolicy.ShouldFire(ExperimentCondition.EMS));
            Assert.IsFalse(EMSPolicy.ShouldFire(ExperimentCondition.Voluntary));
        }
    }
}
```

- [ ] **Step 2: テスト実行して失敗を確認（Unityを閉じてbatchmode）**
Expected: コンパイルエラー（`EMSPolicy.ComputeFireTimingMs`/`ShouldFire` 未定義、または旧API残存）。

- [ ] **Step 3: EMSPolicy を Core へ移設し再実装**

`Assets/Scripts/Core/EMSPolicy.cs`（旧 `Assets/Scripts/Experiment/EMSPolicy.cs` は削除）:
```csharp
namespace ReactionTest.Experiment
{
    /// <summary>
    /// EMS発火タイミング（純粋ロジック）。
    /// 発火時刻(LED点灯基準, ms) = Q10(side) − offset − EMS_to_Touch(side)。
    /// </summary>
    public static class EMSPolicy
    {
        public static float ComputeFireTimingMs(float q10Ms, float offsetMs, float emsToTouchMs)
            => q10Ms - offsetMs - emsToTouchMs;

        /// <summary>EMS条件のみ発火。Voluntaryは発火しない。</summary>
        public static bool ShouldFire(ExperimentCondition condition)
            => condition == ExperimentCondition.EMS;
    }
}
```

- [ ] **Step 4: テスト実行して合格を確認**
Expected: EMSPolicyTests 2件 PASS（他は Task1 由来のコンパイルエラーが残るなら、このタスクのコミットは Task10 後の全緑確認まで保留してよい。最低限 EMSPolicy.cs 単体が正しいことをレビューする）。

- [ ] **Step 5: Commit**
```bash
git add Assets/Scripts/Core/EMSPolicy.cs Assets/Tests/Editor/EMSPolicyTests.cs
git rm Assets/Scripts/Experiment/EMSPolicy.cs
git commit -m "refactor: move EMSPolicy to Core, replace formula with Q10-offset-emsToTouch (+tests)"
```

### Task 3: TrialListGenerator に色バランス生成を追加（TDD）

**Files:**
- Modify: `Assets/Scripts/Experiment/TrialListGenerator.cs`（→ Core へ移設してテスト可能にする）
- Create(test): `Assets/Tests/Editor/TrialListGeneratorTests.cs`

> TrialListGenerator も純粋ロジック。Core へ移設（namespace不変）。`DerivePhaseSeed` の引数 `PhaseType` は新enumで問題なし。
> - Move: `Assets/Scripts/Experiment/TrialListGenerator.cs` → `Assets/Scripts/Core/TrialListGenerator.cs`

- [ ] **Step 1: 失敗するテストを書く**

`Assets/Tests/Editor/TrialListGeneratorTests.cs`:
```csharp
using NUnit.Framework;
using System.Linq;
using ReactionTest.Experiment;

namespace ReactionTest.Experiment.Tests
{
    public class TrialListGeneratorTests
    {
        [Test]
        public void GenerateBalancedColors_HalfRedHalfGreen()
        {
            var list = TrialListGenerator.GenerateBalancedColors(80, seed: 123);
            Assert.AreEqual(80, list.Length);
            Assert.AreEqual(40, list.Count(c => c == StimColor.Red));
            Assert.AreEqual(40, list.Count(c => c == StimColor.Green));
        }

        [Test]
        public void GenerateBalancedColors_Deterministic_ForSameSeed()
        {
            var a = TrialListGenerator.GenerateBalancedColors(40, 7);
            var b = TrialListGenerator.GenerateBalancedColors(40, 7);
            CollectionAssert.AreEqual(a, b);
        }

        [Test]
        public void GenerateBalancedColors_Empty_ForNonPositive()
        {
            Assert.AreEqual(0, TrialListGenerator.GenerateBalancedColors(0, 1).Length);
        }
    }
}
```

- [ ] **Step 2: テスト実行して失敗を確認**
Expected: `GenerateBalancedColors` 未定義のコンパイルエラー。

- [ ] **Step 3: GenerateBalancedColors を実装**

`Assets/Scripts/Core/TrialListGenerator.cs` に追加（既存メソッドは維持）:
```csharp
/// <summary>赤/緑同数のシャッフル済み刺激色リストを生成（Fisher-Yates, System.Random(seed)）。</summary>
public static StimColor[] GenerateBalancedColors(int totalTrials, int seed)
{
    if (totalTrials <= 0) return new StimColor[0];
    int half = totalTrials / 2;
    var list = new StimColor[totalTrials];
    for (int i = 0; i < half; i++) list[i] = StimColor.Red;
    for (int i = half; i < totalTrials; i++) list[i] = StimColor.Green;
    var rng = new System.Random(seed);
    int n = list.Length;
    while (n > 1)
    {
        n--;
        int k = rng.Next(n + 1);
        (list[k], list[n]) = (list[n], list[k]);
    }
    return list;
}
```

- [ ] **Step 4: テスト実行して合格を確認**
Expected: TrialListGeneratorTests 3件 PASS。

- [ ] **Step 5: Commit**
```bash
git add Assets/Scripts/Core/TrialListGenerator.cs Assets/Tests/Editor/TrialListGeneratorTests.cs
git rm Assets/Scripts/Experiment/TrialListGenerator.cs
git commit -m "feat: add GenerateBalancedColors, move TrialListGenerator to Core (+tests)"
```

### Task 4: DataModels を新スキーマへ

**Files:**
- Modify: `Assets/Scripts/Experiment/DataModels.cs`

- [ ] **Step 1: DataModels.cs を §2 のスキーマで全置換**

`DataModels.cs`:
```csharp
using System;

namespace ReactionTest.Experiment
{
    [Serializable]
    public class SessionMeta
    {
        public string SubjectId;
        public ExperimentCondition Condition;
        public int SessionNumber;
        public SRMapping Mapping;
        public string SessionDate;     // yyyy-MM-dd
        public string DatetimeStart;   // ISO 8601
        public string AppVersion;

        public int SeedPre;
        public int SeedEMSLatency;
        public int SeedTraining1;
        public int SeedPost1;
        public int SeedTraining2;
        public int SeedPost2;
    }

    [Serializable]
    public class TrialRecord
    {
        public string SubjectId;
        public ExperimentCondition Condition;
        public string SessionDate;
        public PhaseType Phase;
        public int TrialNumber;
        public StimColor StimColor;
        public UserAction CorrectHand;
        public UserAction ResponseSide;   // touched side, None=timeout
        public bool IsCorrect;
        public float ReactionTimeMs;      // raw, -1=timeout
        public int Peak;
        public ExclusionFlag ExclusionFlag;
        public bool EmsFired;
        public UserAction EmsSide;
        public float EmsFireTimingMs;
        public float EmsToTouchMs;
        public string Timestamp;          // ISO 8601
    }

    /// <summary>セッション毎のキャリブレーション結果（左右別、calibration.jsonに保存）。</summary>
    [Serializable]
    public class CalibrationData
    {
        public float Q10Left;
        public float Q10Right;
        public float EmsToTouchLeft;
        public float EmsToTouchRight;
    }
}
```

- [ ] **Step 2: Commit**（コンパイルは Task10 で通す）
```bash
git add Assets/Scripts/Experiment/DataModels.cs
git commit -m "refactor: new SessionMeta/TrialRecord schema, rename AgencyOffsetConfig to CalibrationData"
```

### Task 5: SubjectDataManager をカウンターバランス＆CalibrationData対応へ

**Files:**
- Modify: `Assets/Scripts/Experiment/SubjectDataManager.cs`

- [ ] **Step 1: SubjectConfig と公開APIを新仕様へ全置換**

要件（§2スキーマ準拠）:
- `SubjectConfig`: `SubjectId, SubjectIndex, Order, Mapping, LatestSessionNumber, LastUpdated`。
- `LoadOrCreateSubject(string subjectId, int subjectIndex)`: 新規時 `Order=Counterbalance.OrderFor(subjectIndex)`, `Mapping=Counterbalance.MappingFor(subjectIndex)` を割当て保存。既存時は読込（保存済みOrder/Mappingを優先、subjectIndex不一致はエラーログ）。戻り値は `SubjectConfig`。
- `CreateSessionFolder()`: 既存ロジック流用（`session_NN_yyyyMMdd_HHmmss`）。`LatestSessionNumber++`。
- `int CurrentSessionNumber => _currentConfig.LatestSessionNumber;`
- `ExperimentCondition ConditionForCurrentSession()` → `Counterbalance.ConditionForSession(_currentConfig.Order, _currentConfig.LatestSessionNumber)`。
- `SRMapping CurrentMapping => _currentConfig.Mapping;`
- `void SaveCalibration(CalibrationData data)`: `_currentSessionPath/calibration.json` にJSON保存。
- `CalibrationData LoadCalibration()`: 同ファイルがあれば読込、なければ null。
- **削除**: `CreateTestSessionFolder`, `GetTestSessionNumber`, `testDataFolderName`, `GetAgencyOffsetConfig`, `SaveCalibrationResult`, `HasCalibrationData`, 旧`GroupType`引数。

実装（全置換）:
```csharp
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

        private string _rootPath;
        private SubjectConfig _currentConfig;
        private string _currentSessionPath;

        public SubjectConfig CurrentConfig => _currentConfig;
        public string CurrentSessionPath => _currentSessionPath;
        public string RootPath => _rootPath;
        public int CurrentSessionNumber => _currentConfig != null ? _currentConfig.LatestSessionNumber : 0;
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
            _currentConfig.LatestSessionNumber++;
            string folder = $"session_{_currentConfig.LatestSessionNumber:D2}_{DateTime.Now:yyyyMMdd_HHmmss}";
            _currentSessionPath = Path.Combine(subjectPath, folder);
            Directory.CreateDirectory(_currentSessionPath);
            SaveConfig();
            Debug.Log($"Created session folder: {_currentSessionPath}");
            return _currentSessionPath;
        }

        public ExperimentCondition ConditionForCurrentSession()
            => Counterbalance.ConditionForSession(_currentConfig.Order, _currentConfig.LatestSessionNumber);

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
```

- [ ] **Step 2: Commit**
```bash
git add Assets/Scripts/Experiment/SubjectDataManager.cs
git commit -m "refactor: SubjectDataManager counterbalance assignment + per-session CalibrationData"
```

### Task 6: DataLogger を新CSVへ

**Files:**
- Modify: `Assets/Scripts/Experiment/DataLogger.cs`

- [ ] **Step 1: ヘッダ・FormatTrialLine を §2 CSV仕様へ、Test系を削除**

変更点:
- `CsvHeader` を §2 の17列に。`TestCsvHeader`/`_includeInterventionColumns` と `Initialize(SessionMeta)`（旧後方互換）と `InitializeWithPath` の `includeInterventionColumns` 引数を削除。
- `InitializeWithPath(SessionMeta session, string outputDir)` の2引数版に。
- `FormatTrialLine` を新フィールドで再実装（enumは `ToString()`、boolは0/1、floatは `F3`/InvariantCulture、`CsvEscape` 流用）:
```csharp
private const string CsvHeader =
    "SubjectID,Condition,SessionDate,Phase,TrialNumber,StimColor,CorrectHand,ResponseSide,IsCorrect," +
    "ReactionTime_ms,Peak,ExclusionFlag,EmsFired,EmsSide,EmsFireTiming_ms,EmsToTouch_ms,Timestamp";

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
```
（`AppendTrial`/`FlushBuffer`/`CsvEscape`/`SaveSessionInfo`/auto-flush は流用。）

- [ ] **Step 2: Commit**
```bash
git add Assets/Scripts/Experiment/DataLogger.cs
git commit -m "refactor: DataLogger new FastestBaseline CSV columns, drop test/intervention modes"
```

### Task 7: 旧Agency資産を削除

**Files:**
- Delete: `Assets/Scripts/Experiment/StaircaseCalibrator.cs`(+`.meta`)
- Delete: `Assets/Scripts/Experiment/AgencySurveyUI.cs`(+`.meta`)

- [ ] **Step 1: 削除**
```bash
git rm Assets/Scripts/Experiment/StaircaseCalibrator.cs Assets/Scripts/Experiment/StaircaseCalibrator.cs.meta
git rm Assets/Scripts/Experiment/AgencySurveyUI.cs Assets/Scripts/Experiment/AgencySurveyUI.cs.meta
```
> 実装時、他に `StaircaseCalibrator`/`AgencySurveyUI` を参照するファイルが無いか `grep` で確認（Orchestratorは Task 9 で除去済みのはず）。

- [ ] **Step 2: Commit**
```bash
git commit -m "chore: remove legacy StaircaseCalibrator/AgencySurveyUI (recoverable via git history)"
```

### Task 8: TrialEngine を Arduino主導へ全面改修

**Files:**
- Modify(全面): `Assets/Scripts/Experiment/TrialEngine.cs`

設計:
- 依存（SerializeField）: `ArduinoLink arduinoLink`, `EMSController emsController`（緊急停止用）, `Text feedbackText`（RTモニタ）, 数値設定（responseTimeoutSec, feedbackDurationSec, foreperiodはOrchestratorがITIで待つので最小限）。
- `ArduinoLink.OnTrialResult`/`OnEmsLatencyResult` を `OnEnable`で購読・`OnDisable`で解除。受信を `_lastTrialResult`/`_hasTrialResult`（および EMSLat 版）に格納。試行は逐次・同時に1件のみ待つ前提。
- 公開: `bool IsAborted`, `void ResetAbort()`。
- `IEnumerator RunTrial(PhaseType phase, int trialIndex, StimColor color, UserAction correctHand, UserAction emsSide, int emsDelayUs, ExperimentCondition condition, string sessionDate, Action<TrialRecord> onCompleted)`
- `IEnumerator RunEMSLatencyTrial(UserAction side, int trialIndex, Action<float> onLatencyMs)`（記録はOrchestratorが必要に応じて）。

- [ ] **Step 1: TrialEngine.cs を全置換**

```csharp
using System;
using System.Collections;
using UnityEngine;
using UnityEngine.UI;
using UnityEngine.InputSystem;

namespace ReactionTest.Experiment
{
    /// <summary>
    /// Arduino主導の試行実行。Unityは TRIAL/EMSLAT を送り、TRIAL_RESULT/EMSLAT_RESULT を待って採点・記録する。
    /// 刺激提示・RT計測・EMS発火スケジューリングはArduino側。
    /// </summary>
    public class TrialEngine : MonoBehaviour
    {
        [Header("Link / EMS")]
        [SerializeField] private ArduinoLink arduinoLink;
        [SerializeField] private EMSController emsController;

        [Header("Feedback (RTモニタ)")]
        [SerializeField] private Text feedbackText;
        [SerializeField] private bool showReactionTimeFeedback = true;
        [SerializeField] private float feedbackDurationSec = 0.8f;

        [Header("Timing")]
        [Tooltip("TRIAL_RESULT を待つ上限（秒）。Arduino側の応答窓 + 通信余裕。")]
        [SerializeField] private float resultTimeoutSec = 3.0f;

        private bool _hasTrialResult;
        private TrialResult _lastTrialResult;
        private bool _hasLatResult;
        private EmsLatencyResult _lastLatResult;

        private bool _isAborted;
        public bool IsAborted => _isAborted;
        public void ResetAbort() => _isAborted = false;

        public void SetArduinoLink(ArduinoLink link) => arduinoLink = link;
        public void SetEMSController(EMSController c) => emsController = c;

        private void OnEnable()
        {
            if (arduinoLink != null)
            {
                arduinoLink.OnTrialResult += HandleTrialResult;
                arduinoLink.OnEmsLatencyResult += HandleLatResult;
            }
            HideFeedback();
        }

        private void OnDisable()
        {
            if (arduinoLink != null)
            {
                arduinoLink.OnTrialResult -= HandleTrialResult;
                arduinoLink.OnEmsLatencyResult -= HandleLatResult;
            }
        }

        private void HandleTrialResult(TrialResult r) { _lastTrialResult = r; _hasTrialResult = true; }
        private void HandleLatResult(EmsLatencyResult r) { _lastLatResult = r; _hasLatResult = true; }

        public IEnumerator RunTrial(
            PhaseType phase, int trialIndex, StimColor color, UserAction correctHand,
            UserAction emsSide, int emsDelayUs, ExperimentCondition condition, string sessionDate,
            Action<TrialRecord> onCompleted)
        {
            HideFeedback();
            _hasTrialResult = false;

            if (arduinoLink != null)
                arduinoLink.SendTrial(color, correctHand, emsSide, emsDelayUs);
            else
                UnityEngine.Debug.Log($"[Sim] TRIAL {color}/{correctHand} ems={emsSide}@{emsDelayUs}us");

            float deadline = Time.realtimeSinceStartup + resultTimeoutSec;
            var keyboard = Keyboard.current;
            while (!_hasTrialResult)
            {
                if (keyboard != null && keyboard.escapeKey.wasPressedThisFrame) { Abort(); break; }
                if (Time.realtimeSinceStartup > deadline)
                {
                    UnityEngine.Debug.LogWarning($"TrialEngine: TRIAL_RESULT timeout (trial {trialIndex}).");
                    break;
                }
                yield return null;
            }

            // 結果→レコード（受信なし/中断時は timeout 相当）
            TrialResult res = _hasTrialResult ? _lastTrialResult
                : new TrialResult { TouchedSide = UserAction.None, RtMs = -1f, Peak = 0, EmsFired = false, TimedOut = true };

            bool isCorrect = !res.TimedOut && res.TouchedSide == correctHand;

            var record = new TrialRecord
            {
                Condition = condition,
                SessionDate = sessionDate,
                Phase = phase,
                TrialNumber = trialIndex,
                StimColor = color,
                CorrectHand = correctHand,
                ResponseSide = res.TouchedSide,
                IsCorrect = isCorrect,
                ReactionTimeMs = res.RtMs,
                Peak = res.Peak,
                EmsFired = res.EmsFired,
                EmsSide = emsSide,
                EmsFireTimingMs = emsDelayUs / 1000f,
                Timestamp = DateTime.UtcNow.ToString("o")
                // SubjectId / ExclusionFlag / EmsToTouchMs は Orchestrator が補完
            };

            if (showReactionTimeFeedback && !res.TimedOut && res.RtMs > 0f)
                yield return ShowFeedback($"{res.RtMs:F0} ms", Color.white);
            else if (showReactionTimeFeedback)
                yield return ShowFeedback(res.TimedOut ? "—" : "?", Color.gray);

            onCompleted?.Invoke(record);
        }

        public IEnumerator RunEMSLatencyTrial(UserAction side, int trialIndex, Action<float> onLatencyMs)
        {
            HideFeedback();
            _hasLatResult = false;

            if (arduinoLink != null) arduinoLink.SendEmsLatency(side);
            else UnityEngine.Debug.Log($"[Sim] EMSLAT {side}");

            float deadline = Time.realtimeSinceStartup + resultTimeoutSec;
            var keyboard = Keyboard.current;
            while (!_hasLatResult)
            {
                if (keyboard != null && keyboard.escapeKey.wasPressedThisFrame) { Abort(); break; }
                if (Time.realtimeSinceStartup > deadline)
                {
                    UnityEngine.Debug.LogWarning($"TrialEngine: EMSLAT_RESULT timeout (trial {trialIndex}).");
                    break;
                }
                yield return null;
            }

            float latency = (_hasLatResult && !_lastLatResult.TimedOut) ? _lastLatResult.LatencyMs : -1f;
            if (showReactionTimeFeedback && latency > 0f)
                yield return ShowFeedback($"{latency:F0} ms", Color.cyan);
            onLatencyMs?.Invoke(latency);
        }

        private void Abort()
        {
            _isAborted = true;
            if (arduinoLink != null) arduinoLink.SendReset();
            if (emsController != null) emsController.EmergencyStop();
            UnityEngine.Debug.LogError("TrialEngine: ABORT (Escape) — sent RESET to Arduino.");
        }

        private IEnumerator ShowFeedback(string msg, Color color)
        {
            if (feedbackText == null) yield break;
            feedbackText.text = msg;
            feedbackText.color = color;
            feedbackText.gameObject.SetActive(true);
            yield return new WaitForSeconds(feedbackDurationSec);
            feedbackText.gameObject.SetActive(false);
        }

        private void HideFeedback()
        {
            if (feedbackText != null) feedbackText.gameObject.SetActive(false);
        }
    }
}
```

- [ ] **Step 2: Commit**
```bash
git add Assets/Scripts/Experiment/TrialEngine.cs
git commit -m "refactor: rewrite TrialEngine as Arduino-driven (TRIAL/EMSLAT via ArduinoLink), drop screen+mouse"
```

### Task 9: ExperimentOrchestrator を新フェーズ列・条件駆動へ全面改修

**Files:**
- Modify(全面): `Assets/Scripts/Experiment/ExperimentOrchestrator.cs`

設計（Start コルーチン）:
1. `ValidateReferences()`（trialEngine/dataLogger/subjectDataManager/arduinoLink 必須、phaseTransitionUI/emsController 任意）。
2. `_config = ExperimentConfig.LoadOrCreate(projectRoot/experiment_config.json)`。
3. `subjectDataManager.LoadOrCreateSubject(subjectId, subjectIndex)`。`CreateSessionFolder()`。
4. `condition = subjectDataManager.ConditionForCurrentSession()`、`mapping = subjectDataManager.CurrentMapping`、`sessionDate = DateTime.Now:yyyy-MM-dd`。
5. Arduinoへ固定閾値とEMS強度を送信: `arduinoLink.SendThreshold(Left, _config.TouchThresholdLeft)` / `Right` / `arduinoLink.SendEmsConfig(_config.EmsPulseWidthUs, _config.EmsPulseCount, _config.EmsBurstCount, _config.EmsPulseIntervalUs)`。
6. `SessionMeta` を構築（seedは `TrialListGenerator.DerivePhaseSeed(subjectId, sessionPath, phase)`）。`dataLogger.InitializeWithPath(meta, sessionPath)`。
7. **Pre**（`_config.PreTrials`, ems off）→ 正答RTを左右別収集 → `q10L=RtStatistics.Q10(correctRTsLeft)`, `q10R=...Right`。
8. **EMSLatency**（condition==EMS のときのみ、`_config.EmsLatencyTrials` を左右に二分）→ 左右別レイテンシ収集 → 安定性チェック（`RtStatistics.SampleStdDev(side) < _config.EmsToTouchStabilitySdMs`）。不安定なら警告し再測定（最大3回）。`emsToTouchL/R = RtStatistics.Median(side)`。Voluntary時は emsToTouch=0。
9. `subjectDataManager.SaveCalibration(new CalibrationData{Q10Left=q10L,...})`。
10. **Training1**(`_config.TrainingTrials`) → **Post1**(`_config.PostTrials`) → 休憩(`ShowPhaseTransition`) → **Training2** → **Post2**。
11. median/gain 出力（`RunBlock` がフェーズ別に正答RTを集計）：`gain = (median(Post1)+median(Post2))/2 − median(Pre)`。サマリJSON `summary.json` をセッションフォルダへ + ログ。
12. 各試行後 `CheckAbort()`（trialEngine.IsAborted）→ trueなら `arduinoLink.SendReset()`, `dataLogger.FlushBuffer()`, 中断UI, yield break。

トレーニング試行のEMS引数計算（ヘルパー）:
```csharp
// condition==EMS かつ phase∈{Training1,Training2} のみEMS、それ以外は None
private (UserAction emsSide, int emsDelayUs, float fireMs) ComputeEms(
    PhaseType phase, UserAction correctHand, ExperimentCondition condition,
    float q10L, float q10R, float e2tL, float e2tR)
{
    bool isTraining = phase == PhaseType.Training1 || phase == PhaseType.Training2;
    if (!(isTraining && EMSPolicy.ShouldFire(condition)))
        return (UserAction.None, 0, 0f);

    float q10 = correctHand == UserAction.Left ? q10L : q10R;
    float e2t = correctHand == UserAction.Left ? e2tL : e2tR;
    float fireMs = EMSPolicy.ComputeFireTimingMs(q10, _config.EmsOffsetMs, e2t);
    if (fireMs < 0f) { Debug.LogWarning($"Fire timing < 0 ({fireMs:F1}ms) → clamp 0."); fireMs = 0f; }
    return (correctHand, Mathf.RoundToInt(fireMs * 1000f), fireMs);
}
```

ブロック実行ヘルパー（Pre/Post/Trainingで共用）:
```csharp
// 戻り値: そのフェーズの「正答RT」リスト（median/gain用）
private IEnumerator RunBlock(PhaseType phase, int trials, int seed,
    ExperimentCondition condition, SRMapping mapping, string sessionDate,
    float q10L, float q10R, float e2tL, float e2tR,
    List<float> correctRTsOut, List<float> correctRTsLeftOut, List<float> correctRTsRightOut)
{
    StimColor[] colors = TrialListGenerator.GenerateBalancedColors(trials, seed);
    for (int i = 1; i <= trials; i++)
    {
        StimColor color = colors[i - 1];
        UserAction correctHand = Counterbalance.CorrectHand(color, mapping);
        var (emsSide, emsDelayUs, fireMs) = ComputeEms(phase, correctHand, condition, q10L, q10R, e2tL, e2tR);

        TrialRecord rec = null;
        yield return StartCoroutine(trialEngine.RunTrial(
            phase, i, color, correctHand, emsSide, emsDelayUs, condition, sessionDate,
            r => rec = r));

        // Orchestrator補完
        rec.SubjectId = subjectId;
        rec.EmsToTouchMs = emsSide == UserAction.Left ? e2tL : (emsSide == UserAction.Right ? e2tR : 0f);
        rec.ExclusionFlag = RtStatistics.Classify(rec.ReactionTimeMs, _config.RtAnticipationMs, _config.RtLapseMaxMs, 0f);
        dataLogger.AppendTrial(rec);

        if (rec.IsCorrect && rec.ReactionTimeMs > 0f)
        {
            correctRTsOut?.Add(rec.ReactionTimeMs);
            if (correctHand == UserAction.Left) correctRTsLeftOut?.Add(rec.ReactionTimeMs);
            else correctRTsRightOut?.Add(rec.ReactionTimeMs);
        }

        if (trialEngine.IsAborted) yield break;
    }
    dataLogger.FlushBuffer();
}
```

> `RtStatistics.Classify` は upperSdBound=0 で anticipation(<RtAnticipationMs)/lapse(>RtLapseMaxMs) のみ判定（+3SDはPython側）。`Mathf` は UnityEngine。`_config` は `ExperimentConfig`。

- [ ] **Step 1: ExperimentOrchestrator.cs を上記設計で全置換**

（完全な実装をこのタスクで書く。`subjectId`/`subjectIndex` は `[SerializeField]`。Percentile/ComputeIQRFilteredMean/旧フェーズ・旧参照は全廃。median は `RtStatistics.Median`。）

- [ ] **Step 2: Commit**
```bash
git add Assets/Scripts/Experiment/ExperimentOrchestrator.cs
git commit -m "refactor: Orchestrator FastestBaseline sequence (Pre/EMSLatency/Train1/Post1/Train2/Post2), condition-driven, Q10+gain"
```

### Task 10: 全体コンパイル＆全テスト緑の確認

**Files:** （なし。検証のみ）

- [ ] **Step 1: Unityを閉じてもらい batchmode 実行**
Run: 冒頭の batchmode コマンド。
Expected: `EXIT=0`、`test_results.xml` の `total` が（Phase A/B分 + EMSPolicy 2 + TrialListGenerator 3）件で `failed="0"`。`test_run.log` に `error CS`/`warning CS` が無いこと。

- [ ] **Step 2: 残存参照スキャン**
`grep` で `GroupType`/`EMSDecision`/`ExperimentRunMode`/`TrialInputMode`/`AgencyOffsetConfig`/`StaircaseCalibrator`/`AgencySurveyUI`/`ErrorType`/`TaskRule` の残存参照が無い（またはTaskRule残置のみ）ことを確認。
Expected: 能動コードからの参照なし。

- [ ] **Step 3: Commit（必要なら微修正）**
```bash
git add -A
git commit -m "fix: resolve remaining references after Phase C+D migration"
```

---

## 4. シーン再配線メモ（実装後・Unity GUIで手動）

コードはコンパイル＆テスト緑になるが、**シーン上の参照割当はコードでは設定されない**。次回Unityを開いたら以下を確認/割当：
- `ExperimentOrchestrator`: `arduinoLink`, `trialEngine`, `dataLogger`, `subjectDataManager`, `phaseTransitionUI`(任意), `emsController`(任意), `subjectId`, `subjectIndex`。
- `TrialEngine`: `arduinoLink`, `emsController`, `feedbackText`。
- `EMSController`: `arduinoLink`（Task B4で追加済）。
- 旧 `AgencySurveyUI`/`StaircaseCalibrator` を参照していたGameObject/SerializeFieldは削除（Missing参照の掃除）。
- 旧 `stimulusImage` 等の画面刺激オブジェクトは新フローで未使用（残しても害はないが整理推奨）。

---

## 5. 自己レビュー結果

- **仕様カバレッジ**: PhaseType新6フェーズ(Task1)、タイミング式(Task2)、色バランス試行(Task3)、新TrialRecord/SessionMeta/CalibrationData(Task4)、カウンターバランス＆条件解決＆Calibration保存(Task5)、新CSV(Task6)、Agency除去(Task7)、Arduino主導試行(Task8)、新フェーズ列＋条件駆動＋Q10＋EMSLatency安定性＋median/gain＋除外フラグ(Task9)。Voluntaryスキップ・手動強度調整・緊急停止RESETを反映。
- **型整合**: `ExperimentCondition`/`StimColor`/`SRMapping`/`ConditionOrder`/`ExclusionFlag`/`UserAction`(CoreEnums)、`TrialResult`/`EmsLatencyResult`(ArduinoProtocol)、`RtStatistics.Q10/Median/SampleStdDev/Classify`、`Counterbalance.OrderFor/MappingFor/ConditionForSession/CorrectHand`、`ArduinoLink.SendTrial/SendEmsLatency/SendThreshold/SendEmsConfig/SendReset` と各タスクの呼び出しが一致。
- **依存順**: Task1→DataModels/SubjectDataManager/DataLogger/TrialEngine/Orchestrator がコンパイルエラーになるが、Task4〜9で解消。全緑確認はTask10。EMSPolicy/TrialListGeneratorのテストはCore移設で先行検証可。
- **未確定/リスク**: TRIALコマンドに応答タイムアウト引数が無い（Arduino側応答窓に依存）→ Unityは `resultTimeoutSec` で安全網。Arduinoスケジュール発火の安全上限はファーム責務。`subjectIndex` 運用（被験者採番）は実験者がInspectorで管理。

---

## 6. 実装後の残作業（このプランの外）
- **B5 実機手動検証**: STATUS往復 / EMS:R,L単発 / TRIAL 1試行のRT受信 / EMSLAT 1試行 / 緊急停止RESET。
- Python解析（[Analysis/](../../Analysis/)）の新CSV列対応（median/gain/+3SD/除外）。
- Arduinoファーム（integrated_full系）の §3プロトコル整合（TRIAL/EMSLAT/THR/EMSCFG、応答窓、スケジュール発火安全上限）。
