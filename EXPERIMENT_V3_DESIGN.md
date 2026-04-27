# Reaction Test 実験設計 V3（CRT特化・HDDM解析対応）

> **V3.2** — CRT特化・6フェーズ連続実行・適応的インターリーブ階段法・左右独立キャリブレーション
> **V3.2 変更点**: 熟練度収束 / DDM 推定精度の確保のため、Practice / Baseline / Training / PostTest の試行数を増加

## 1. 目的

Kasahara et al. (CHI'21) "*Preserving Agency During EMS Training*" の追試・拡張。
EMS を「主体感（Agency）を維持できるギリギリのタイミング」で発火すると、訓練後に反応時間が短縮するかを検証する。

タスクは **CRT（Choice Reaction Time = 左右2択）** に固定。
- 刺激色 = 左（緑） / 右（赤）
- 正解 = ターゲット側と同じボタンをクリック

## 2. 実験フロー（1日・1ラン・6フェーズ連続実行）

| # | フェーズ | 試行数（既定） | EMS | 説明 |
|----|----------|---------------|-----|------|
| 1 | **Practice** | 50 | なし | 習熟。CRTタスクの学習曲線を漸近線付近まで進めた状態で Baseline へ移行 |
| 2 | **Baseline** | 80 | なし | HDDMベースライン。左右別にIQRフィルタ → 平均で `BaselineRT_Left/Right` を算出 |
| 3 | **EMSLatency** | 左右各10 = 計20 | あり（視覚刺激なし） | EMS発火 → ボタン押下までの遅延を測定。IQRフィルタ → 平均で `EMSLatency_Left/Right` を算出 |
| 4 | **Calibration** | 最大80（収束時打ち切り） | あり | Agency閾値の適応的階段法探索。左右独立の階段で反転5回到達で収束 |
| 5 | **Training** | 100 | 群別 | `AgencyEMS` 群はキャリブレーション済みオフセットでEMS、`Voluntary` 群はEMSなし |
| 6 | **PostTest** | 80 | なし | HDDM事後測定 |

- 全フェーズで **Esc キー** による緊急停止可（EMS 即時無効化 + データ Flush）
- フェーズ間は `PhaseTransitionUI` でフェーズ名・説明を表示し、**スペースキー** で開始
- Baseline / Training / PostTest では **20 試行ごとに自発休憩 UI** を表示し、被験者の任意でスペースキーで再開

### V3.2 試行数増加の根拠

| フェーズ | V3.1 | V3.2 | 理由 |
|---|---|---|---|
| Practice | 15 | **50** | CRT 学習曲線の漸近線到達には数百試行が必要との文献的指摘に応じ、Practice を増やしてベースライン測定時の熟練度を安定化（教授指摘への対応） |
| Baseline | 40 | **80** | DDM パラメータ（特に t）の推定 SE は √N に反比例。40→80 で SE 約 30% 改善。階層ベイズの部分プーリングと併せて推定の robustness を確保 |
| EMSLatency | 30 | **20** | EMS 発火回数の総量を抑える（不応期 200ms × 30 = 最低6秒のフェーズ → 20 で4秒に短縮）。IQR フィルタ後の平均推定としては左右各10で十分 |
| Training | 40 | **100** | 訓練効果が定着するための試行数を確保。Kasahara et al. (CHI'21) の追試として妥当な水準 |
| PostTest | 40 | **80** | Baseline と対称にし、Δt 等の事後分布の推定精度を確保 |

合計試行数: V3.1 = 245 → V3.2 = 410。所要時間目安: 装着含めて 30-40 分。

## 3. EMS発火タイミング

### 関係式
```
EMSFireTiming = BaselineRT(side) − EMSOffset − EMSLatency(side)
```

| 変数 | 説明 |
|------|------|
| `EMSOffset` | BaselineRT より何ms前倒しして押させたいか（= pre-emptive gain、速めたい量） |
| `EMSFireTiming` | 刺激提示から何ms後に EMS を発火するか（実装上の待機時間） |
| `EMSLatency` | EMS発火 → ボタン押下までの被験者の筋収縮遅延（左右別） |
| `BaselineRT` | EMSなしでの反応時間（左右別） |

### 計算例
```
BaselineRT_Left = 300ms, EMSOffset = 40ms, EMSLatency_Left = 50ms
→ FireTiming = 300 − 40 − 50 = 210ms（刺激提示から210ms後にEMS）
→ 実際のボタン押下 ≈ 210 + 50 = 260ms（BaselineRTより40ms速い）
```

## 4. キャリブレーション（適応的インターリーブ階段法）

`StaircaseCalibrator` による左右独立の適応的インターリーブ階段。

| パラメータ | 値 |
|-----------|-----|
| 初期オフセット | 40ms（先行研究の Agency 閾値近傍） |
| Agency判定 | **2AFC (はい/いいえ)** または 7段階リッカート (≥ 4 を Yes) |
| ステップ幅 | 反転0–1回 → 10ms / 2–3回 → 5ms / 4回以上 → 3ms |
| 収束条件 | 左右それぞれ反転5回到達 |
| 最終値 | 反転時のオフセット値の平均 |
| 最大試行数 | 80（未収束時は現在値を採用し警告ログ） |

### 更新則
- **Yes（主体感あり）** → offset をマイナス方向（より速いEMS = 難しく）
- **No（主体感なし）** → offset をプラス方向（より遅いEMS = 簡単に）

### ターゲット側選択
- 両側未収束 → 50/50ランダム
- **片側収束後は未収束側を確定選択**（残試行を浪費しない）

### 特殊処理
- **エラー試行**: Agency回答は無効扱いで階段更新をスキップ
- **キャッチ試行**: 収束済み側がランダムで選ばれた場合。収束値を固定使用、Agency UIは表示するが回答は破棄

## 5. データ保存

被験者データは `<プロジェクトルート>/ExperimentData/<SubjectID>/` に保存される。

```
ExperimentData/
├── P001/
│   ├── config.json                       ← 被験者設定（群・キャリブレーション結果）
│   ├── session_01_20260422_100000/
│   │   ├── session_info.json
│   │   └── trial_log.csv
│   └── session_02_.../
└── P002/
    └── ...
```

### config.json (SubjectConfig)

| フィールド | 型 | 説明 |
|----|----|------|
| `SubjectId` | string | 被験者ID |
| `Group` | GroupType | 実験群（`AgencyEMS` / `Voluntary`）。**既存被験者の群は保存値が優先される**（Inspector値と不一致の場合はエラーログ） |
| `LatestSessionNumber` | int | 最新セッション番号 |
| `AgencyOffsetLeft` | float | 階段法で同定した左チャンネル Agency維持オフセット (ms) |
| `AgencyOffsetRight` | float | 階段法で同定した右チャンネル Agency維持オフセット (ms) |
| `BaselineRTLeft` | float | 左ターゲットのベースライン反応時間 (ms) |
| `BaselineRTRight` | float | 右ターゲットのベースライン反応時間 (ms) |
| `EMSLatencyLeft` | float | 左チャンネルの EMS→ボタン押下レイテンシ (ms) |
| `EMSLatencyRight` | float | 右チャンネルの EMS→ボタン押下レイテンシ (ms) |
| `CalibrationCompleted` | bool | キャリブレーション完了フラグ |
| `LastUpdated` | string | 最終更新日時 (ISO 8601) |

### trial_log.csv

1試行 = 1行。Agency回答も同じ行に統合済み（別ファイル `agency_log.csv` は **廃止**）。

| 列名 | 説明 |
|----|------|
| `SubjectID` | 被験者ID |
| `Group` | `AgencyEMS` / `Voluntary` |
| `Phase` | `Practice` / `Baseline` / `EMSLatency` / `Calibration` / `Training` / `PostTest` |
| `TrialNumber` | フェーズ内の試行番号（1-indexed） |
| `TargetSide` | `Left` / `Right`（EMSLatencyフェーズではEMS発火チャンネル） |
| `ResponseSide` | `Left` / `Right` / `None`（タイムアウト） |
| `IsCorrect` | `1` / `0`（**エラー試行も必ず記録** — DDM解析で必須） |
| `ReactionTime_ms` | 反応時間（ms、小数3桁）。タイムアウト時は -1 |
| `EMSOffset_ms` | **速めたい量**（pre-emptive gain）。Calibrationでは候補値、Trainingでは確定値、EMSなしは 0 |
| `EMSFireTiming_ms` | **実発火タイミング**（刺激提示から何ms後に発火したか）。EMSなしは 0 |
| `AgencyLikert` | 主体感評価 1–7。Calibration以外は 0 |
| `Timestamp` | ISO 8601 (UTC) |

### session_info.json

| フィールド | 説明 |
|----|------|
| `SubjectId` | 被験者ID |
| `Group` | 実験群 |
| `DatetimeStart` | セッション開始日時 (ISO 8601 UTC) |
| `AppVersion` | Unity アプリケーションバージョン |

### 型・Enum

| 名称 | 値 |
|----|------|
| `GroupType` | `AgencyEMS`, `Voluntary` |
| `PhaseType` | `Practice`, `Baseline`, `EMSLatency`, `Calibration`, `Training`, `PostTest` |
| `UserAction` | `None`, `Left`, `Right` |
| `ErrorType` | `None`, `WrongSide`, `Omission`（Commission は廃止 — CRTでは常に左右どちらかを押す） |

## 6. 実装構成

| コンポーネント | ファイル | 責務 |
|----|----|----|
| `ExperimentOrchestrator` | ExperimentOrchestrator.cs | 6フェーズ連続実行、群別ロジック、IQRフィルタ、緊急停止 |
| `TrialEngine` | TrialEngine.cs | 1試行の制御（刺激表示、入力監視、RT計測、EMS発火ディスパッチ）。高精度 `Stopwatch` 使用 |
| `TaskRule` | TaskRule.cs | CRT正解判定、ターゲット側ランダム選択（Left/Right 50/50） |
| `EMSPolicy` | EMSPolicy.cs | EMS発火タイミング計算（`BaselineRT − Offset − EMSLatency`）。Training用 / Calibration用の2メソッド |
| `StaircaseCalibrator` | StaircaseCalibrator.cs | 左右独立の適応的階段法。`StaircaseLadder` が片側のステートを管理 |
| `AgencySurveyUI` | AgencySurveyUI.cs | 7段階リッカートUI（CanvasGroup で表示/非表示切替） |
| `DataLogger` | DataLogger.cs | `trial_log.csv` へのメモリバッファ + フェーズ終了時Flush。N試行ごとの自動Flush付き（既定: 10試行） |
| `SubjectDataManager` | SubjectDataManager.cs | 被験者フォルダ・config.json・セッションフォルダ管理 |
| `EMSController` | EMSController.cs | Arduino DUE + L298N シリアル通信、安全機構（不応期200ms・最大発火回数500・緊急停止） |
| `PhaseTransitionUI` | PhaseTransitionUI.cs | フェーズ間案内表示（スペースキー待機）+ 自発休憩 UI |
| `ExperimentTypes` | ExperimentTypes.cs | Enum定義 (`GroupType`, `PhaseType`, `UserAction`, `ErrorType`, `EMSDecision`) |
| `DataModels` | DataModels.cs | データモデル (`SessionMeta`, `TrialRecord`, `AgencyOffsetConfig`) |

## 7. 高精度タイミング

- `TrialEngine.Awake()` でディスプレイ周波数の2倍（最低120fps）に `targetFrameRate` を設定、VSync OFF
- 反応時間は `System.Diagnostics.Stopwatch` で計測（フレーム依存しない高精度タイマー）
- EMS発火待機: 50ms以上は `WaitForSeconds`、50ms未満はスピンウェイト

## 8. 外れ値除去

### Unity 側（BaselineRT / EMSLatency 算出時）
- IQR法: `[Q1 − 1.5·IQR, Q3 + 1.5·IQR]` 外を除外 → **平均**
- Q1/Q3 は線形補間で算出
- データ4件未満は単純平均にフォールバック
- 全データ除外時は中央値にフォールバック

### Python 側（解析時）
- 生理制約: 100ms未満、1000ms超を除外
- 正解試行のみから中央値を算出（RT Gain 計算用）

## 9. 安全機構

| 機構 | 実装箇所 | 説明 |
|----|----|----|
| **緊急停止 (Esc)** | TrialEngine + ExperimentOrchestrator | Escキーで即座にEMS無効化 + データFlush + 実験中断 |
| **不応期** | EMSController | 連続発火の最小間隔 200ms（既定）。間隔内の発火はブロック |
| **最大発火回数** | EMSController | 1セッションあたり最大500回（既定）。超過時はEMS無効化 |
| **Arduino側安全装置** | Arduino_ReactionTest_EMS.ino | 500ms未満の連打を無視 |
| **自動Flush** | DataLogger | N試行ごとにバッファを自動書き出し（既定: 10試行）。クラッシュ時のデータ消失防止 |
| **終了時Flush** | DataLogger | `OnApplicationQuit` + `OnDestroy` でバッファ書き出し |
| **群の保護** | SubjectDataManager | 既存被験者のGroupをInspector値で上書きしない。不一致時はエラーログ |

## 10. 統計解析

仮説階層・判断基準・結果解釈フローの詳細は以下のドキュメントを参照:

- **`Analysis/HYPOTHESIS_AND_ANALYSIS_PLAN.md`** — 仮説 (H1/H2/H3)、判断基準、結果報告
- **`Analysis/HYPOTHESIS_DECISION_TREE.md`** — 結果パターン別の解釈フロー
- **`Analysis/ANALYSIS_PLAN_SUMMARY.md`** — 1ページサマリ
- **`Analysis/HDDM_README.md`** — HDDM 解析の実行マニュアル

### 解析スクリプト

| スクリプト | 担当 |
|---|---|
| `Analysis/analyze_training_effect.py` | 観測指標 (ΔRT, Δaccuracy) + EZ-DDM (補助) |
| `Analysis/analyze_training_effect_hddm.py` | 階層ベイズ DDM (主機構分解) |
| `Analysis/analyze_agency.py` | Calibration の階段法可視化、Agency 心理測定関数 |
| `Analysis/make_dummy_data.py` | パイプライン動作確認用の仮想データ生成 |

### 仮説（要約）

- **H1（主仮説）**: AgencyEMS 群は Voluntary 群より大きな ΔRT 短縮を示す
- **H2（制約）**: その RT 短縮は accuracy 低下を伴わない（速度-正答率トレードオフではない）
- **H3（機構, 仮説駆動）**: 短縮は主に non-decision time `t` の短縮として現れる
- **H3'（機構, 探索的）**: drift rate `v` や decision time の変化も観察し、効果の局在を分解する

### 判断基準

| 事後確率 P(Δ < 0 \| data) | 解釈 |
|---|---|
| ≥ 0.97 | 強い証拠 (strong) |
| 0.90–0.97 | 中程度 (moderate) |
| 0.85–0.90 | 弱い (anecdotal) |
| < 0.85 | 証拠なし |

加えて 95% HDI と ROPE による equivalence 判定を併用。

### 必要サンプルサイズ

- **H1**: 効果量 f = 0.3、α = 0.05、Power = 0.80 → 各群 18 名 × 2 群 = **36 名**
- **H3 (機構分解)**: 探索的位置付け。被験者間個人差 (σ_t_between) の実測値次第で必要 N が変動
  → パイロット 5 名で σ_t_between を実測し、必要に応じて追加被験者を検討

### 参考文献
- Kasahara, S., et al. (2021). *Preserving Agency During Electrical Muscle Stimulation Training Speeds up Reaction Time Directly After Removing EMS.* CHI '21.
- Wiecki, T. V., Sofer, I., & Frank, M. J. (2013). *HDDM: Hierarchical Bayesian estimation of the Drift-Diffusion Model in Python.* Frontiers in Neuroinformatics.
- Ratcliff, R., & McKoon, G. (2008). *The diffusion decision model: Theory and data for two-choice decision tasks.* Neural Computation.
- Kruschke, J. K. (2018). *Rejecting or accepting parameter values in Bayesian estimation.* AMPPS.

## 11. 使用方法

### 実験実行
```
1. ExperimentOrchestrator の Inspector で SubjectId / GroupType を設定
2. Play → 6フェーズが自動的に連続実行される
3. 同じ SubjectId で再実行 → 新しいセッション (session_02_...) が作成される
4. 既存のキャリブレーションデータがあれば自動読み込み
```

### 解析実行
```bash
# 観測指標 + EZ-DDM
python Analysis/analyze_training_effect.py \
  --data_dir ExperimentData \
  --outdir Analysis/results

# 階層ベイズ DDM (HDDM Docker 内)
python Analysis/analyze_training_effect_hddm.py \
  --data_dir ../ExperimentData \
  --outdir ./results_hddm \
  --samples 10000 --burn 2000 --thin 2
```

## 12. 妥当性確認チェックリスト

- [ ] CRT 左右反応の正解判定が正しいか（緑=左、赤=右）
- [ ] エラー試行が `IsCorrect=0` として必ず記録されるか（破棄されていないか）
- [ ] 外れ値除去後に n が想定より過少になっていないか
- [ ] 群別の EMS ポリシーが混線していないか（Voluntary群で EMS が発火していないか）
- [ ] `EMSFireTiming_ms = BaselineRT − EMSOffset − EMSLatency`（左右別）が正しく計算されているか
- [ ] 既存被験者の Group が Inspector 値で上書きされていないか（config.json の `Group` を確認）
- [ ] Calibration が収束しているか（反転5回/側、未収束時の警告ログ）
- [ ] Esc 中断後に `trial_log.csv` が記録途中まで残っているか
- [ ] 高精度タイマー（Stopwatch）が正常に動作しているか
- [ ] EMSController の安全機構（不応期・最大発火回数）が機能しているか
