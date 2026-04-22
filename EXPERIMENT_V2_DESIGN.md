# Reaction Test 実験設計（CRT + EMS研究）

> 旧称: EXPERIMENT_V2_DESIGN。現行実装は V3（CRT特化・6フェーズ連続実行・適応的階段法）。

## 1. 目的
Kasahara et al. (CHI'21) "Preserving Agency During EMS Training" の追試・拡張。
EMS を「主体感（Agency）を維持できるギリギリのタイミング」で発火すると、訓練後に反応時間が短縮するかを検証する。

タスクは **CRT（Choice Reaction Time = 左右2択）** に固定。
- 刺激色 = 左（緑） / 右（赤）
- 正解 = ターゲット側と同じボタンをクリック

## 2. 実験フロー（1日・1ラン・6フェーズ連続実行）

1. **Practice** — 習熟。EMSなし。15試行（既定）。
2. **Baseline** — HDDMベースライン。EMSなし。40試行（既定）。**左右別にIQRフィルタ → 平均で `BaselineRT_Left / Right` を算出**。
3. **EMSLatency** — 視覚刺激なし。EMSを発火 → 被験者が筋収縮側のボタンを押すまでの遅延を測定。左右各15試行。IQRフィルタ → 平均で `EMSLatency_Left / Right` を算出。
4. **Calibration** — Agency閾値の適応的階段法探索。最大80試行（収束時打ち切り）。左右独立の階段で、反転5回到達で収束。
5. **Training** — 介入フェーズ。`AgencyEMS` 群はキャリブレーション済みのオフセットでEMS、`Voluntary` 群はEMSなし。40試行。
6. **PostTest** — HDDM事後測定。EMSなし。40試行。

全フェーズで Esc キーによる緊急停止可（EMS 即時無効化 + データ Flush）。

## 3. EMS発火タイミング

### 関係式
```
EMSFireTiming = BaselineRT(side) − EMSOffset − EMSLatency(side)
```

- **EMSOffset**: 「BaselineRT より何ms前倒しして押させたいか」（= pre-emptive gain、速めたい量）
- **EMSFireTiming**: 「刺激提示から何ms後に EMS を発火するか」（実装上の待機時間）
- **EMSLatency**: EMS発火 → ボタン押下までの被験者の筋収縮遅延（左右別）
- **BaselineRT**: EMSなしでの反応時間（左右別）

### 例
BaselineRT_Left=300ms, EMSOffset=40ms, EMSLatency_Left=50ms
→ FireTiming = 300 − 40 − 50 = **210ms**（刺激提示から210ms後にEMS）
→ 実際のボタン押下 ≈ 210 + 50 = 260ms（BaselineRTより40ms速い）

## 4. キャリブレーション（階段法）

`StaircaseCalibrator` による左右独立の適応的インターリーブ階段。

- **初期オフセット**: 40ms（先行研究の Agency 閾値近傍）
- **Agency判定**: 7段階リッカートで ≥4 を Yes とする
- **更新則**: Yes → offset をマイナス方向（より速いEMS = 難しく） / No → プラス方向
- **ステップ幅**: 反転0-1回→10ms / 2-3回→5ms / 4回以上→3ms
- **収束条件**: 左右それぞれ反転5回到達
- **最終値**: 反転時のオフセット値の平均
- **ターゲット側選択**: 両側未収束なら50/50ランダム、**片側収束後は未収束側を確定選択**（残試行を浪費しない）
- **エラー試行**: Agency回答は無効扱いで階段更新をスキップ
- **最大試行数**: 80（未収束時は現在値を採用し警告ログ）

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

| フィールド | 説明 |
|----|----|
| `SubjectId` | 被験者ID |
| `Group` | 実験群（`AgencyEMS` / `Voluntary`）。**既存被験者の群は保存値が優先される**（Inspector値と不一致の場合はエラーログ） |
| `LatestSessionNumber` | 最新セッション番号 |
| `AgencyOffsetLeft / Right` | 階段法で同定した左右別 Agency維持オフセット (ms) |
| `BaselineRTLeft / Right` | 左右別ベースライン反応時間 (ms) |
| `EMSLatencyLeft / Right` | 左右別 EMS応答レイテンシ (ms) |
| `CalibrationCompleted` | キャリブレーション完了フラグ |
| `LastUpdated` | 最終更新日時 (ISO 8601) |

### trial_log.csv

1試行 = 1行。Agency回答も同じ行に統合済み（別ファイル `agency_log.csv` は廃止）。

| 列名 | 説明 |
|----|----|
| `SubjectID` | 被験者ID |
| `Group` | `AgencyEMS` / `Voluntary` |
| `Phase` | `Practice` / `Baseline` / `EMSLatency` / `Calibration` / `Training` / `PostTest` |
| `TrialNumber` | フェーズ内の試行番号（1-indexed） |
| `TargetSide` | `Left` / `Right`（EMSLatencyフェーズではEMS発火チャンネル） |
| `ResponseSide` | `Left` / `Right` / `None`（タイムアウト） |
| `IsCorrect` | `1` / `0`（エラー試行も必ず記録） |
| `ReactionTime_ms` | 反応時間。タイムアウト時は -1 |
| `EMSOffset_ms` | **速めたい量**（pre-emptive gain）。Calibrationでは候補値、Trainingでは確定値、EMSなしは 0 |
| `EMSFireTiming_ms` | **実発火タイミング**（刺激提示から何ms後に発火したか）。EMSなしは 0 |
| `AgencyLikert` | 主体感評価 1〜7。Calibration以外は 0 |
| `Timestamp` | ISO 8601 |

### 型・Enum

| 名称 | 値 |
|----|----|
| `GroupType` | `AgencyEMS`, `Voluntary` |
| `PhaseType` | `Practice`, `Baseline`, `EMSLatency`, `Calibration`, `Training`, `PostTest` |
| `UserAction` | `None`, `Left`, `Right` |
| `ErrorType` | `None`, `WrongSide`, `Omission`（Commissionは廃止） |

## 6. 実装構成

| コンポーネント | 責務 |
|----|----|
| `ExperimentOrchestrator` | 6フェーズ連続実行、群別ロジック、緊急停止 |
| `TrialEngine` | 1試行の制御（刺激表示、入力監視、RT計測、EMS発火ディスパッチ） |
| `TaskRule` | CRT正解判定、ターゲット側ランダム選択 |
| `EMSPolicy` | EMS発火タイミング計算（`BaselineRT − Offset − EMSLatency`） |
| `StaircaseCalibrator` | 左右独立の適応的階段法 |
| `AgencySurveyUI` | 7段階リッカートUI |
| `DataLogger` | `trial_log.csv` へのメモリバッファ + フェーズ終了時Flush |
| `SubjectDataManager` | 被験者フォルダ・config.json・セッションフォルダ管理 |
| `EMSController` | Arduino DUE + L298N シリアル通信、安全機構（不応期・最大発火回数・緊急停止） |
| `PhaseTransitionUI` | フェーズ間案内表示 |

## 7. 外れ値除去

### Unity 側（BaselineRT / EMSLatency 算出時）
- IQR法: `[Q1 − 1.5·IQR, Q3 + 1.5·IQR]` 外を除外 → **平均**
- データ4件未満は単純平均にフォールバック

### Python 側（解析時）
- 生理制約: 100ms未満、1000ms超を除外
- 正解試行のみから中央値を算出（RT Gain 計算用）

## 8. 統計解析

スクリプト: `Analysis/analyze_training_effect.py`

### 従来解析
- **RT Gain** = `median(PostTest_RT) − median(Baseline_RT)`（正解試行のみ、負値 = 速くなった）
- 独立t検定（AgencyEMS vs Voluntary）+ Cohen's d
- One-sample t検定（各群の Gain vs 0）
- BH-FDR 多重比較補正
- ベイズファクター BF10（pingouin利用可能時）

### HDDM 解析
- ベイズ推定で DDM パラメータ a（決定閾値）/ v（ドリフト率）/ t（非決定時間）を分離
- Baseline vs PostTest の a, t の変化を群間比較
- **注意**: 現行実装は PyMC + 正規分布近似のスケルトン。本格運用時は Wiener first-passage time 尤度（HSSM等）への置き換えが必要。

### 仮説
- H1: AgencyEMS 群は Voluntary 群より大きな RT 短縮を示す
- H2: Baseline → PostTest で t（非決定時間）が短縮する
- H3: a（決定閾値）は群間で差がない（慎重さではなく運動効率の変化）

### 必要サンプルサイズ
効果量 f = 0.3、α = 0.05、Power = 0.80 → 各群18名 × 2群 = **36名**

### 参考文献
- Kasahara, S., et al. (2021). *Preserving Agency During Electrical Muscle Stimulation Training Speeds up Reaction Time Directly After Removing EMS.* CHI '21.

## 9. 妥当性確認チェックリスト

- [ ] CRT 左右反応の正解判定が正しいか（緑=左、赤=右）
- [ ] エラー試行が `IsCorrect=0` として必ず記録されるか
- [ ] 外れ値除去後に n が想定より過少になっていないか
- [ ] 群別の EMS ポリシーが混線していないか（Voluntary群で EMS が発火していないか）
- [ ] `EMSFireTiming_ms = BaselineRT − EMSOffset − EMSLatency`（左右別）が正しく計算されているか
- [ ] 既存被験者の Group が Inspector 値で上書きされていないか（config.json の `Group` を確認）
- [ ] Calibration が収束しているか（反転5回/側、未収束時の警告ログ）
- [ ] Esc 中断後に `trial_log.csv` が記録途中まで残っているか
