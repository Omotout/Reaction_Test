# FastestBaseline 移行 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** EMS反応時間トレーニング実験系を、Kasahara主体感枠組みから「FastestBaseline(Q10)トレーニング」枠組みへ移行する。刺激提示・反応検出・RT計測をArduino側に移し、Unityを司令塔（フェーズ進行・Q10/タイミング算出・記録）に再編する。

**Architecture:** PC(Unity)=頭脳（フェーズ進行・条件/カウンターバランス管理・Q10とEMS発火タイミング算出・コマンド送信・RT受信・記録・モニタ表示）。Arduino=リアルタイム入出力（2色LED点灯・静電容量タッチ検出・micros()精度のRT計測・EMS発火スケジューリング）。両者は115200bpsの行ベースプロトコルで通信し、Arduino主導でLED点灯〜EMS発火〜タッチ検出の時間臨界パスを実行する。

**Tech Stack:** Unity (C#, MonoBehaviour, Unity Test Framework/NUnit EditModeテスト), System.IO.Ports シリアル通信, Arduino (integrated_full.ino 系, L298N, 静電容量タッチ, 2色LED), JSON設定ファイル。

---

## 0. 前提・確定した設計判断（2026-06-01）

- 刺激＝2色LED（赤/黄緑）、反応＝薬指の静電容量タッチ（**左右2電極**）、RT計測＝Arduino内部（`micros()`精度）。Arduino参照実装は [integrated_full.ino](../../../integrated_full.ino)。Arduino本体は別途実装。本計画は**Unity側 ＋ プロトコル契約**を対象とする。
- EMS発火タイミング式を一本化：`発火時刻(LED点灯基準) = Q10(side) − offset − EMS_to_Touch(side)`。
  - `offset = 0` → FastestBaselineモード（既定）。`offset > 0`（設定可）→ agency_EMSモード。
  - 条件 `Voluntary` → EMS発火OFF。
- Q10(FastestBaseline)は左右別。median/gainの主分析値も出力。
- フェーズ順：（固定閾値運用のためBASELINE工程は省略）`Pre(80,EMSなし)` → `EMSLatency(30,EMSあり：EMS_to_Touch実測＋強度調整＋安定性<4ms)` → `Training1(60)` → `Post1(80)` → 休憩 → `Training2(60)` → `Post2(80)`。Practiceは撤廃。
- タッチ閾値は**固定値**（設定ファイル）。装置調整時に手動`BASELINE`で適正値を求めて記入する運用。
- 除外：生RTは全件無加工保存。anticipation(<150ms)・>1000ms はUnity記録時にフラグ。個人内+3SDとmedian/gainはPython解析側で算出。
- 試行数・offset・ITI・閾値・除外パラメータは `experiment_config.json` で可変（事前/本実験で差替）。
- カウンターバランス：被験者config.jsonに ConditionOrder と SRMapping を保持。被験者内2条件は別日2セッションで実施。
- 主体感機構（StaircaseCalibrator / AgencySurveyUI）は能動フローから外し、ファイルは残置（オプション資産）。

---

## 1. アーキテクチャ全体像

```
ExperimentOrchestrator（司令塔）
   ├─ ExperimentConfig         [新] 設定ファイル読込（試行数/offset/ITI/閾値/除外）
   ├─ Counterbalance           [新] 条件順序・S-Rマッピング・セッション→条件の解決
   ├─ RtStatistics             [新] Q10/median/SD/percentile/除外フラグ（純粋ロジック）
   ├─ ArduinoLink              [新] 双方向シリアル（送信＋受信パース）。単一のシリアル所有者
   ├─ TrialRunner（旧TrialEngine改） トライアル指令送信→RT受信→採点→モニタ表示→中断
   │     └─ ArduinoLink ──► Arduino (integrated_full系: LED/Touch/EMS/RT)
   ├─ EMSPolicy（改）          発火タイミング式（Q10−offset−EMS_to_Touch）＋条件ゲート
   ├─ DataLogger（改）         新CSV列（condition/stimColor/correctHand/exclusion/emsToTouch等）
   ├─ SubjectDataManager（改） config.json拡張（順序/マッピング/セッション別条件/Q10/閾値）
   ├─ TrialListGenerator       [流用] 左右均衡シャッフル
   ├─ PhaseTransitionUI        [流用] フェーズ間教示
   ├─ StaircaseCalibrator      [残置/オプション] 主体感階段法
   └─ AgencySurveyUI           [残置/オプション] 主体感アンケート
```

---

## 2. ファイル別 改修内容

| ファイル | 区分 | 内容 |
|---|---|---|
| `Assets/Scripts/Core/ReactionTest.Core.asmdef` | 新規 | 純粋ロジック用アセンブリ。Auto Referenced=trueでAssembly-CSharpから利用可 |
| `Assets/Scripts/Core/CoreEnums.cs` | 新規 | `UserAction`をここへ移設＋新enum（StimColor/ExperimentCondition/ConditionOrder/SRMapping/ExclusionFlag/Hand不要・UserAction流用） |
| `Assets/Scripts/Core/ExperimentConfig.cs` | 新規 | 設定ファイルの型＋LoadOrCreate |
| `Assets/Scripts/Core/RtStatistics.cs` | 新規 | Percentile/Q10/Median/Mean/SampleStdDev/Classify |
| `Assets/Scripts/Core/Counterbalance.cs` | 新規 | 順序・マッピング・条件・正解手の決定（純粋関数） |
| `Assets/Tests/Editor/ReactionTest.Core.Tests.asmdef` | 新規 | EditModeテストアセンブリ |
| `Assets/Tests/Editor/RtStatisticsTests.cs` 他 | 新規 | 純粋ロジックの単体テスト |
| `Assets/Scripts/Experiment/ExperimentTypes.cs` | 改修 | `UserAction`をCoreへ移動。`PhaseType`を Pre/EMSLatency/Training1/Post1/Training2/Post2/Test に再定義。GroupType→廃止し条件はExperimentConditionへ |
| `Assets/Scripts/Experiment/ArduinoLink.cs` | 新規 | 双方向シリアル（TXキュー＋RXスレッド＋行パース＋結果イベント）。EMSControllerの送信専用基盤を置換 |
| `Assets/Scripts/Experiment/EMSController.cs` | 改修 | ArduinoLink上のEMS安全機構（不応期/最大発火/緊急停止/強度設定）に再編。SerialPort直接所有を撤廃 |
| `Assets/Scripts/Experiment/TrialEngine.cs` → `TrialRunner.cs` | 改修 | 画面刺激＋マウス入力を撤廃。`TRIAL`/`EMSLAT`指令送信→`ArduinoLink`からRT受信→採点→RTモニタ表示→Esc中断。クラス名はTrialRunnerへ |
| `Assets/Scripts/Experiment/EMSPolicy.cs` | 改修 | `ComputeFireTiming(q10, offset, emsToTouch)`へ。条件/offsetを反映 |
| `Assets/Scripts/Experiment/DataModels.cs` | 改修 | TrialRecord新列、SessionMeta拡張、SubjectConfig拡張、AgencyOffsetConfig→CalibrationData改名 |
| `Assets/Scripts/Experiment/DataLogger.cs` | 改修 | 新CSVヘッダ＋FormatTrialLine |
| `Assets/Scripts/Experiment/SubjectDataManager.cs` | 改修 | 順序/マッピング割当、セッション→条件解決、Q10/EMS_to_Touch/閾値保存 |
| `Assets/Scripts/Experiment/ExperimentOrchestrator.cs` | 改修 | 新フェーズ列、条件駆動、Q10算出、EMSLatency安定性チェック＋再calib、median/gain出力、TrialRunner/ArduinoLink連携。Percentileを撤去しRtStatistics利用 |
| `Assets/Scripts/Experiment/StaircaseCalibrator.cs` | 残置 | 能動フローから除外。オプションモード用に保持 |
| `Assets/Scripts/Experiment/AgencySurveyUI.cs` | 残置 | 同上 |
| `Arduino_ReactionTest_EMS.ino` | 廃止予定 | integrated_full.ino系へ統合（Arduino側担当） |
| `{projectRoot}/experiment_config.json` | 新規 | 実行時生成される既定設定 |

---

## 3. 新旧 シリアルプロトコル対応表（Unity↔Arduino 契約）

> Arduino本体は別途実装。Unityは下表の送信文字列とパース規則を実装し、Arduinoはこれに整合させる。すべて行ベース・`\n`終端・115200bps。座標系：`R`=右手, `L`=左手, `Red`/`Green(YG)`。時間はµs。
>
> **シーケンスID（`<id>`）**: TRIAL/EMSLAT には単調増加の整数 `<id>` を載せる。**Arduinoは対応する結果(TRIAL_RESULT/EMSLAT_RESULT)で同じ `<id>` を必ずエコーする**こと。Unityは期待idと一致する結果のみ採用し、タイムアウト後に届く前試行の遅延結果を破棄して試行ずれ（RTの1試行ずれ）を防ぐ（Phase C+D コードレビュー指摘で追加）。

### Unity → Arduino

| 用途 | 旧 (`Arduino_ReactionTest_EMS.ino`) | 新（本計画） | Arduino動作 |
|---|---|---|---|
| トライアル（Pre/Post, EMSなし） | （なし。Unityが画面提示） | `TRIAL,<id>,<led>,<resp>,N,0` | ledを点灯しt0=micros()。respタッチ待ち。検出で`TRIAL_RESULT`返信（idエコー） |
| トライアル（Training, EMSあり） | （なし） | `TRIAL,<id>,<led>,<resp>,<emsSide>,<emsDelayUs>` | 同上＋t0+emsDelayUsにemsSideへEMS発火 |
| EMSレイテンシ計測 | 旧はUnipoll（視覚なしEMS→マウス） | `EMSLAT,<id>,<side>` | LEDなしでsideにEMS発火、t0=EMS onset、sideタッチまで計測。`EMSLAT_RESULT`返信（idエコー） |
| タッチ閾値設定（固定） | （なし） | `THR,<side>,<value>` | side電極の検出閾値を設定 |
| EMS強度設定 | `W../C../B../I..` | `EMSCFG,<width>,<count>,<burst>,<interval>` | 波形パラメータ設定（強度調整用） |
| LED消灯/全停止 | `L`/`R`即時発火 | `LED:OFF` / `RESET` | 消灯・全停止 |
| EMS手動テスト | `L` / `R` | `EMS:R` / `EMS:L` | 単発EMS（強度確認用） |
| 状態確認 | `?` | `STATUS` | 現在値を返信 |

`<id>`は正の整数（セッション内で単調増加）、`<led>`∈{R,G}、`<resp>`∈{R,L}、`<emsSide>`∈{R,L,N}（N=EMSなし）。

### Arduino → Unity

| 場面 | 返信フォーマット | 例 |
|---|---|---|
| トライアル完了 | `TRIAL_RESULT,<id>,<touchedSide>,<rtUs>,<peak>,<emsFired>` | `TRIAL_RESULT,12,R,243187,58,1` |
| トライアル無反応 | `TRIAL_RESULT,<id>,NONE,-1,0,<emsFired>` | `TRIAL_RESULT,12,NONE,-1,0,0` |
| EMSレイテンシ完了 | `EMSLAT_RESULT,<id>,<side>,<latencyUs>` | `EMSLAT_RESULT,4,R,52310` |
| EMSレイテンシ無反応 | `EMSLAT_RESULT,<id>,<side>,-1` | `EMSLAT_RESULT,4,L,-1` |
| コマンドACK | `OK:<cmd>` | `OK:THR:R:30` |
| 状態 | `STATUS:...` | |

> `<id>`は受信した TRIAL/EMSLAT の値をそのまま返す（必須）。`touchedSide`が`resp`と一致＝正答。`rtUs`/`latencyUs`は µs。Unityは ms(小数) に変換して記録。Arduinoは1つの TRIAL/EMSLAT につき結果を**ちょうど1行**返すこと（タッチ検出 or 自前タイムアウトで NONE）。

---

## 4. 実装ロードマップ（フェーズ＝独立に検証可能な単位）

- **Phase A（基盤・純粋ロジック）**：設定/統計/カウンターバランス/新enum。**追加のみ・既存コード非改変・全件単体テスト**。本書で詳細化。
- **Phase B（Arduino通信層）**：ArduinoLink双方向シリアル＋プロトコルパーサ。パーサは単体テスト、実機送受は手動検証。
- **Phase C（試行実行＋フェーズ進行）**：TrialEngine→TrialRunner改修、EMSPolicy式、Orchestifier新フェーズ列、条件駆動、Q10/安定性。
- **Phase D（データ記録＋出力）**：DataModels/DataLogger新列、median/gain出力、SubjectDataManager拡張。

各PhaseはPhase Aに依存（C/DはB/Aに依存）。Phase B〜Dは§7に確定タスク一覧を置き、着手時に本書と同じbite-sizedステップへ展開する。

---

## 5. Phase A 詳細（基盤・純粋ロジック）

> 方針：Phase Aは**新規ファイルの追加のみ**。既存enumの破壊的変更（PhaseType等）はPhase Cに集約し、ここでは行わない。例外として`UserAction`をCoreアセンブリへ移設するが、型名・名前空間（`ReactionTest.Experiment`）は不変のため既存参照はAuto Reference経由でそのままコンパイルできる。
> 実装開始前に作業ブランチを作成すること（mainに直接コミットしない）：`git checkout -b feat/fastestbaseline-migration`

### Task A1: Coreアセンブリ定義と enum 移設

**Files:**
- Create: `Assets/Scripts/Core/ReactionTest.Core.asmdef`
- Create: `Assets/Scripts/Core/CoreEnums.cs`
- Modify: `Assets/Scripts/Experiment/ExperimentTypes.cs`（`UserAction`定義を削除）

- [ ] **Step 1: asmdefを作成**

`Assets/Scripts/Core/ReactionTest.Core.asmdef`:
```json
{
    "name": "ReactionTest.Core",
    "rootNamespace": "ReactionTest.Experiment",
    "references": [],
    "includePlatforms": [],
    "excludePlatforms": [],
    "allowUnsafeCode": false,
    "overrideReferences": false,
    "autoReferenced": true,
    "defineConstraints": [],
    "noEngineReferences": false
}
```

- [ ] **Step 2: CoreEnums.cs を作成（UserActionを移設＋新enum追加）**

`Assets/Scripts/Core/CoreEnums.cs`:
```csharp
namespace ReactionTest.Experiment
{
    /// <summary>左/右/無入力。ターゲット側・応答側・EMSチャンネルの表現に共用。</summary>
    public enum UserAction
    {
        None,
        Left,
        Right
    }

    /// <summary>刺激色（2色LED）。</summary>
    public enum StimColor
    {
        Red,
        Green
    }

    /// <summary>実験条件（被験者内2条件）。</summary>
    public enum ExperimentCondition
    {
        EMS,
        Voluntary
    }

    /// <summary>条件提示順（別日カウンターバランス）。</summary>
    public enum ConditionOrder
    {
        EmsFirst,
        VoluntaryFirst
    }

    /// <summary>刺激-反応マッピング。RedRight=赤→右手/緑→左手。RedLeft=その逆。</summary>
    public enum SRMapping
    {
        RedRight,
        RedLeft
    }

    /// <summary>除外フラグ（生データは保持し、解析用に分類のみ記録）。</summary>
    public enum ExclusionFlag
    {
        Normal,
        Anticipation,
        Lapse
    }
}
```

- [ ] **Step 3: ExperimentTypes.cs から UserAction 定義を削除**

[ExperimentTypes.cs:50-59](../../Assets/Scripts/Experiment/ExperimentTypes.cs) の `UserAction` enum 定義（コメント含む）を削除する。他のenum（PhaseType等）はこのPhaseでは触らない。削除後、`UserAction`はCoreアセンブリ側で定義される。

- [ ] **Step 4: Unityでコンパイル確認**

UnityエディタでConsoleにコンパイルエラーが出ないことを確認（Assembly-CSharpがCoreをAuto Reference参照し`UserAction`が解決される）。
Expected: エラーなし。

- [ ] **Step 5: Commit**

```bash
git add Assets/Scripts/Core Assets/Scripts/Experiment/ExperimentTypes.cs
git commit -m "refactor: add Core assembly and move UserAction enum"
```

### Task A2: テストアセンブリの作成と疎通

**Files:**
- Create: `Assets/Tests/Editor/ReactionTest.Core.Tests.asmdef`
- Create: `Assets/Tests/Editor/SmokeTests.cs`

- [ ] **Step 1: テスト用asmdefを作成**

`Assets/Tests/Editor/ReactionTest.Core.Tests.asmdef`:
```json
{
    "name": "ReactionTest.Core.Tests",
    "rootNamespace": "ReactionTest.Experiment.Tests",
    "references": ["ReactionTest.Core"],
    "includePlatforms": ["Editor"],
    "excludePlatforms": [],
    "overrideReferences": true,
    "precompiledReferences": ["nunit.framework.dll"],
    "autoReferenced": false,
    "defineConstraints": ["UNITY_INCLUDE_TESTS"]
}
```

- [ ] **Step 2: スモークテストを作成**

`Assets/Tests/Editor/SmokeTests.cs`:
```csharp
using NUnit.Framework;
using ReactionTest.Experiment;

namespace ReactionTest.Experiment.Tests
{
    public class SmokeTests
    {
        [Test]
        public void UserAction_IsAccessibleFromCore()
        {
            Assert.AreNotEqual(UserAction.Left, UserAction.Right);
        }
    }
}
```

- [ ] **Step 3: Test Runnerで実行して合格を確認**

Unity: Window → General → Test Runner → EditMode → Run All。
Expected: `SmokeTests.UserAction_IsAccessibleFromCore` PASS。

- [ ] **Step 4: Commit**

```bash
git add Assets/Tests
git commit -m "test: add Core test assembly and smoke test"
```

### Task A3: RtStatistics（Q10/median/SD/除外）

**Files:**
- Create: `Assets/Scripts/Core/RtStatistics.cs`
- Test: `Assets/Tests/Editor/RtStatisticsTests.cs`

- [ ] **Step 1: 失敗するテストを書く**

`Assets/Tests/Editor/RtStatisticsTests.cs`:
```csharp
using System.Collections.Generic;
using NUnit.Framework;
using ReactionTest.Experiment;

namespace ReactionTest.Experiment.Tests
{
    public class RtStatisticsTests
    {
        [Test]
        public void Percentile_LinearInterpolation_Q10()
        {
            // 1..10 の Q10 は線形補間で index=0.9 → 1*0.1+2*0.9 = 1.9
            var data = new List<float> { 1,2,3,4,5,6,7,8,9,10 };
            Assert.AreEqual(1.9f, RtStatistics.Q10(data), 1e-4f);
        }

        [Test]
        public void Median_OddAndEven()
        {
            Assert.AreEqual(3f, RtStatistics.Median(new List<float>{1,2,3,4,5}), 1e-4f);
            Assert.AreEqual(2.5f, RtStatistics.Median(new List<float>{1,2,3,4}), 1e-4f);
        }

        [Test]
        public void SampleStdDev_KnownValue()
        {
            // {2,4,4,4,5,5,7,9} の標本SD = 2.138...
            var data = new List<float>{2,4,4,4,5,5,7,9};
            Assert.AreEqual(2.13809f, RtStatistics.SampleStdDev(data), 1e-3f);
        }

        [Test]
        public void Classify_AnticipationLapseNormal()
        {
            Assert.AreEqual(ExclusionFlag.Anticipation, RtStatistics.Classify(120f, 150f, 1000f, 0f));
            Assert.AreEqual(ExclusionFlag.Lapse,        RtStatistics.Classify(1200f, 150f, 1000f, 0f));
            Assert.AreEqual(ExclusionFlag.Normal,       RtStatistics.Classify(300f, 150f, 1000f, 0f));
        }

        [Test]
        public void Empty_ReturnsZero()
        {
            Assert.AreEqual(0f, RtStatistics.Q10(new List<float>()));
            Assert.AreEqual(0f, RtStatistics.Median(new List<float>()));
        }
    }
}
```

- [ ] **Step 2: テストを実行して失敗を確認**

Test Runner → EditMode → Run。
Expected: コンパイルエラー（`RtStatistics`未定義）。

- [ ] **Step 3: RtStatistics を実装**

`Assets/Scripts/Core/RtStatistics.cs`:
```csharp
using System;
using System.Collections.Generic;
using System.Linq;

namespace ReactionTest.Experiment
{
    /// <summary>RT分布の純粋統計ユーティリティ（UnityEngine非依存・テスト容易）。</summary>
    public static class RtStatistics
    {
        /// <summary>線形補間パーセンタイル（p: 0..1）。入力は非破壊（内部でソートコピー）。</summary>
        public static float Percentile(IEnumerable<float> values, float p)
        {
            var sorted = values.OrderBy(v => v).ToList();
            if (sorted.Count == 0) return 0f;
            if (sorted.Count == 1) return sorted[0];

            float index = p * (sorted.Count - 1);
            int lo = (int)Math.Floor(index);
            int hi = (int)Math.Ceiling(index);
            if (lo == hi) return sorted[lo];

            float frac = index - lo;
            return sorted[lo] * (1f - frac) + sorted[hi] * frac;
        }

        /// <summary>FastestBaseline = 正答RTの下位10パーセンタイル。</summary>
        public static float Q10(IEnumerable<float> correctRTs) => Percentile(correctRTs, 0.10f);

        public static float Median(IEnumerable<float> values) => Percentile(values, 0.50f);

        public static float Mean(IEnumerable<float> values)
        {
            var list = values.ToList();
            return list.Count == 0 ? 0f : list.Average();
        }

        /// <summary>標本標準偏差（n-1）。2件未満は0。</summary>
        public static float SampleStdDev(IEnumerable<float> values)
        {
            var list = values.ToList();
            if (list.Count < 2) return 0f;
            float mean = list.Average();
            double sumSq = list.Sum(v => (v - mean) * (double)(v - mean));
            return (float)Math.Sqrt(sumSq / (list.Count - 1));
        }

        /// <summary>
        /// 除外分類。生データは保持し、分類のみ返す。
        /// upperSdBound>0 のとき rt>upperSdBound も Lapse とみなす（個人内+3SD用。
        /// Unity記録時は 0 を渡して anticipation/&gt;lapseMax のみ判定し、+3SDはPython側で再計算）。
        /// </summary>
        public static ExclusionFlag Classify(float rtMs, float anticipationMs, float lapseMaxMs, float upperSdBound)
        {
            if (rtMs < anticipationMs) return ExclusionFlag.Anticipation;
            if (rtMs > lapseMaxMs) return ExclusionFlag.Lapse;
            if (upperSdBound > 0f && rtMs > upperSdBound) return ExclusionFlag.Lapse;
            return ExclusionFlag.Normal;
        }
    }
}
```

- [ ] **Step 4: テストを実行して合格を確認**

Test Runner → EditMode → Run。
Expected: RtStatisticsTests 全件 PASS。

- [ ] **Step 5: Commit**

```bash
git add Assets/Scripts/Core/RtStatistics.cs Assets/Tests/Editor/RtStatisticsTests.cs
git commit -m "feat: add RtStatistics (Q10/median/sd/exclusion) with tests"
```

### Task A4: Counterbalance（順序・マッピング・条件・正解手）

**Files:**
- Create: `Assets/Scripts/Core/Counterbalance.cs`
- Test: `Assets/Tests/Editor/CounterbalanceTests.cs`

- [ ] **Step 1: 失敗するテストを書く**

`Assets/Tests/Editor/CounterbalanceTests.cs`:
```csharp
using NUnit.Framework;
using ReactionTest.Experiment;

namespace ReactionTest.Experiment.Tests
{
    public class CounterbalanceTests
    {
        [Test]
        public void OrderAndMapping_From2x2Index()
        {
            // index 0..3 で 順序×マッピング の4群を巡回
            Assert.AreEqual(ConditionOrder.EmsFirst,        Counterbalance.OrderFor(0));
            Assert.AreEqual(ConditionOrder.VoluntaryFirst,  Counterbalance.OrderFor(1));
            Assert.AreEqual(SRMapping.RedRight,             Counterbalance.MappingFor(0));
            Assert.AreEqual(SRMapping.RedRight,             Counterbalance.MappingFor(1));
            Assert.AreEqual(SRMapping.RedLeft,              Counterbalance.MappingFor(2));
        }

        [Test]
        public void ConditionForSession_RespectsOrder()
        {
            Assert.AreEqual(ExperimentCondition.EMS,
                Counterbalance.ConditionForSession(ConditionOrder.EmsFirst, 1));
            Assert.AreEqual(ExperimentCondition.Voluntary,
                Counterbalance.ConditionForSession(ConditionOrder.EmsFirst, 2));
            Assert.AreEqual(ExperimentCondition.Voluntary,
                Counterbalance.ConditionForSession(ConditionOrder.VoluntaryFirst, 1));
        }

        [Test]
        public void CorrectHand_RespectsMapping()
        {
            Assert.AreEqual(UserAction.Right, Counterbalance.CorrectHand(StimColor.Red,   SRMapping.RedRight));
            Assert.AreEqual(UserAction.Left,  Counterbalance.CorrectHand(StimColor.Green, SRMapping.RedRight));
            Assert.AreEqual(UserAction.Left,  Counterbalance.CorrectHand(StimColor.Red,   SRMapping.RedLeft));
            Assert.AreEqual(UserAction.Right, Counterbalance.CorrectHand(StimColor.Green, SRMapping.RedLeft));
        }
    }
}
```

- [ ] **Step 2: テストを実行して失敗を確認**

Expected: コンパイルエラー（`Counterbalance`未定義）。

- [ ] **Step 3: Counterbalance を実装**

`Assets/Scripts/Core/Counterbalance.cs`:
```csharp
namespace ReactionTest.Experiment
{
    /// <summary>被験者番号からの2×2カウンターバランス割当と、色→正解手の写像（純粋関数）。</summary>
    public static class Counterbalance
    {
        /// <summary>条件提示順：被験者indexの偶奇で割当。</summary>
        public static ConditionOrder OrderFor(int subjectIndex)
            => (subjectIndex % 2 == 0) ? ConditionOrder.EmsFirst : ConditionOrder.VoluntaryFirst;

        /// <summary>S-Rマッピング：2件ごとに反転（順序と直交）。</summary>
        public static SRMapping MappingFor(int subjectIndex)
            => ((subjectIndex / 2) % 2 == 0) ? SRMapping.RedRight : SRMapping.RedLeft;

        /// <summary>セッション番号(1 or 2)→条件。</summary>
        public static ExperimentCondition ConditionForSession(ConditionOrder order, int sessionNumber)
        {
            bool first = sessionNumber <= 1;
            if (order == ConditionOrder.EmsFirst)
                return first ? ExperimentCondition.EMS : ExperimentCondition.Voluntary;
            return first ? ExperimentCondition.Voluntary : ExperimentCondition.EMS;
        }

        /// <summary>刺激色とマッピングから正解の手を返す。</summary>
        public static UserAction CorrectHand(StimColor color, SRMapping mapping)
        {
            bool redRight = (mapping == SRMapping.RedRight);
            if (color == StimColor.Red)   return redRight ? UserAction.Right : UserAction.Left;
            return redRight ? UserAction.Left : UserAction.Right; // Green
        }
    }
}
```

- [ ] **Step 4: テストを実行して合格を確認**

Expected: CounterbalanceTests 全件 PASS。

- [ ] **Step 5: Commit**

```bash
git add Assets/Scripts/Core/Counterbalance.cs Assets/Tests/Editor/CounterbalanceTests.cs
git commit -m "feat: add Counterbalance assignment logic with tests"
```

### Task A5: ExperimentConfig（設定ファイル）

**Files:**
- Create: `Assets/Scripts/Core/ExperimentConfig.cs`
- Test: `Assets/Tests/Editor/ExperimentConfigTests.cs`

- [ ] **Step 1: 失敗するテストを書く**

`Assets/Tests/Editor/ExperimentConfigTests.cs`:
```csharp
using System.IO;
using NUnit.Framework;
using ReactionTest.Experiment;

namespace ReactionTest.Experiment.Tests
{
    public class ExperimentConfigTests
    {
        [Test]
        public void LoadOrCreate_CreatesDefaultWhenMissing()
        {
            string path = Path.Combine(Path.GetTempPath(), "ec_" + Path.GetRandomFileName() + ".json");
            try
            {
                var cfg = ExperimentConfig.LoadOrCreate(path);
                Assert.IsTrue(File.Exists(path));
                Assert.AreEqual(80, cfg.PreTrials);
                Assert.AreEqual(0f, cfg.EmsOffsetMs);
                Assert.AreEqual(4f, cfg.EmsToTouchStabilitySdMs);
            }
            finally { if (File.Exists(path)) File.Delete(path); }
        }

        [Test]
        public void LoadOrCreate_ReadsExistingValues()
        {
            string path = Path.Combine(Path.GetTempPath(), "ec_" + Path.GetRandomFileName() + ".json");
            try
            {
                File.WriteAllText(path, "{\"PreTrials\":40,\"EmsOffsetMs\":40.0}");
                var cfg = ExperimentConfig.LoadOrCreate(path);
                Assert.AreEqual(40, cfg.PreTrials);
                Assert.AreEqual(40f, cfg.EmsOffsetMs);
            }
            finally { if (File.Exists(path)) File.Delete(path); }
        }
    }
}
```

- [ ] **Step 2: テストを実行して失敗を確認**

Expected: コンパイルエラー（`ExperimentConfig`未定義）。

- [ ] **Step 3: ExperimentConfig を実装**

`Assets/Scripts/Core/ExperimentConfig.cs`:
```csharp
using System;
using System.IO;
using UnityEngine;

namespace ReactionTest.Experiment
{
    /// <summary>
    /// 事前/本実験で差し替え可能な実験設定。projectRoot/experiment_config.json に保存。
    /// JsonUtility互換のためpublicフィールドのみ。
    /// </summary>
    [Serializable]
    public class ExperimentConfig
    {
        // 試行数
        public int PreTrials = 80;
        public int EmsLatencyTrials = 30;
        public int TrainingTrials = 60;
        public int PostTrials = 80;

        // EMSタイミング
        public float EmsOffsetMs = 0f;   // 0=FastestBaseline, >0=agency_EMS

        // ITI / 前置時間（秒）
        public float ItiMinSec = 2.0f;
        public float ItiMaxSec = 3.0f;

        // 固定タッチ閾値（手動BASELINEで調整した値）
        public int TouchThresholdRight = 30;
        public int TouchThresholdLeft = 30;

        // EMS波形（強度）
        public int EmsPulseWidthUs = 50;
        public int EmsPulseCount = 1;
        public int EmsBurstCount = 3;
        public int EmsPulseIntervalUs = 40000;

        // 除外基準（Unity記録時はanticipation/lapseMaxのみ。+3SDはPython側）
        public float RtAnticipationMs = 150f;
        public float RtLapseMaxMs = 1000f;
        public float LapseSdMultiplier = 3f;

        // EMS_to_Touch 安定性（標本SDがこの値未満なら安定）
        public float EmsToTouchStabilitySdMs = 4f;

        // 応答タイムアウト（ms）
        public float ResponseTimeoutMs = 2000f;

        public static ExperimentConfig LoadOrCreate(string path)
        {
            if (File.Exists(path))
            {
                string json = File.ReadAllText(path);
                var cfg = JsonUtility.FromJson<ExperimentConfig>(json);
                if (cfg != null) return cfg;
            }
            var def = new ExperimentConfig();
            File.WriteAllText(path, JsonUtility.ToJson(def, true));
            return def;
        }
    }
}
```

- [ ] **Step 4: テストを実行して合格を確認**

Expected: ExperimentConfigTests 全件 PASS。

- [ ] **Step 5: Commit**

```bash
git add Assets/Scripts/Core/ExperimentConfig.cs Assets/Tests/Editor/ExperimentConfigTests.cs
git commit -m "feat: add ExperimentConfig with JSON load/create and tests"
```

### Phase A 完了条件
- EditModeテスト全件PASS（RtStatistics / Counterbalance / ExperimentConfig / Smoke）。
- Unity Consoleにコンパイルエラーなし。既存シーン・既存実験フローは従来どおり起動可能（破壊的変更なし）。

---

## 6. Phase A セルフレビュー結果

- **仕様カバレッジ**：Q10（A3）、median/SD（A3）、除外フラグ（A3）、カウンターバランス＝条件順序/S-Rマッピング/セッション条件/正解手（A4）、設定ファイルの試行数・offset・ITI・閾値・除外・安定性（A5）。Phase Aスコープ内の純粋ロジックを網羅。
- **プレースホルダ走査**：TBD/TODO/「適宜」等なし。各実装ステップに完全なコードを記載。
- **型整合**：`UserAction`（A1）をA4が使用、enum名（StimColor/ExperimentCondition/ConditionOrder/SRMapping/ExclusionFlag）はA1定義をA3/A4/A5が参照。メソッド名 `Q10`/`Median`/`SampleStdDev`/`Classify`/`OrderFor`/`MappingFor`/`ConditionForSession`/`CorrectHand`/`LoadOrCreate` はテストと実装で一致。

---

## 7. Phase B〜D 確定タスク一覧（着手時にbite-sized展開）

### Phase B：Arduino通信層
- **B1 ArduinoLink（双方向シリアル）**：`Assets/Scripts/Experiment/ArduinoLink.cs` 新規。TXキュー＋RX受信スレッド＋行単位パース。受信行を `ConcurrentQueue` に積み、メインスレッドの `Update()` でディスパッチ。接続失敗時はシミュレーションモード（ログのみ）。
- **B2 プロトコルパーサ（純粋・テスト可）**：`ParseTrialResult(string) → TrialResult` / `ParseEmsLatResult(string) → (side, latencyUs)` をstaticに切り出しCoreでテスト。`TRIAL_RESULT,R,243187,58,1` / `NONE,-1` を正しく分解。µs→ms変換。
- **B3 コマンド送信API**：`SendTrial(led, resp, emsSide, emsDelayUs)` / `SendEmsLatency(side)` / `SendThreshold(side, value)` / `SendEmsConfig(...)` / `LedOff()` / `Reset()`。§3の文字列を生成。
- **B4 EMSController再編**：SerialPort直接所有を撤廃しArduinoLink依存へ。不応期/最大発火/緊急停止/強度設定を維持。
- **B5 実機手動検証**：`STATUS`往復、`EMS:R/L`単発、`TRIAL`1試行のRT受信をConsoleで確認。

### Phase C：試行実行＋フェーズ進行
- **C1 PhaseType再定義**：`Pre/EMSLatency/Training1/Post1/Training2/Post2/Test`。`GroupType`撤廃→`ExperimentCondition`。
- **C2 EMSPolicy改修**：`ComputeFireTimingMs(q10Side, offsetMs, emsToTouchSide)` と条件ゲート（Voluntaryは発火なし）。テスト：式が `q10−offset−emsToTouch` を返す/Voluntaryで無効。
- **C3 TrialRunner（旧TrialEngine）**：画面刺激＋マウス撤廃。`RunTrial(stimColor, correctHand, emsSide, emsDelayUs)` が ArduinoLink へ指令→`TRIAL_RESULT`待ち→採点（touched==correctHand）→RTモニタ表示→Esc中断。ITI/前置時間はUnityでWait。
- **C4 EMSLatencyフェーズ**：`EMSLAT,<side>` を左右各n試行→µs受信→IQRまたは平均でEMS_to_Touch(左右別)。**安定性チェック**：標本SD≥`EmsToTouchStabilitySdMs`なら警告＋再calib（最大再試行回数ガード）。強度調整コマンド送信。
- **C5 Orchestrator新フェーズ列**：Pre→EMSLatency→Training1→Post1→（休憩UI）→Training2→Post2。Pre後にQ10(左右別)算出（RtStatistics）。Trainingは条件・offsetでEMS指令。Percentile自前実装を撤去。
- **C6 条件解決**：起動時にSubjectDataManagerからこのセッションの`ExperimentCondition`・`SRMapping`を取得し全試行へ反映。

### Phase D：データ記録＋出力
- **D1 DataModels拡張**：TrialRecordに `Condition, SessionDate, StimColor, CorrectHand, ExclusionFlag, EmsFired, EmsToTouchMs, StimOnsetTimestamp` を追加（生RTは維持）。`AgencyOffsetConfig`→`CalibrationData`へ改名し`Q10Left/Right, EmsToTouchLeft/Right, ThresholdL/R`を保持。SessionMetaに`Condition/SessionDate/SRMapping`。
- **D2 DataLogger新CSV**：ヘッダを §「記録すべきデータ項目」に合わせ拡張。FormatTrialLineを更新（RFC4180エスケープ流用）。
- **D3 median/gain出力**：フェーズ別に正答median RTを算出し、`gain = (median(Post1)+median(Post2))/2 − median(Pre)` をセッションサマリJSON/ログへ出力。RtStatistics利用。
- **D4 SubjectDataManager拡張**：新規被験者作成時に被験者indexからOrder/Mapping割当・保存。セッション→条件解決。Q10/EMS_to_Touch/閾値の保存・読込。
- **D5 除外フラグ記録**：記録時に `RtStatistics.Classify(rt, anticipation, lapseMax, 0)` を付与（+3SDはPython側）。

---

## 8. リスク・留意点
- **Arduino側プロトコル整合**：§3はUnity側の契約。Arduino実装担当と本表を共有し齟齬がないか着手前に確認。
- **タッチ固定閾値**：装置調整時に手動`BASELINE`で適正値を求め設定ファイルへ。日差ドリフトに注意。
- **RT精度**：Arduinoは`micros()`化前提。Unityはµs受信→小数ms記録。
- **シーン参照**：TrialEngine→TrialRunner改名時、シーンの参照（SerializeField）再割当が必要になりうる。クラス名据え置きも選択肢（Phase C着手時に判断）。
- **既存解析資産**：median/gain/+3SDは [Analysis/](../../Analysis/)・[hddm_sim/](../../hddm_sim/) と整合させる。
