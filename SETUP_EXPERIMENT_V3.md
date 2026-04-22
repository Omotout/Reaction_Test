# Experiment V3 セットアップ手順

## 1. スクリプト一覧

| ファイル | 説明 |
|----------|------|
| `Assets/Scripts/Experiment/ExperimentTypes.cs` | Enum定義（GroupType, PhaseType, UserAction, ErrorType, EMSDecision） |
| `Assets/Scripts/Experiment/DataModels.cs` | データモデル（SessionMeta, TrialRecord, AgencyOffsetConfig） |
| `Assets/Scripts/Experiment/TaskRule.cs` | CRT正解判定・ターゲット側ランダム選択 |
| `Assets/Scripts/Experiment/EMSPolicy.cs` | EMS発火タイミング計算 |
| `Assets/Scripts/Experiment/EMSController.cs` | Arduino DUE + L298N シリアル通信・安全機構 |
| `Assets/Scripts/Experiment/TrialEngine.cs` | 1試行の制御（CRT + EMSLatency） |
| `Assets/Scripts/Experiment/StaircaseCalibrator.cs` | 適応的インターリーブ階段法 |
| `Assets/Scripts/Experiment/AgencySurveyUI.cs` | 7段階リッカートUI |
| `Assets/Scripts/Experiment/DataLogger.cs` | CSV出力（メモリバッファ方式） |
| `Assets/Scripts/Experiment/SubjectDataManager.cs` | 被験者データ管理 |
| `Assets/Scripts/Experiment/PhaseTransitionUI.cs` | フェーズ間案内表示 |
| `Assets/Scripts/Experiment/ExperimentOrchestrator.cs` | 6フェーズ連続実行・メインコントローラ |

## 2. Arduinoセットアップ

1. Arduino DUE + L298N (H-Bridge) を接続
2. `Arduino_ReactionTest_EMS.ino` を Arduino IDE で開く
3. Arduino DUE にアップロード
4. シリアルポート名を確認（例: COM5）

### ピン接続

| Arduino | L298N | 用途 |
|---------|-------|------|
| D3 | IN1 | 左チャンネル A |
| D4 | IN2 | 左チャンネル B |
| D5 | IN3 | 右チャンネル A |
| D6 | IN4 | 右チャンネル B |

### EMSパラメータ

| パラメータ | 範囲 | デフォルト | 説明 |
|-----------|------|-----------|------|
| PulseWidth | 20–1000 µs | 50 | パルス幅 |
| PulseCount | 1–100 | 1 | 繰り返し回数 |
| BurstCount | 1–20 | 3 | 2相性サイクル数 |
| PulseInterval | 0–100000 µs | 40000 | パルス間隔 |

### Arduinoコマンド仕様

| コマンド | 説明 |
|---------|------|
| `L` | 左チャンネル発火（撓屈） |
| `R` | 右チャンネル発火（尺屈） |
| `Wnn` | パルス幅設定 (20–1000 µs) |
| `Cnn` | パルス連射回数 (1–100) |
| `Bnn` | バーストサイクル数 (1–20) |
| `Innnn` | パルス間隔 (0–100000 µs) |

## 3. シーン構築

### Step 1: Canvas作成
1. Hierarchy で右クリック → **UI → Canvas**
2. Canvas を選択し、Inspector で:
   - Render Mode: **Screen Space - Overlay**
   - UI Scale Mode: **Scale With Screen Size**
   - Reference Resolution: **1920 x 1080**

### Step 2: 刺激表示用 Image（中央）
1. Canvas を右クリック → **UI → Image**
2. 名前を **StimulusImage** に変更
3. RectTransform 設定:
   - Anchor: **Middle Center**
   - Pos X: 0, Pos Y: 0
   - Width: **200**, Height: **200**
4. Image コンポーネント:
   - Color: 緑 (0, 255, 0) ※初期色
5. **最初は非表示にする**: Inspector 上部のチェックボックスを OFF

### Step 3: フィードバックText作成
1. Canvas を右クリック → **UI → Text** → 名前を **FeedbackText** に変更
2. RectTransform: PosY=-100, Width=200, Height=60
3. Font Size: 36
4. Alignment: Center-Middle
5. Color: 白
6. **最初は非表示にする**: Inspector 上部のチェックボックスを OFF

