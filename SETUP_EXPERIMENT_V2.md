# Experiment V2 セットアップ手順

## 1. 追加済みスクリプト
- Assets/Scripts/Experiment/ExperimentTypes.cs
- Assets/Scripts/Experiment/DataModels.cs
- Assets/Scripts/Experiment/TaskRule.cs
- Assets/Scripts/Experiment/EMSPolicy.cs
- Assets/Scripts/Experiment/EMSController.cs  ← NEW
- Assets/Scripts/Experiment/TrialEngine.cs
- Assets/Scripts/Experiment/AgencySurveyUI.cs
- Assets/Scripts/Experiment/DataLogger.cs
- Assets/Scripts/Experiment/ExperimentOrchestrator.cs

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
| PulseWidth | 20-1000 µs | 50 | パルス幅 |
| PulseCount | 1-100 | 1 | 繰り返し回数 |
| BurstCount | 1-20 | 3 | 2相性サイクル数 |
| PulseInterval | 0-100000 µs | 40000 | パルス間隔 |

## 3. シーン構築
1. SampleScene を開く
2. 空の GameObject を4つ作成
   - ExperimentOrchestrator
   - TrialEngine
   - DataLogger
   - EMSController  ← NEW

### Canvas UI構築（詳細手順）

#### Step 1: Canvas作成
1. Hierarchy で右クリック → **UI → Canvas**
2. Canvas を選択し、Inspector で:
   - Render Mode: **Screen Space - Overlay**
   - UI Scale Mode: **Scale With Screen Size**
   - Reference Resolution: **1920 x 1080**

#### Step 2: 刺激表示用 Image（中央）
1. Canvas を右クリック → **UI → Image**
2. 名前を **StimulusImage** に変更
3. RectTransform 設定:
   - Anchor: **Middle Center**
   - Pos X: 0, Pos Y: 0
   - Width: **200**, Height: **200**
4. Image コンポーネント:
   - Color: 緑 (0, 255, 0) ※初期色
5. **最初は非表示にする**: Inspector 上部のチェックボックスを OFF

#### Step 3: AgencySurveyUI用のPanel作成
1. Canvas を右クリック → **UI → Panel**
2. 名前を **AgencySurveyPanel** に変更
3. RectTransform 設定:
   - Anchor: **Stretch - Stretch**（四隅を親に合わせる）
   - Left/Right/Top/Bottom: すべて 0
4. Image コンポーネント:
   - Color: 半透明黒 (0, 0, 0, 200)
5. **CanvasGroup を追加**: Add Component → CanvasGroup

#### Step 4: 質問文 Text
1. AgencySurveyPanel を右クリック → **UI → Text**（TextMeshProではない方）
2. 名前を **PromptText** に変更
3. RectTransform 設定:
   - Anchor: **Top Center**
   - Pos Y: **-100**
   - Width: **800**, Height: **100**
4. Text 設定:
   - Text: 「主体感はどの程度ありましたか？」
   - Font Size: **36**
   - Alignment: **Center + Middle**
   - Color: 白

#### Step 5: リッカートボタン（1〜7）
1. AgencySurveyPanel を右クリック → **UI → Button**
2. 名前を **LikertButton1** に変更
3. RectTransform 設定:
   - Anchor: **Middle Center**
   - Pos X: **-300**, Pos Y: **0**
   - Width: **80**, Height: **80**
4. 子の Text を選択し、Text を **1** に変更、Font Size: **32**
5. **ボタン1を複製**: Ctrl+D で6回複製
6. 各ボタンの設定:

| ボタン名 | Pos X | Text |
|----------|-------|------|
| LikertButton1 | -300 | 1 |
| LikertButton2 | -200 | 2 |
| LikertButton3 | -100 | 3 |
| LikertButton4 | 0 | 4 |
| LikertButton5 | 100 | 5 |
| LikertButton6 | 200 | 6 |
| LikertButton7 | 300 | 7 |

#### Step 6: AgencySurveyUI スクリプトのアタッチ
1. AgencySurveyPanel を選択
2. Add Component → **AgencySurveyUI**
3. Inspector で参照を設定:
   - Root: **AgencySurveyPanel** (自身の CanvasGroup)
   - Likert Buttons: サイズを **7** に設定し、LikertButton1〜7 を順番にドラッグ
   - Prompt Text: **PromptText** をドラッグ

