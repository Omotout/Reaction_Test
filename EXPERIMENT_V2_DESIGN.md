# Reaction Test 実験設計（SRT/DRT/CRT + EMS研究）

## 1. 目的
FPS_ReactionTest の基盤を活用し、次の3タスクで反応速度とEMS介入効果を検証する。

- TaskA (SRT): 緑円が出たら左クリック（単純反応）
- TaskB (DRT): 緑円は左クリック、赤円は無反応（弁別反応）
- TaskC (CRT): 緑円は左クリック、赤円は右クリック（選択反応）

## 2. 実験全体フロー

**本実験は1日で実施する。**

### 実験1: キャリブレーション（個人別ベースライン取得）
目的：個人ごとの反応時間を測定し、実験2で使用するEMSタイミングを決定するためのデータを収集する。

1. ベースライン測定（EMSなし）
   - TaskA/B/C を各30試行
   - 反応時間とエラーをログに記録
   - 出力: trial_log.csv（BaselineRT を含む）

2. EMSレイテンシ測定（EMSあり、0msオフセット）
   - TaskA/B/C を各20試行
   - 0msオフセットでEMS発火し、反応時間を測定
   - EMS発火→ボタン押下の遅延時間を取得
   - 出力: trial_log.csv（EMSLatency を含む）

3. Agency探索（EMSあり）
   - 各タスクで、EMSオフセットを -200ms から +100ms を 5ms 刻みで提示
   - 各提示後に主体感を7段階リッカート（1〜7）で取得
   - 出力: agency_log.csv

4. **中間解析（Python）**
   - 実験1終了後、analyze_agency.py を実行
   - ベースラインRT: Baselineフェーズの平均反応時間（外れ値除去後）
   - EMSレイテンシ: EMSLatencyフェーズの平均反応時間（外れ値除去後）
   - **Agency閾値の決定（ロジスティック回帰法）**:
     1. Agencyスコアを0-1に正規化: `(score - 1) / 6`
     2. 各個人・各タスクでオフセット vs 正規化Agencyにロジスティック回帰をフィット
     3. `Agency(x) = 1 / (1 + exp(-k * (x - x0)))`
     4. Agency = 0.5 となるオフセット `x0` を最適オフセットとして採用
   - 結果を agency_offset.json として保存

### 実験2: 訓練と効果測定（対照実験）
目的：実験1で同定したタイミングを用いて、反応速度向上効果を検証する。

**前提条件**: 実験1の解析完了、agency_offset.json が存在すること

1. 群割当
   - Agency-EMS群: 実験1で同定した主体感維持タイミングでEMS
   - Voluntary群: EMSなし（対照群）

2. 訓練フェーズ
   - TaskA → TaskB → TaskC の順
   - 各タスク30試行
   - 群に応じたEMSポリシーを適用

3. 事後測定フェーズ
   - 各タスク30試行（EMSなし）
   - 訓練効果の測定

## 3. EMSオフセットの計算方法

### 概念
システムでは「ボタンフィードバックを何ms速めるか」をオフセットとして指定する。
EMSを発火してから実際にボタンが押されるまでには遅延（EMSレイテンシ）があるため、これを考慮して発火タイミングを計算する。

### 計算式
```
EMS発火タイミング = ベースライン反応時間 - オフセット - EMSレイテンシ
```

- **ベースライン反応時間**: EMSなしでの平均反応時間（刺激→ボタン押下）
- **オフセット**: ボタンフィードバックを速める量（正の値）
- **EMSレイテンシ**: EMS発火→ボタン押下の遅延時間（0msオフセットで測定）

### 例
- ベースライン反応時間: 300ms
- EMSレイテンシ: 50ms（0msオフセットでEMS発火した時の応答時間）
- オフセット: 40ms（ボタンフィードバックを40ms速めたい）

計算:
- EMS発火タイミング = 300 - 40 - 50 = **210ms**（刺激提示から210ms後にEMS発火）
- 実際のボタン押下 = 210 + 50 = 260ms
- 速くなった量 = 300 - 260 = 40ms ✓

### agency_offset.json の形式
```json
{
  "SRT": 40.0,              // 主体感維持オフセット（速める量）
  "DRT": 35.0,
  "CRT": 30.0,
  "BaselineRT_SRT": 280.0,  // ベースライン反応時間（EMSなし）
  "BaselineRT_DRT": 320.0,
  "BaselineRT_CRT": 350.0,
  "EMSLatency_SRT": 50.0,   // EMSレイテンシ（0msオフセット時の応答時間）
  "EMSLatency_DRT": 55.0,
  "EMSLatency_CRT": 60.0
}
```

## 4. 1日実験のワークフロー

```
[実験1: キャリブレーション]
    │
    ├── ベースライン測定 (EMSなし, 各タスク30試行)
    │      ↓
    ├── EMSレイテンシ測定 (0msオフセット, 各タスク20試行)
    │      ↓
    ├── Agency探索 (EMS提示 + 主体感評価)
    │      ↓
    └── CSV出力: trial_log.csv, agency_log.csv
           │
           ↓
[中間解析: Python]
    │
    ├── analyze_agency.py 実行
    ├── ベースラインRT算出（Baselineフェーズから）
    ├── EMSレイテンシ算出（EMSLatencyフェーズから）
    ├── 推奨オフセット算出（Agency探索から）
    └── agency_offset.json 出力
           │
           ↓
[実験2: 訓練・測定]
    │
    ├── agency_offset.json 読み込み
    ├── 訓練フェーズ (群別EMS適用)
    └── 事後測定フェーズ (EMSなし)
```

## 5. 実装構成（FPS_ReactionTestから移植予定）