### Step 4: PhaseTransitionPanel 作成
1. Canvas を右クリック → **Create Empty** → 名前を **PhaseTransitionPanel** に変更
2. RectTransform:
   - Anchor: Stretch-Stretch（四隅ドラッグで全画面）
   - Left/Right/Top/Bottom: 0
3. **Add Component** → **Canvas Group** を追加
4. **Add Component** → **Image** を追加（背景用、Color: 黒 50%透明）

5. PhaseTransitionPanel を右クリック → **UI → Text** → 名前を **PhaseNameText** に変更
   - RectTransform: PosY=100, Width=800, Height=80
   - Font Size: 48
   - Alignment: Center-Middle
   - Color: 白

6. PhaseTransitionPanel を右クリック → **UI → Text** → 名前を **InstructionText** に変更
   - RectTransform: PosY=0, Width=800, Height=200
   - Font Size: 24
   - Alignment: Center-Middle
   - Color: 白

7. PhaseTransitionPanel を右クリック → **UI → Text** → 名前を **PressSpaceText** に変更
   - RectTransform: PosY=-150, Width=400, Height=50
   - Font Size: 20
   - Alignment: Center-Middle
   - Color: 黄色

### Step 5: AgencySurveyPanel 作成
1. Canvas を右クリック → **UI → Panel**
2. 名前を **AgencySurveyPanel** に変更
3. RectTransform 設定:
   - Anchor: **Stretch - Stretch**（四隅を親に合わせる）
   - Left/Right/Top/Bottom: すべて 0
4. Image コンポーネント:
   - Color: 半透明黒 (0, 0, 0, 200)
5. **CanvasGroup を追加**: Add Component → CanvasGroup

6. AgencySurveyPanel を右クリック → **UI → Text**（TextMeshProではない方）
   - 名前を **PromptText** に変更
   - RectTransform: Anchor=Top Center, PosY=-100, Width=800, Height=100
   - Text: 「自分でボタンを押した感覚がありましたか？」
   - Font Size: 36, Alignment: Center+Middle, Color: 白
7. AgencySurveyPanel を右クリック → **UI → Button** → 名前を **NoButton** に変更
   - RectTransform: Anchor=Middle Center, PosX=-200, PosY=0, Width=250, Height=80
   - 子の Text: 「いいえ (勝手に動いた)」
8. AgencySurveyPanel を右クリック → **UI → Button** → 名前を **YesButton** に変更
   - RectTransform: Anchor=Middle Center, PosX=200, PosY=0, Width=250, Height=80
   - 子の Text: 「はい (自分で押した)」

### 最終的なHierarchy構造
```
Main Camera
Directional Light
EventSystem              ← Canvas作成時に自動生成
Canvas
├── StimulusImage        ← TrialEngine.stimulusImage
├── FeedbackText         ← TrialEngine.feedbackText
├── PhaseTransitionPanel ← PhaseTransitionUI (CanvasGroup付き)
│   ├── PhaseNameText    ← PhaseTransitionUI.phaseNameText
│   ├── InstructionText  ← PhaseTransitionUI.instructionText
│   └── PressSpaceText   ← PhaseTransitionUI.pressSpaceText
└── AgencySurveyPanel    ← AgencySurveyUI (CanvasGroup付き)
    ├── PromptText       ← AgencySurveyUI.promptText
    ├── NoButton         ← AgencySurveyUI.noButton
    └── YesButton        ← AgencySurveyUI.yesButton
ExperimentOrchestrator
TrialEngine
DataLogger
EMSController
SubjectDataManager
```

## 4. コンポーネント割当

### Step 1: 空のGameObject作成
Hierarchy で右クリック → **Create Empty** で以下を作成:
- **ExperimentOrchestrator**
- **TrialEngine**
- **DataLogger**
- **EMSController**
- **SubjectDataManager**

### Step 2: EMSController の設定
1. Hierarchy で **EMSController** を選択
2. Inspector で **Add Component** → **EMSController** を追加
3. パラメータを設定:

| 項目 | 値 | 説明 |
|------|-----|------|
| Port Name | COM5 | Arduinoのポート（デバイスマネージャーで確認） |
| Baud Rate | 9600 | そのまま |
| EMS Enabled | ✓ | チェックを入れる |
| Pulse Width | 50 | パルス幅（µs） |
| Pulse Count | 1 | 連射回数 |
| Burst Count | 3 | 2相性サイクル数 |
| Pulse Interval | 40000 | パルス間隔（µs） |
| Refractory Period Ms | 200 | 連続発火の最小間隔（ms） |
| Max Fires Per Session | 500 | 1セッションの最大発火回数 |

### Step 3: TrialEngine の設定
1. Hierarchy で **TrialEngine** を選択
2. Inspector で **Add Component** → **TrialEngine** を追加
3. 参照を設定:

| 項目 | 設定方法 |
|------|----------|
| Stimulus Image | Hierarchy の **StimulusImage** をドラッグ |
| Left Color | 緑 (0, 255, 0) |
| Right Color | 赤 (255, 0, 0) |
| Feedback Text | Hierarchy の **FeedbackText** をドラッグ |
| Show Reaction Time Feedback | ✓ (ON) |
| Feedback Duration Sec | 0.8 |
| EMS Controller | Hierarchy の **EMSController** をドラッグ |

4. フェーズ別試行数（Inspector で変更可）:

| 項目 | デフォルト値 |
|------|-------------|
| Practice Trials | 15 |
| Baseline Trials | 40 |
| EMS Latency Trials Per Side | 15 |
| Training Trials | 40 |
| Post Test Trials | 40 |

### Step 4: DataLogger の設定
1. Hierarchy で **DataLogger** を選択
2. Inspector で **Add Component** → **DataLogger** を追加
3. パラメータ:

| 項目 | デフォルト値 | 説明 |
|------|-------------|------|
| Trial File Name | trial_log.csv | 出力CSV名 |
| Auto Flush Interval | 10 | N試行ごとに自動Flush（0で無効） |

### Step 5: PhaseTransitionUI の設定
1. Hierarchy で **PhaseTransitionPanel** を選択
2. Inspector で **Add Component** → **PhaseTransitionUI** を追加
3. 参照を設定:

| 項目 | 設定方法 |
|------|----------|
| Root | PhaseTransitionPanel 自身（CanvasGroup付き） |
| Phase Name Text | **PhaseNameText** をドラッグ |
| Instruction Text | **InstructionText** をドラッグ |
| Press Space Text | **PressSpaceText** をドラッグ |

### Step 6: AgencySurveyUI の設定
1. Hierarchy で **AgencySurveyPanel** を選択
2. Inspector で **Add Component** → **AgencySurveyUI** を追加
3. 参照を設定:

| 項目 | 設定 |
|------|------|
| Root | AgencySurveyPanel 自身（CanvasGroup付き） |
| Yes Button | **YesButton** をドラッグ |
| No Button | **NoButton** をドラッグ |
| Prompt Text | **PromptText** をドラッグ |

### Step 7: SubjectDataManager の設定
1. Hierarchy で **SubjectDataManager** を選択
2. Inspector で **Add Component** → **SubjectDataManager** を追加
3. デフォルト設定のままでOK（Data Folder Name: ExperimentData）

### Step 8: ExperimentOrchestrator の設定
1. Hierarchy で **ExperimentOrchestrator** を選択
2. Inspector で **Add Component** → **ExperimentOrchestrator** を追加
3. 参照を設定:

| 項目 | 設定方法 |
|------|----------|
| Trial Engine | Hierarchy の **TrialEngine** をドラッグ |
| Agency Survey UI | Hierarchy の **AgencySurveyPanel** をドラッグ |
| Data Logger | Hierarchy の **DataLogger** をドラッグ |
| Subject Data Manager | Hierarchy の **SubjectDataManager** をドラッグ |
| Phase Transition UI | Hierarchy の **PhaseTransitionPanel** をドラッグ |
| EMS Controller | Hierarchy の **EMSController** をドラッグ |

4. 実験パラメータを設定:

| 項目 | 値 | 説明 |
|------|-----|------|
| Subject Id | P001 | 被験者ID（実験ごとに変更） |
| Group Type | AgencyEMS | AgencyEMS または Voluntary |
| Max Calibration Trials | 80 | キャリブレーションの最大試行数 |

## 5. 動作テスト

1. **Ctrl+S** でシーンを保存
2. **Play** ボタンを押す
3. Console に以下が表示されれば成功:
   - `TrialEngine: Display XXHz → Target FPS: XXX`
   - `SubjectDataManager: Data root = ...`
   - `Created new subject: P001` または `Loaded subject data: P001`
   - `EMS Controller: Serial port COMX connected`（Arduino接続時）
   - または `EMS Controller: Arduino not connected (simulation mode)`（未接続時）
   - `DataLogger: Output directory = ...`
4. フェーズ移行画面が表示され、スペースキーで進行できることを確認
5. 刺激が表示され、クリックで反応時間が記録されることを確認
6. Calibration で Agency評価UI が表示され、ボタンクリックで次に進むことを確認
7. Esc キーで緊急停止できることを確認

## 6. 実験運用手順

### データ管理構造
被験者データはプロジェクトルート直下に自動管理されます：
```
<プロジェクトルート>/ExperimentData/
├── P001/
│   ├── config.json                       ← 被験者設定（群・キャリブレーション結果）
│   ├── session_01_20260422_100000/
│   │   ├── session_info.json
│   │   └── trial_log.csv
│   └── session_02_20260422_140000/
│       └── ...
└── P002/
    └── ...
```

### 実験実行
1. ExperimentOrchestrator の **Subject Id** を入力（例: P001）
2. **Group Type** を設定（AgencyEMS / Voluntary）
3. **Play** を押す
4. 6フェーズが自動的に連続実行される:
   Practice → Baseline → EMSLatency → Calibration → Training → PostTest
5. 終了後、Console にログ出力先が表示される

> **注意**: 同じ Subject Id の既存被験者は、保存済みの Group が優先されます。
> Group を変更したい場合は被験者フォルダを削除またはリネームしてください。

### 再実行
同じ Subject Id で再実行すると、新しいセッション（session_02_... など）が作成されます。
既存のキャリブレーションデータがあれば自動的に読み込まれます。

### 解析
```bash
# 依存パッケージの導入
cd Analysis
pip install -r requirements.txt

# 解析の実行
python analyze_training_effect.py \
  --data_dir ../ExperimentData \
  --outdir results \
  [--skip_hddm]    # HDDM解析をスキップ（高速化）
  [--min_rt 100]    # 最小有効RT（ms）
  [--max_rt 1000]   # 最大有効RT（ms）
```

出力ファイル:
- `rt_gains.csv` — 被験者別RT Gain
- `descriptive_stats.csv` — 記述統計
- `analysis_results.json` — 全結果
- `rt_gain_boxplot.png` — RT Gain 箱ひげ図
- `rt_pre_post.png` — Pre/Post ペアプロット
- `rt_distribution_*.png` — RT分布ヒストグラム（正答/誤答別）
- `rt_overlay_*.png` — Baseline vs PostTest 重ね合わせ
- `calibration_staircase_*.png` — 階段法プロット（被験者別）
- `calibration_psychometric.png` — 心理測定関数プロット
- `hddm_summary.csv` / `hddm_trace.png` — HDDM解析結果（実行時のみ）

## 7. 注意点
- EMSController が未接続の場合、シミュレーションモードで動作（Debug.Logのみ）
- GroupType が Voluntary の場合は EMS 無効
- EMS発火タイミング = BaselineRT(side) − EMSOffset − EMSLatency(side)（左右別）
- Arduino側で500ms未満の連打は安全装置により無視される
- **高精度タイミング**: Stopwatch による計測、VSync OFF、targetFrameRate = リフレッシュレート × 2

## 8. EMSキャリブレーション（手動テスト）
EMSController の `Test Trigger Left` / `Test Trigger Right` をチェックすると、手動でEMS発火テストが可能。
刺激強度の調整は Arduino_ReactionTest_EMS.ino のパラメータまたは Unity インスペクタで行う。