#### 最終的なHierarchy構造
```
Canvas
├── StimulusImage          ← TrialEngine.stimulusImage
├── FeedbackText           ← TrialEngine.feedbackText (反応時間表示用)
├── PhaseTransitionPanel   ← PhaseTransitionUI.root (CanvasGroup付き)
│   ├── PhaseNameText      ← PhaseTransitionUI.phaseNameText
│   ├── InstructionText    ← PhaseTransitionUI.instructionText
│   └── PressSpaceText     ← PhaseTransitionUI.pressSpaceText
└── AgencySurveyPanel      ← AgencySurveyUI.root (CanvasGroup付き)
    ├── PromptText         ← AgencySurveyUI.promptText
    ├── LikertButton1      ← AgencySurveyUI.likertButtons[0]
    ├── LikertButton2      ← AgencySurveyUI.likertButtons[1]
    ├── LikertButton3      ← AgencySurveyUI.likertButtons[2]
    ├── LikertButton4      ← AgencySurveyUI.likertButtons[3]
    ├── LikertButton5      ← AgencySurveyUI.likertButtons[4]
    ├── LikertButton6      ← AgencySurveyUI.likertButtons[5]
    └── LikertButton7      ← AgencySurveyUI.likertButtons[6]
```

## 4. コンポーネント割当（詳細手順）

### Step 1: 空のGameObject作成
1. Hierarchy で右クリック → **Create Empty**
2. 名前を **ExperimentOrchestrator** に変更
3. 同様に以下も作成:
   - **TrialEngine**
   - **DataLogger**
   - **EMSController**
   - **SubjectDataManager**

### Step 1.5: フェーズ移行UI作成
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

### Step 1.6: フィードバックText作成
1. Canvas を右クリック → **UI → Text** → 名前を **FeedbackText** に変更
2. RectTransform: PosY=-100, Width=200, Height=60
3. Font Size: 36
4. Alignment: Center-Middle
5. Color: 白

### Step 2: EMSController の設定
1. Hierarchy で **EMSController** を選択
2. Inspector で **Add Component** → **EMSController** を検索して追加
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

### Step 3: TrialEngine の設定
1. Hierarchy で **TrialEngine** を選択
2. Inspector で **Add Component** → **TrialEngine** を検索して追加
3. 参照を設定:
   | 項目 | 設定方法 |
   |------|----------|
   | Stimulus Image | Hierarchy の **StimulusImage** をドラッグ |
   | Green Color | 緑 (0, 255, 0) |
   | Red Color | 赤 (255, 0, 0) |
   | Feedback Text | Hierarchy の **FeedbackText** をドラッグ |
   | Show Reaction Time Feedback | ✓ (フィードバック表示ON) |
   | Feedback Duration Sec | 0.8 |
   | EMS Controller | Hierarchy の **EMSController** をドラッグ |

### Step 4: DataLogger の設定
1. Hierarchy で **DataLogger** を選択
2. Inspector で **Add Component** → **DataLogger** を検索して追加
3. デフォルト設定のままでOK:
   - Trial File Name: trial_log.csv
   - Agency File Name: agency_log.csv

### Step 4.5: PhaseTransitionUI の設定
1. Hierarchy で **PhaseTransitionPanel** を選択
2. Inspector で **Add Component** → **PhaseTransitionUI** を検索して追加
3. 参照を設定:
   | 項目 | 設定方法 |
   |------|----------|
   | Root | PhaseTransitionPanel 自身（CanvasGroup付き） |
   | Phase Name Text | Hierarchy の **PhaseNameText** をドラッグ |
   | Instruction Text | Hierarchy の **InstructionText** をドラッグ |
   | Press Space Text | Hierarchy の **PressSpaceText** をドラッグ |

### Step 5: AgencySurveyUI の設定（既にStep 6で完了済み）
AgencySurveyPanel に既に追加済みの場合はスキップ。
1. Hierarchy で **AgencySurveyPanel** を選択
2. Inspector で参照を確認:
   | 項目 | 設定 |
   |------|------|
   | Root | AgencySurveyPanel 自身（CanvasGroup付き） |
   | Likert Buttons | Size: 7、LikertButton1〜7 を順番に設定 |
   | Prompt Text | PromptText をドラッグ |