FPS_ReactionTest から以下の機能を移植:
- シリアル通信によるEMS制御（Arduino連携）
- 高精度タイマー（Stopwatch）による反応時間計測
- CSV保存機能

現在の責務分離設計:
- ExperimentOrchestrator: フェーズ遷移、群割当、実験進行
- TrialEngine: 1試行のステート制御（待機、刺激提示、入力監視、RT計測）
- TaskRule: A/B/C の正解条件と反応判定
- EMSPolicy: 群ごとのEMSタイミング決定
- AgencySurveyUI: 主体感アンケート表示・回答収集
- DataLogger: セッション・トライアル・アンケートの保存

## 6. 推奨データモデル

### 列挙型
- TaskType: SRT, DRT, CRT
- GroupType: AgencyEMS, Voluntary
- PhaseType: Baseline, AgencySearch, Training, PostTest
- StimulusColor: Green, Red

### 主要レコード
- SessionMeta
  - subject_id
  - group
  - datetime_start
  - app_version
- TrialRecord
  - phase
  - task
  - trial_index
  - stimulus_color
  - expected_action (Left/Right/None)
  - actual_action (Left/Right/None)
  - is_correct
  - reaction_time_ms
  - ems_enabled
  - ems_offset_ms
  - timestamp
- AgencyRecord
  - task
  - candidate_offset_ms
  - agency_likert_7 (1..7)

## 6. 反応判定仕様（タスク別）

- TaskA (SRT)
  - 刺激: 緑のみ
  - 正解: 左クリック
- TaskB (DRT)
  - 刺激: 緑/赤
  - 正解: 緑は左クリック、赤は無反応
- TaskC (CRT)
  - 刺激: 緑/赤
  - 正解: 緑は左クリック、赤は右クリック

ミス分類（分析用）
- commission error（押してはいけない時に押した）
- omission error（押すべき時に押さなかった）
- wrong-side error（左右誤り）

## 7. 外れ値除去仕様

推奨（既存分析と整合、Kasahara et al. CHI'21 準拠）
- 生理制約: 100ms未満、1000ms超を除外
- IQR法: [Q1 - 1.5IQR, Q3 + 1.5IQR] 外を除外
- 各セッション最初の2試行は除外（集中力安定のため）

除外後の中央値を RT とする。

## 8. 統計解析

### 8.1 Agency解析（実験1: キャリブレーション）

スクリプト: `analyze_agency.py`

出力:
- Preemptive gainごとの主体感平均（SEM付き）
- 一元配置ANOVA
- 多重比較（Tukey HSD）
- agency_offset.json（個人別オフセット）

### 8.2 訓練効果解析（実験2: Validation）

スクリプト: `analyze_training_effect.py`

**実験デザイン**:
- 被験者間要因: 群（AgencyEMS vs Voluntary）
- 被験者内要因: タスク（SRT vs DRT vs CRT）
- 従属変数: RT Gain = PostTest_RT - Baseline_RT

**必要サンプルサイズ**:
- 効果量 f = 0.3（中〜大）想定
- α = 0.05, Power = 0.80
- **各群18名 × 2群 = 計36名**

**分析手順** (Kasahara et al. CHI'21 準拠):

1. **RT Gain計算**
   - 各被験者×タスクごとに: Gain = median(PostTest_RT) - median(Baseline_RT)
   - 負の値 = 速くなった

2. **正規性検定**
   - Shapiro-Wilk検定（各条件で実施）
   - 非正規の場合はノンパラメトリック検定を検討

3. **2×3 混合計画ANOVA**
   - 主効果: 群、タスク
   - 交互作用: 群×タスク
   - ライブラリ: pingouin

4. **事後検定**
   - 各タスクでの群間比較（独立t検定、Bonferroni補正）
   - 各群内でのタスク間比較（対応ありt検定）

5. **one-sample t検定**
   - 各条件でのGain vs 0 の検定
   - 有意ならば「速くなった」と結論

6. **効果量**
   - Cohen's d を算出（群間比較）
   - 0.2=小, 0.5=中, 0.8=大

**仮説**:
- H1: AgencyEMS群はVoluntary群より大きなRT短縮を示す
- H2: 効果はタスク複雑性（SRT > DRT > CRT）で異なる
- H3: 群×タスクの交互作用が見られる

**参考文献**:
- Kasahara, S., et al. (2021). Preserving Agency During Electrical Muscle Stimulation Training Speeds up Reaction Time Directly After Removing EMS. CHI '21.
  - SRTで約8ms（最大20ms）の短縮効果
  - Agency維持が効果の鍵

## 9. 実装ステップ（最短）

1. FPS_ReactionTestからEMS制御を移植
   - SerialPort通信クラス
   - EMSConfig送信機能

2. 入力方式をクリック判定に対応
   - 左右クリックを直接取得

3. TaskRule を導入
   - タスクごとに刺激生成と正解判定を切替

4. AgencyアンケートUI実装
   - 7段階リッカートを回答
   - 回答とオフセットを保存

5. データ保存をCSV2系統へ
   - trial_log.csv（試行単位）
   - agency_log.csv（アンケート単位）

6. Python解析追加
   - analyze_agency.py: キャリブレーション解析
   - analyze_training_effect.py: 訓練効果解析（混合ANOVA）

7. 訓練・測定ループ実装
   - 群ごとに EMSPolicy を適用
   - 各タスク30試行で固定

## 10. 妥当性確認チェックリスト
- タスクA/B/Cで正解判定が仕様通りか
- TaskB赤刺激で無反応が正解として記録されるか
- 外れ値除去後に n が想定より過少になっていないか
- 群ごとのEMSポリシーが混線していないか
- 30試行完了で必ず保存されるか
- agency_offset.json が正しく読み込まれるか
- EMSタイミング = BaselineRT - Offset - EMSLatency が正しく計算されているか
