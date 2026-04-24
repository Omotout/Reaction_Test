# HDDM (Hierarchical Drift Diffusion Model) 解析

`analyze_training_effect.py` (EZ-DDM 版) の並行実装。同じ `trial_log.csv` を入力に、
階層ベイズで DDM パラメータ (v, a, t) を推定し、群間・フェーズ間比較を事後分布で報告する。

## EZ-DDM 版との違い

| | EZ-DDM (`analyze_training_effect.py`) | HDDM (`analyze_training_effect_hddm.py`) |
|---|---|---|
| 推定法 | 閉形式 (Wagenmakers et al. 2007) | 階層ベイズ MCMC (PyMC 2) |
| 出力 | 点推定 + t 検定 p 値 | 事後分布 + HDI + 事後確率 |
| 部分プーリング | なし (被験者独立) | あり (試行数少でも推定安定) |
| 誤答試行 | 正答率にのみ使用 | RT 尤度計算に直接使用 |
| 刺激側の分離 | 不可 (全試行プール) | StimCoding で Left/Right 分離 |
| 実行時間 | 数秒 | 10000 samples で 10-30 分 |
| 依存 | numpy, scipy, statsmodels | HDDM (Docker 推奨) |

両者を並行実行し、結論が一致すれば robustness が高い。齟齬があれば EZ の仮定
(等分散・正規近似) を疑う材料になる。

## 実行環境

HDDM は Python 3.7-3.9 と PyMC 2 に依存し、OS によっては native build が難しい。
**Docker image `hcp4715/hddm` の利用を推奨**する。

### Docker (推奨)

```powershell
# Reaction_Test プロジェクトルートで
docker run -it --rm `
  -v ${PWD}:/home/jovyan/work `
  -p 8888:8888 `
  hcp4715/hddm:latest
```

コンテナ起動後、表示された URL (例: `http://127.0.0.1:8888/lab?token=...`) を
ブラウザで開き、Jupyter Lab から Terminal を起動して以下を実行:

```bash
cd /home/jovyan/work/Analysis
python analyze_training_effect_hddm.py \
  --data_dir ../ExperimentData \
  --outdir ./results_hddm \
  --samples 10000 --burn 2000 --thin 2
```

### conda (Windows でネイティブ環境を作りたい場合)

```bash
conda create -n hddm python=3.9
conda activate hddm
pip install cython numpy==1.22 scipy==1.6.3 pandas==1.4 pymc==2.3.8
pip install git+https://github.com/hddm-devs/kabuki
pip install git+https://github.com/hddm-devs/hddm
pip install matplotlib seaborn
```

## 主要な仮説とそれに対応する出力

| 仮説 | 出力で見るべき値 |
|---|---|
| H1: AgencyEMS 群の ΔRT が Voluntary 群より大 | `observed_rt_deltas.csv` の群別平均差 |
| H2: AgencyEMS 群で Δt が負 (非決定時間短縮) | `hddm_results.json` の `group_deltas.AgencyEMS.t.p_reduction` |
| H3: Δa は群間差なし (速度-正答率トレードオフ否定) | `hddm_results.json` の `group_comparison.a.hdi_low/high` が 0 を含むか |
| 分解: Δt は ΔRT の何割を説明するか | `frac_t_of_rt.csv` + `hddm_frac_t.png` |

## 出力ファイル

| ファイル | 内容 |
|---|---|
| `hddm_input.csv` | HDDM に投入した整形済みデータ (デバッグ用) |
| `hddm_stats_<group>.csv` | HDDM の `gen_stats()` 全パラメータ要約 |
| `hddm_model_<group>` | 保存済みモデル (`hddm.load()` で再利用可) |
| `traces_<group>.db` | MCMC trace (pickle) |
| `subject_traces_<group>.csv` | 被験者 × param × Phase の事後要約 |
| `observed_rt_deltas.csv` | 被験者ごとの観測 ΔRT (IQR フィルタ平均差) |
| `frac_t_of_rt.csv` | 被験者ごとの Δt / ΔRT |
| `hddm_group_delta_posteriors.png` | 群レベル Δv, Δa, Δt の事後分布 |
| `hddm_subject_deltas.png` | 被験者レベル Δ のボックスプロット |
| `hddm_frac_t.png` | frac_t の群別分布 |
| `hddm_results.json` | JSON レポート (trace なし、要約統計のみ) |

## パラメータ決定の指針

### MCMC サンプル数

| 用途 | samples | burn | thin | 所要時間目安 |
|---|---|---|---|---|
| パイプライン動作確認 | 1000 | 200 | 1 | 1-3 分 |
| 予備分析 | 3000 | 500 | 1 | 5-10 分 |
| 本番 (推奨) | 10000 | 2000 | 2 | 15-30 分 |
| 高精度 | 20000 | 5000 | 5 | 30-60 分 |

被験者数 × 試行数に比例してスケールするため、パイロット段階では小さめから始める。
収束診断 (Gelman-Rubin R̂) は `hddm_stats_<group>.csv` の `mc err` 列が平均値の
1% 未満であれば OK の目安。

### p_outlier

デフォルト 0.05 (5% の試行が contaminant 分布由来と仮定)。CRT では早押し
(100ms 未満) を `min_rt` で除外済みなので 0.05 で十分。タイムアウト試行が
多い場合 (>10%) は 0.10 に上げる。

## モデル構造

```
HDDMStimCoding(
    stim_col='stim',           # 'Left' / 'Right'
    split_param='v',            # stim='Right' 試行で drift 符号反転
    depends_on={
        'v': 'Phase',           # Baseline / PostTest で別 drift rate
        'a': 'Phase',           # 同じく boundary
        't': 'Phase',           # 同じく non-decision time
    },
    p_outlier=0.05,
)
```

**stimulus coding の意味**: CRT では左刺激と右刺激は対称。同じ v で表現するため、
右刺激の試行は drift 方向を反転させて尤度を計算する。これにより左右の試行を
1 つの `v(Phase)` パラメータで扱える。もし「左右で効きが違う」と予想するなら、
`depends_on['v'] = ['stim', 'Phase']` に変更する。

**群間比較は別モデルで fit**: AgencyEMS と Voluntary は被験者間デザインなので、
同じ階層内に混ぜるより群ごとに別モデルとして fit し、得られた事後分布同士を
比較する方が解釈が素直になる (両群の hyperprior を独立にできる)。

## トラブルシュート

- **`AssertionError: One of the column names specified via depends_on was not picked up`**
  → data の Phase 列の値が 'Baseline'/'PostTest' 以外を含んでいる可能性。
     `preprocess_for_hddm` が正しくフィルタしているか確認。

- **`invalid value encountered in double_scalars`**
  → `find_starting_values()` 内の警告。無視してよい。サンプリングは継続する。

- **メモリ不足 (Docker)**
  → `%USERPROFILE%\.wslconfig` に以下を記述して `wsl --shutdown`:
     ```ini
     [wsl2]
     memory=8GB
     processors=4
     ```

- **trace 保存に失敗**
  → `--outdir` 配下の書き込み権限を確認。Docker の場合は
     `-v ${PWD}:/home/jovyan/work` でマウントした側のフォルダに書いているか確認。