### Step 6: SubjectDataManager の設定
1. Hierarchy で右クリック → **Create Empty** → 名前を `SubjectDataManager` に変更
2. Inspector で **Add Component** → **SubjectDataManager** を検索して追加

### Step 7: ExperimentOrchestrator の設定
1. Hierarchy で **ExperimentOrchestrator** を選択
2. Inspector で **Add Component** → **ExperimentOrchestrator** を検索して追加
3. 参照を設定:
   | 項目 | 設定方法 |
   |------|----------|
   | Trial Engine | Hierarchy の **TrialEngine** をドラッグ |
   | Agency Survey UI | Hierarchy の **AgencySurveyPanel** をドラッグ |
   | Data Logger | Hierarchy の **DataLogger** をドラッグ |
   | Subject Data Manager | Hierarchy の **SubjectDataManager** をドラッグ |
   | Phase Transition UI | Hierarchy の **PhaseTransitionPanel** をドラッグ |
4. 実験パラメータを設定:
   | 項目 | 値 | 説明 |
   |------|-----|------|
   | Subject Id | P001 | 被験者ID（実験ごとに変更） |
   | Group Type | AgencyEMS | AgencyEMS または Voluntary |
   | Run Mode | Calibration | 実験1は Calibration、実験2は Validation |
   | Trials Per Task | 30 | タスクあたりの試行数 |
   | EMS Latency Trials | 20 | EMSレイテンシ測定の試行数 |
   | Offset Start Ms | -200 | Agency探索の開始オフセット |
   | Offset End Ms | 100 | Agency探索の終了オフセット |
   | Offset Step Ms | 5 | オフセットの刻み幅 |

### Step 8: 最終確認
Hierarchy が以下の構造になっているか確認:
```
Main Camera
Directional Light
EventSystem          ← Canvas作成時に自動生成
Canvas
├── StimulusImage
└── AgencySurveyPanel
    ├── PromptText
    ├── LikertButton1
    ├── LikertButton2
    ├── LikertButton3
    ├── LikertButton4
    ├── LikertButton5
    ├── LikertButton6
    └── LikertButton7
ExperimentOrchestrator
TrialEngine
DataLogger
EMSController
SubjectDataManager   ← 追加
```

### Step 9: 動作テスト
1. **Ctrl+S** でシーンを保存
2. **Play** ボタンを押す
3. Console に以下が表示されれば成功:
   - `TrialEngine: Display XXHz → Target FPS: XXX`
   - `Created new subject: P001` または `Loaded subject data: P001`
   - `EMS Controller: Serial port COMX connected` （Arduino接続時）
   - または `EMS Controller: Arduino not connected (simulation mode)`（未接続時）
4. 刺激が表示され、クリックで反応時間が記録されることを確認
5. Agency評価UIが表示され、ボタンクリックで次に進むことを確認

## 5. 1日実験の運用手順

### データ管理構造
被験者データは以下の構造で自動管理されます：
```
<Application.persistentDataPath>/ReactionTestData/
├── P001/
│   ├── config.json                 ← 被験者設定（オフセット含む）
│   ├── calibration_01_20250101_100000/
│   │   ├── session_info.json
│   │   ├── trial_log.csv
│   │   └── agency_log.csv
│   ├── calibration_02_20250101_140000/  ← 再実行時は番号が増加
│   │   └── ...
│   └── validation_01_20250101_160000/
│       └── ...
└── P002/
    └── ...
```

### 実験1: キャリブレーション
1. ExperimentOrchestrator の Run Mode を **Calibration** に設定
2. Subject Id を入力（例: P001）
3. Play を押す
4. Baseline → EMSLatency → AgencySearch が実行される
5. 終了後、Console にログ出力先が表示される
6. 出力ファイル:
   - trial_log.csv（Baseline + EMSLatency + AgencySearch の反応時間）
   - agency_log.csv（主体感評価データ）

### 中間解析（Python）
1. Analysis フォルダで依存を導入
   ```
   pip install -r requirements.txt
   ```
2. 解析を実行（**--subject-dir で被験者フォルダを指定**）
   ```
   python analyze_agency.py \
     --agency <session_path>/agency_log.csv \
     --trial <session_path>/trial_log.csv \
     --outdir <session_path> \
     --subject-dir <subject_path>
   ```
   例:
   ```
   python analyze_agency.py \
     --agency "C:/Users/.../ReactionTestData/P001/calibration_01_.../agency_log.csv" \
     --trial "C:/Users/.../ReactionTestData/P001/calibration_01_.../trial_log.csv" \
     --outdir "C:/Users/.../ReactionTestData/P001/calibration_01_..." \
     --subject-dir "C:/Users/.../ReactionTestData/P001"
   ```
3. 出力:
   - agency_offset.json（個人別オフセット + ベースラインRT + EMSレイテンシ）
   - 各種解析レポート
   - **config.json が自動更新される**

### 実験2: 訓練・測定
1. **同じ Subject Id を入力**（例: P001）
2. ExperimentOrchestrator の Run Mode を **Validation** に設定
3. Group Type を設定（AgencyEMS / Voluntary）
4. Play を押す
5. **自動的にキャリブレーション結果が読み込まれる**
6. Training → PostTest が実行される

> **注意**: キャリブレーション未完了の場合はエラーになります

### 再キャリブレーション
同じ Subject Id で再度 Calibration を実行すると、新しいセッション（calibration_02_... など）が作成されます。
Python解析で最新セッションを指定し、config.json を更新することで、新しいオフセットが適用されます。

## 6. 出力データ形式

### config.json (被験者設定)
| フィールド | 説明 |
|------------|------|
| SubjectId | 被験者ID |
| Group | 実験群（AgencyEMS / Voluntary） |
| LatestCalibrationSession | 最新キャリブレーションセッション番号 |
| LatestValidationSession | 最新検証セッション番号 |
| SRT_Offset / DRT_Offset / CRT_Offset | 主体感維持オフセット (ms) |
| BaselineRT_SRT / DRT / CRT | ベースライン反応時間 (ms) |
| EMSLatency_SRT / DRT / CRT | EMS応答遅延 (ms) |
| CalibrationCompleted | キャリブレーション完了フラグ |
| LastUpdated | 最終更新日時 |

### trial_log.csv
| 列名 | 説明 |
|------|------|
| phase | Baseline / EMSLatency / AgencySearch / Training / PostTest |
| task | SRT / DRT / CRT |
| trial_index | 試行番号 |
| stimulus_color | Green / Red |
| expected_action | Left / Right / None |
| actual_action | Left / Right / None |
| is_correct | true / false |
| reaction_time_ms | 反応時間（ミリ秒） |
| ems_enabled | true / false |
| ems_offset_ms | EMSオフセット |
| timestamp | ISO8601形式タイムスタンプ |

### agency_log.csv
| 列名 | 説明 |
|------|------|
| task | SRT / DRT / CRT |
| candidate_offset_ms | テストしたオフセット値 |
| agency_likert_7 | 主体感評価（1〜7） |
| timestamp | ISO8601形式タイムスタンプ |

### agency_offset.json
```json
{
  "SRT": 40.0,
  "DRT": 35.0,
  "CRT": 30.0,
  "BaselineRT_SRT": 280.0,
  "BaselineRT_DRT": 320.0,
  "BaselineRT_CRT": 350.0,
  "EMSLatency_SRT": 50.0,
  "EMSLatency_DRT": 55.0,
  "EMSLatency_CRT": 60.0
}
```

**オフセット**: ボタンフィードバックを速める量（正の値）
**BaselineRT**: EMSなしでの平均反応時間
**EMSLatency**: EMS発火→ボタン押下の遅延時間（EMSLatencyフェーズで測定）
**EMS発火タイミング**: BaselineRT - Offset - EMSLatency

## 7. 注意点
- EMSController が未接続の場合、シミュレーションモードで動作（Debug.Logのみ）
- GroupType が Voluntary の場合は EMS 無効
- EMS発火タイミング = ベースライン反応時間 - オフセット - EMSレイテンシ
- Arduino側で500ms未満の連打は安全装置により無視される

## 8. EMSキャリブレーション
EMSController の Test Trigger Left/Right をチェックすると、手動でEMS発火テストが可能。
刺激強度の調整は Arduino_ReactionTest_EMS.ino のパラメータまたは Unity インスペクタで行う。
