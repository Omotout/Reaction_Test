"""
analyze_training_effect_hddm.py — V3 CRT特化 + 階層ベイズ DDM (HDDM) 解析

`analyze_training_effect.py` (EZ-DDM) の並行版。入力 CSV は同一フォーマット。

階層ベイズ推定の利点:
  1. 部分プーリング: 試行数の少ない被験者の推定が群分布により安定化
  2. 不確実性の明示: 点推定ではなく事後分布 → 「群間差の事後確率」で報告可能
  3. 刺激側別の drift rate: HDDMStimCoding で Left/Right 刺激に対する v を分離
  4. 階層モデル比較: DIC による「どのパラメータが条件で変わるか」の定量評価

検定プラン:
  EZ-DDM 版の 6 本の仮説検定と対応する形で HDDM 事後分布を要約する。
  事後確率 (P(Δ<0 | data) など) と 95% 信用区間 (HDI) を報告。

  1a. ΔRT (秒)            : AgencyEMS vs Voluntary (観察指標、既存解析と同じ)
  1b. ΔAccuracy           : AgencyEMS vs Voluntary (既存解析と同じ)
  2a. Δa (決定閾値)        : 群間差なしの事後確率 → トレードオフ否定の強化
  2b. Δt (非決定時間, 秒)  : EMS群で有意な短縮 → 運動プライミング
  2c. Δv (ドリフト率)      : 観察 (左右刺激で符号反転するため絶対値で評価)

分解指標:
  frac_t = Δt / ΔRT (被験者ごとの事後平均から算出)

モデル:
  HDDMStimCoding(stim_col='stim', split_param='v', drift_criterion=False)
  depends_on = {'v': 'Phase', 'a': 'Phase', 't': 'Phase'}
    - 刺激側 (Left/Right) ごとに v の符号が反転するため StimCoding を使用
    - Phase (Baseline/PostTest) で v, a, t が変化することを許す
    - 被験者間要因 (Group) は被験者ID 自体に埋め込まれているため、
      群ごとに別モデルを fit して事後分布を比較する

使用例:
  python analyze_training_effect_hddm.py \\
    --data_dir ../ExperimentData \\
    --outdir ./results_hddm \\
    --samples 10000 --burn 2000

  # 高速テスト:
  python analyze_training_effect_hddm.py \\
    --data_dir ../ExperimentData \\
    --outdir ./results_hddm \\
    --samples 2000 --burn 500

注意:
  HDDM は Python 3.7–3.9 かつ PyMC 2 に依存するため、Docker image
  (hcp4715/hddm) の中で実行することを推奨。
"""
import argparse
import json
import re
import warnings
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

try:
    import hddm
    import kabuki
    HAS_HDDM = True
except ImportError:
    HAS_HDDM = False


# =====================================================================
# データ読み込み & HDDM 形式への変換
# =====================================================================

def load_all_subjects(data_dir: Path) -> pd.DataFrame:
    """全被験者の全セッションの trial_log.csv を結合して返す (EZ 版と同じ)。"""
    all_data = []
    for subject_dir in sorted(data_dir.iterdir()):
        if not subject_dir.is_dir():
            continue
        for session_dir in sorted(subject_dir.glob("session_*")):
            trial_log = session_dir / "trial_log.csv"
            if trial_log.exists():
                # Unity 側で UTF-8 BOM 付きで書かれている場合がある
                all_data.append(pd.read_csv(trial_log, encoding="utf-8-sig"))
    if not all_data:
        raise ValueError(f"No trial_log.csv found under {data_dir}")
    return pd.concat(all_data, ignore_index=True, sort=False)


def preprocess_for_hddm(df: pd.DataFrame,
                        min_rt: float = 100, max_rt: float = 1000) -> pd.DataFrame:
    """HDDM 形式の DataFrame を返す。

    HDDM が期待する列:
      subj_idx  : 被験者の整数 ID (0-indexed, 群を跨いでユニーク)
      stim      : 'Left' / 'Right' (StimCoding が符号反転に使用)
      response  : 1 = 正答 (刺激側と一致), 0 = 誤答
      rt        : 反応時間 (秒)
      Phase     : 'Baseline' / 'PostTest'  (depends_on で使用)

    旧フォーマット (AgencyLikert 列のみ、EMSFireTiming_ms なし) にも対応。
    HDDM は正答 + 誤答 RT の両方を尤度計算に使うため、誤答試行も保持する。
    """
    df = df[df["Phase"].isin(["Baseline", "PostTest"])].copy()
    df["ReactionTime_ms"] = pd.to_numeric(df["ReactionTime_ms"], errors="coerce")
    df["IsCorrect"] = pd.to_numeric(df["IsCorrect"], errors="coerce").fillna(0).astype(int)
    df = df.dropna(subset=["ReactionTime_ms"])
    df = df[df["ReactionTime_ms"] > 0]  # タイムアウト(-1)を除外

    n0 = len(df)
    df = df[(df["ReactionTime_ms"] >= min_rt) & (df["ReactionTime_ms"] <= max_rt)].copy()
    print(f"Preprocess: {n0 - len(df)}/{n0} trials removed by RT bounds [{min_rt}, {max_rt}]ms")

    # タイムアウト (ResponseSide='None') を除外 (念のため)
    df = df[df["ResponseSide"].isin(["Left", "Right"])].copy()

    # Group が整数値 (0/1) で保存されているレガシーデータへの対応
    if df["Group"].dtype in (np.int64, np.int32, int, float):
        group_map = {0: "AgencyEMS", 1: "Voluntary"}
        df["Group"] = df["Group"].map(group_map).fillna(df["Group"].astype(str))

    # SubjectID → subj_idx 整数
    subj_map = {sid: i for i, sid in enumerate(sorted(df["SubjectID"].unique()))}
    hddm_df = pd.DataFrame({
        "subj_idx": df["SubjectID"].map(subj_map).astype(int),
        "SubjectID": df["SubjectID"].astype(str),
        "Group": df["Group"].astype(str),
        "stim": df["TargetSide"],  # 'Left' / 'Right'
        "response": df["IsCorrect"].astype(int),  # 1=correct, 0=error
        "rt": df["ReactionTime_ms"].astype(float) / 1000.0,  # 秒単位
        "Phase": df["Phase"],
    })
    return hddm_df.reset_index(drop=True)


# =====================================================================
# HDDM フィット (群ごとに別モデル)
# =====================================================================

def fit_hddm_for_group(group_df: pd.DataFrame, group_name: str,
                       samples: int, burn: int, thin: int,
                       out_dir: Path) -> dict:
    """ある群のデータに対して HDDMStimCoding をフィットし結果を返す。

    depends_on:
      v: ['stim', 'Phase']  — 刺激側 × フェーズで 4 水準
         (StimCoding により stim の 'Right' が v の符号反転に対応)
      a: 'Phase'            — フェーズで 2 水準
      t: 'Phase'            — フェーズで 2 水準

    Returns: 被験者レベル・群レベルの事後サンプルを整理した dict
    """
    if not HAS_HDDM:
        raise RuntimeError("hddm package is not available. Run inside the HDDM docker image.")

    print(f"\n--- Fitting HDDM for group: {group_name} ---")
    print(f"  n_subjects={group_df['subj_idx'].nunique()}  "
          f"n_trials={len(group_df)}  "
          f"samples={samples} burn={burn} thin={thin}")

    # HDDM が期待する最小カラムに絞る (余計な列があっても動くが明示)
    fit_df = group_df[["subj_idx", "stim", "response", "rt", "Phase"]].copy()

    # StimCoding: stim='Right' の試行では drift rate の符号を反転して尤度計算する
    # これにより左右刺激を 1 つの v(Phase) パラメータで記述できる
    model = hddm.HDDMStimCoding(
        fit_df,
        stim_col="stim",
        split_param="v",
        drift_criterion=False,
        include=["v", "a", "t"],
        depends_on={"v": "Phase", "a": "Phase", "t": "Phase"},
        p_outlier=0.05,
    )
    model.find_starting_values()
    model.sample(samples, burn=burn, thin=thin,
                 dbname=str(out_dir / f"traces_{group_name}.db"),
                 db="pickle")

    # 事後統計の保存
    stats_path = out_dir / f"hddm_stats_{group_name}.csv"
    model.gen_stats().to_csv(stats_path)
    print(f"  Saved: {stats_path}")

    # モデル本体も保存 (再利用可能)
    model_path = out_dir / f"hddm_model_{group_name}"
    try:
        model.save(str(model_path))
        print(f"  Saved model: {model_path}")
    except Exception as exc:
        print(f"  [WARN] model.save failed: {exc}")

    # 群レベル事後サンプルを抽出
    group_traces = extract_group_traces(model)
    subj_traces = extract_subject_traces(model, fit_df)

    return {
        "group_name": group_name,
        "n_subjects": int(group_df["subj_idx"].nunique()),
        "n_trials": int(len(group_df)),
        "model": model,
        "group_traces": group_traces,
        "subject_traces": subj_traces,
        "dic": float(model.dic) if hasattr(model, "dic") else None,
    }


def extract_group_traces(model) -> dict:
    """群レベル (hyperprior mean) の v, a, t × Phase の事後サンプルを辞書で返す。

    HDDM 1.0 系のノード命名規則 (hddm_stats で確認済み):
      群レベル:   'v(Baseline)'     'a(PostTest)'     't(Baseline)'
      被験者:     'v_subj(Baseline).0'  'a_subj(PostTest).9'
    """
    traces = {}
    for param in ["v", "a", "t"]:
        for phase in ["Baseline", "PostTest"]:
            node_name = f"{param}({phase})"
            try:
                node = model.nodes_db.node[node_name]
            except (KeyError, AttributeError):
                continue
            if not hasattr(node, "trace") or node.trace() is None:
                continue
            traces[f"{param}_{phase}"] = np.asarray(node.trace())
    return traces


# 被験者レベルノード名のパターン: 'v_subj(Baseline).0', 'a_subj(PostTest).9'
_SUBJ_NODE_RE = re.compile(r"^([vat])_subj\((Baseline|PostTest)\)\.(\d+)$")


def extract_subject_traces(model, fit_df: pd.DataFrame) -> pd.DataFrame:
    """被験者 × パラメータ × フェーズ の事後平均・SD・HDI を long-form で返す。

    nodes_db のインデックス名を直接パースする (HDDM 1.0.1RC で確認済み)。
    期待ノード名: '<param>_subj(<Phase>).<subj_idx>'
    """
    rows = []
    for node_name in model.nodes_db.index:
        match = _SUBJ_NODE_RE.match(str(node_name))
        if not match:
            continue
        param, phase, subj_idx_str = match.groups()
        try:
            node = model.nodes_db.node[node_name]
        except (KeyError, AttributeError):
            continue
        if not hasattr(node, "trace") or node.trace() is None:
            continue
        trace = np.asarray(node.trace())
        rows.append({
            "subj_idx": int(subj_idx_str),
            "param": param,
            "Phase": phase,
            "mean": float(np.mean(trace)),
            "sd": float(np.std(trace)),
            "hdi_low": float(np.percentile(trace, 2.5)),
            "hdi_high": float(np.percentile(trace, 97.5)),
        })
    if not rows:
        # 空 DataFrame を返すときも列を揃える (下流で KeyError にしないため)
        return pd.DataFrame(columns=["subj_idx", "param", "Phase",
                                     "mean", "sd", "hdi_low", "hdi_high"])
    return pd.DataFrame(rows)


# =====================================================================
# 事後要約: 群内 Δ (Post - Base), 群間比較, 寄与率
# =====================================================================

def _posterior_summary(diff: np.ndarray) -> dict:
    """事後サンプルの要約統計を辞書で返す (trace 付き)。"""
    return {
        "trace": diff,
        "mean": float(np.mean(diff)),
        "sd": float(np.std(diff)),
        "hdi_low": float(np.percentile(diff, 2.5)),
        "hdi_high": float(np.percentile(diff, 97.5)),
        "p_reduction": float(np.mean(diff < 0)),   # P(Δ < 0 | data)
        "p_increase": float(np.mean(diff > 0)),    # P(Δ > 0 | data)
    }


def _decision_time(a: np.ndarray, v: np.ndarray) -> np.ndarray:
    """DDM の平均決定時間: DT = (a / 2v) · tanh(av / 2)。

    v が 0 に近い場合は NaN を返す。
    """
    with np.errstate(divide="ignore", invalid="ignore"):
        dt = (a / (2.0 * v)) * np.tanh(v * a / 2.0)
    return dt


def compute_group_deltas(group_traces: dict) -> dict:
    """群レベルの Δ = PostTest − Baseline 事後サンプルと HDI/事後確率を返す。

    v, a, t の直接パラメータに加え、H2d の Δ決定時間 (decision_time) を
    a と v の事後サンプルから派生計算する。
    """
    deltas = {}
    for param in ["v", "a", "t"]:
        key_post = f"{param}_PostTest"
        key_base = f"{param}_Baseline"
        if key_post not in group_traces or key_base not in group_traces:
            continue
        diff = group_traces[key_post] - group_traces[key_base]
        deltas[param] = _posterior_summary(diff)

    # H2d: Δ決定時間 = DT(PostTest) − DT(Baseline)
    required = [f"{p}_{ph}" for p in ["a", "v"] for ph in ["Baseline", "PostTest"]]
    if all(k in group_traces for k in required):
        dt_base = _decision_time(group_traces["a_Baseline"],
                                 group_traces["v_Baseline"])
        dt_post = _decision_time(group_traces["a_PostTest"],
                                 group_traces["v_PostTest"])
        diff_dt = dt_post - dt_base
        valid = np.isfinite(diff_dt)
        if valid.sum() > 100:
            deltas["decision_time"] = _posterior_summary(diff_dt[valid])

    return deltas


def compare_groups_posterior(delta_a: dict, delta_b: dict,
                             name_a: str, name_b: str) -> dict:
    """2 群の Δ 事後分布から、差の事後分布を独立サンプル仮定で構成。"""
    results = {}
    for param in ["v", "a", "t", "decision_time"]:
        if param not in delta_a or param not in delta_b:
            continue
        # 独立なチェーンなので、長さを揃えてペアリング (random shuffle は不要、
        # 両者とも同じ長さ・同じ事後から独立に引かれているとみなせるため単純差分でよい)
        trace_a = delta_a[param]["trace"]
        trace_b = delta_b[param]["trace"]
        n = min(len(trace_a), len(trace_b))
        rng = np.random.default_rng(0)  # 再現性
        # より厳密には独立サンプル同士の差を表すため、両方をシャッフルして差を取る
        idx_a = rng.permutation(len(trace_a))[:n]
        idx_b = rng.permutation(len(trace_b))[:n]
        diff = trace_a[idx_a] - trace_b[idx_b]

        results[param] = {
            "mean_diff": float(np.mean(diff)),
            "sd_diff": float(np.std(diff)),
            "hdi_low": float(np.percentile(diff, 2.5)),
            "hdi_high": float(np.percentile(diff, 97.5)),
            "p_a_larger_reduction": float(np.mean(diff < 0)),
            "p_a_smaller_reduction": float(np.mean(diff > 0)),
            "description": f"({name_a} Δ{param}) − ({name_b} Δ{param})",
        }
    return results


def compute_frac_decision_per_subject(subj_traces_a: pd.DataFrame,
                                      subj_traces_b: pd.DataFrame,
                                      rt_deltas_ms: pd.DataFrame) -> pd.DataFrame:
    """被験者ごとに frac_decision = Δ決定時間_s * 1000 / ΔRT_ms を算出。

    Δ決定時間は a, v の事後平均から DT = (a/2v)·tanh(av/2) で派生計算。
    """
    cols = ["subj_idx", "Group", "delta_decision_time_s",
            "delta_rt_ms", "frac_decision"]
    rows = []
    for subj_traces in (subj_traces_a, subj_traces_b):
        if subj_traces is None or subj_traces.empty:
            continue
        for subj in subj_traces["subj_idx"].unique():
            sd = subj_traces[subj_traces["subj_idx"] == subj]

            def _get_mean(param, phase):
                r = sd[(sd["param"] == param) & (sd["Phase"] == phase)]
                return float(r.iloc[0]["mean"]) if not r.empty else None

            a_b, a_p = _get_mean("a", "Baseline"), _get_mean("a", "PostTest")
            v_b, v_p = _get_mean("v", "Baseline"), _get_mean("v", "PostTest")
            if any(x is None for x in [a_b, a_p, v_b, v_p]):
                continue
            if abs(v_b) < 1e-6 or abs(v_p) < 1e-6:
                continue

            dt_b = (a_b / (2 * v_b)) * np.tanh(v_b * a_b / 2)
            dt_p = (a_p / (2 * v_p)) * np.tanh(v_p * a_p / 2)
            delta_dt = dt_p - dt_b

            rt_row = rt_deltas_ms[rt_deltas_ms["subj_idx"] == subj]
            if rt_row.empty:
                continue
            drt_ms = float(rt_row.iloc[0]["delta_rt_ms"])
            group = rt_row.iloc[0]["Group"]
            if not np.isfinite(drt_ms) or abs(drt_ms) < 1e-6:
                continue

            rows.append({
                "subj_idx": int(subj),
                "Group": group,
                "delta_decision_time_s": delta_dt,
                "delta_rt_ms": drt_ms,
                "frac_decision": (delta_dt * 1000.0) / drt_ms,
            })
    if not rows:
        return pd.DataFrame(columns=cols)
    return pd.DataFrame(rows)


def compute_frac_t_per_subject(subj_traces_a: pd.DataFrame,
                               subj_traces_b: pd.DataFrame,
                               rt_deltas_ms: pd.DataFrame) -> pd.DataFrame:
    """被験者ごとに frac_t = Δt_s * 1000 / ΔRT_ms を算出。

    Δt_s は HDDM 事後平均、ΔRT_ms は観測 (IQR フィルタ平均) を使用。
    rt_deltas_ms は ['subj_idx', 'Group', 'delta_rt_ms'] を持つ DataFrame。
    """
    cols = ["subj_idx", "Group", "delta_t_s", "delta_rt_ms", "frac_t_of_rt"]
    rows = []
    for subj_traces in (subj_traces_a, subj_traces_b):
        if subj_traces is None or subj_traces.empty:
            continue
        t_traces = subj_traces[subj_traces["param"] == "t"]
        for subj in t_traces["subj_idx"].unique():
            base = t_traces[(t_traces["subj_idx"] == subj) &
                            (t_traces["Phase"] == "Baseline")]
            post = t_traces[(t_traces["subj_idx"] == subj) &
                            (t_traces["Phase"] == "PostTest")]
            if base.empty or post.empty:
                continue
            dt_s = post.iloc[0]["mean"] - base.iloc[0]["mean"]
            rt_row = rt_deltas_ms[rt_deltas_ms["subj_idx"] == subj]
            if rt_row.empty:
                continue
            drt_ms = float(rt_row.iloc[0]["delta_rt_ms"])
            if not np.isfinite(drt_ms) or abs(drt_ms) < 1e-6:
                continue
            rows.append({
                "subj_idx": int(subj),
                "Group": rt_row.iloc[0]["Group"],
                "delta_t_s": dt_s,
                "delta_rt_ms": drt_ms,
                "frac_t_of_rt": (dt_s * 1000.0) / drt_ms,
            })
    if not rows:
        return pd.DataFrame(columns=cols)
    return pd.DataFrame(rows)


def compute_observed_rt_deltas(hddm_df: pd.DataFrame) -> pd.DataFrame:
    """被験者ごとに ΔRT_ms (PostTest − Baseline の正答 IQR-平均差) を返す。

    EZ-DDM 版 compute_deltas と整合させるため、同じ IQR フィルタを適用する。
    """
    from scipy import stats  # local import to avoid hard dep at module load

    def iqr_filtered_mean(rts: np.ndarray, k: float = 1.5) -> Optional[float]:
        rts = np.asarray(rts)
        if len(rts) == 0:
            return None
        if len(rts) < 4:
            return float(np.mean(rts))
        q1, q3 = np.quantile(rts, [0.25, 0.75])
        iqr = q3 - q1
        kept = rts[(rts >= q1 - k * iqr) & (rts <= q3 + k * iqr)]
        if len(kept) == 0:
            return float(np.median(rts))
        return float(np.mean(kept))

    rows = []
    for (subj, group), g in hddm_df.groupby(["subj_idx", "Group"]):
        base = g[(g["Phase"] == "Baseline") & (g["response"] == 1)]["rt"].to_numpy() * 1000
        post = g[(g["Phase"] == "PostTest") & (g["response"] == 1)]["rt"].to_numpy() * 1000
        mean_b = iqr_filtered_mean(base)
        mean_p = iqr_filtered_mean(post)
        if mean_b is None or mean_p is None:
            continue
        rows.append({
            "subj_idx": int(subj), "Group": group,
            "baseline_rt_ms": mean_b, "posttest_rt_ms": mean_p,
            "delta_rt_ms": mean_p - mean_b,
        })
    return pd.DataFrame(rows)


# =====================================================================
# プロット
# =====================================================================

def plot_group_posteriors(deltas_a: dict, deltas_b: dict,
                          name_a: str, name_b: str, out_path: Path) -> None:
    """群レベル Δv, Δa, Δt, Δ決定時間 の事後分布を比較プロット。"""
    params = ["v", "a", "t", "decision_time"]
    param_labels = {"v": "Δv", "a": "Δa", "t": "Δt",
                    "decision_time": "ΔDecisionTime"}
    param_units = {"t": " (s)", "decision_time": " (s)"}
    fig, axes = plt.subplots(2, 2, figsize=(14, 9))
    for ax, param in zip(axes.flatten(), params):
        label = param_labels.get(param, f"Δ{param}")
        if param not in deltas_a or param not in deltas_b:
            ax.set_title(f"{label} — no data")
            continue
        trace_a = deltas_a[param]["trace"]
        trace_b = deltas_b[param]["trace"]

        ax.hist(trace_a, bins=50, alpha=0.55, color="steelblue",
                density=True, label=f"{name_a} (mean={np.mean(trace_a):+.3f})")
        ax.hist(trace_b, bins=50, alpha=0.55, color="coral",
                density=True, label=f"{name_b} (mean={np.mean(trace_b):+.3f})")
        ax.axvline(0, color="gray", ls="--", alpha=0.5)
        unit = param_units.get(param, "")
        ax.set_xlabel(f"{label}{unit}   PostTest − Baseline")
        ax.set_ylabel("Posterior density")
        p_a = deltas_a[param]["p_reduction"]
        p_b = deltas_b[param]["p_reduction"]
        ax.set_title(f"{label}    P(Δ<0): {name_a}={p_a:.3f}, {name_b}={p_b:.3f}")
        ax.legend(fontsize=9)
    plt.suptitle(f"Group-level Δ posteriors: {name_a} vs {name_b}")
    plt.tight_layout()
    plt.savefig(out_path, dpi=180)
    plt.close()


def plot_subject_deltas(subj_a: pd.DataFrame, subj_b: pd.DataFrame,
                        name_a: str, name_b: str, out_path: Path) -> None:
    """被験者レベルの Δv, Δa, Δt を群別 box + strip で比較。"""
    records = []
    for df, name in [(subj_a, name_a), (subj_b, name_b)]:
        if df.empty:
            continue
        for param in ["v", "a", "t"]:
            pivot = df[df["param"] == param].pivot_table(
                index="subj_idx", columns="Phase", values="mean").dropna()
            if pivot.empty or "PostTest" not in pivot.columns:
                continue
            for subj_idx, row in pivot.iterrows():
                records.append({
                    "Group": name, "param": param,
                    "subj_idx": subj_idx,
                    "delta": row["PostTest"] - row["Baseline"],
                })
    if not records:
        return
    delta_df = pd.DataFrame(records)

    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    for ax, param in zip(axes, ["v", "a", "t"]):
        d = delta_df[delta_df["param"] == param]
        if d.empty:
            ax.set_title(f"Δ{param} — no data")
            continue
        sns.boxplot(data=d, x="Group", y="delta", ax=ax,
                    hue="Group", palette="Set2", legend=False,
                    order=[name_a, name_b])
        sns.stripplot(data=d, x="Group", y="delta", ax=ax, color="black",
                      alpha=0.6, jitter=True, order=[name_a, name_b])
        ax.axhline(0, color="gray", ls="--", alpha=0.5)
        unit = " (s)" if param == "t" else ""
        ax.set_title(f"Subject-level Δ{param}{unit}  (posterior means)")
    plt.suptitle("Subject-level Δ parameters from HDDM posterior means")
    plt.tight_layout()
    plt.savefig(out_path, dpi=180)
    plt.close()


def plot_frac_t(frac_df: pd.DataFrame, out_path: Path) -> None:
    """群ごとの frac_t = Δt / ΔRT 分布。"""
    if frac_df.empty:
        return
    fig, ax = plt.subplots(figsize=(8, 5.5))
    sns.boxplot(data=frac_df, x="Group", y="frac_t_of_rt", ax=ax,
                hue="Group", palette="Set2", legend=False)
    sns.stripplot(data=frac_df, x="Group", y="frac_t_of_rt", ax=ax,
                  color="black", alpha=0.6, jitter=True)
    ax.axhline(0, color="gray", ls="--", alpha=0.5)
    ax.axhline(1, color="gray", ls=":", alpha=0.5)
    ax.set_ylabel("Δt / ΔRT  (proportion of RT change due to non-decision time)")
    ax.set_title("Non-decision time contribution to total RT change\n"
                 "(HDDM subject-level posterior means)")
    plt.tight_layout()
    plt.savefig(out_path, dpi=180)
    plt.close()


# =====================================================================
# Main
# =====================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="CRT training effect via hierarchical Bayesian DDM (HDDM)")
    parser.add_argument("--data_dir", required=True, help="ExperimentData root")
    parser.add_argument("--outdir", required=True, help="Output directory")
    parser.add_argument("--min_rt", type=float, default=100)
    parser.add_argument("--max_rt", type=float, default=1000)
    parser.add_argument("--samples", type=int, default=10000,
                        help="MCMC samples per chain (default: 10000)")
    parser.add_argument("--burn", type=int, default=2000,
                        help="Burn-in samples (default: 2000)")
    parser.add_argument("--thin", type=int, default=2,
                        help="Thinning factor (default: 2)")
    parser.add_argument("--groups", nargs=2, default=["AgencyEMS", "Voluntary"],
                        help="Two group names to compare (default: AgencyEMS Voluntary)")
    args = parser.parse_args()

    if not HAS_HDDM:
        raise RuntimeError(
            "HDDM package not available. This script must be run inside the "
            "HDDM docker image (hcp4715/hddm) or an equivalent Python 3.7-3.9 "
            "environment with hddm, kabuki, and pymc<3 installed.")

    data_dir = Path(args.data_dir)
    out_dir = Path(args.outdir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Loading subject data...")
    raw = load_all_subjects(data_dir)
    print(f"Loaded {len(raw)} trials, {raw['SubjectID'].nunique()} subjects")

    hddm_df = preprocess_for_hddm(raw, args.min_rt, args.max_rt)
    print(f"After preprocessing: {len(hddm_df)} trials, "
          f"{hddm_df['subj_idx'].nunique()} subjects, "
          f"groups={hddm_df['Group'].unique().tolist()}")
    hddm_df.to_csv(out_dir / "hddm_input.csv", index=False)

    # === 群ごとに HDDM フィット ===
    group_a_name, group_b_name = args.groups
    group_a_df = hddm_df[hddm_df["Group"] == group_a_name]
    group_b_df = hddm_df[hddm_df["Group"] == group_b_name]

    if group_a_df.empty or group_b_df.empty:
        raise ValueError(
            f"One of the groups has no data: "
            f"{group_a_name}={len(group_a_df)}, {group_b_name}={len(group_b_df)}")

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=RuntimeWarning)
        fit_a = fit_hddm_for_group(group_a_df, group_a_name,
                                   args.samples, args.burn, args.thin, out_dir)
        fit_b = fit_hddm_for_group(group_b_df, group_b_name,
                                   args.samples, args.burn, args.thin, out_dir)

    # === Δ 計算 ===
    print("\n[Analysis] Computing group-level Δ posteriors...")
    delta_a = compute_group_deltas(fit_a["group_traces"])
    delta_b = compute_group_deltas(fit_b["group_traces"])

    print(f"\n=== {group_a_name} group-level Δ (PostTest − Baseline) ===")
    for param, d in delta_a.items():
        print(f"  Δ{param}: mean={d['mean']:+.4f}  "
              f"HDI=[{d['hdi_low']:+.4f}, {d['hdi_high']:+.4f}]  "
              f"P(Δ<0)={d['p_reduction']:.3f}")

    print(f"\n=== {group_b_name} group-level Δ (PostTest − Baseline) ===")
    for param, d in delta_b.items():
        print(f"  Δ{param}: mean={d['mean']:+.4f}  "
              f"HDI=[{d['hdi_low']:+.4f}, {d['hdi_high']:+.4f}]  "
              f"P(Δ<0)={d['p_reduction']:.3f}")

    # === 群間比較 ===
    print(f"\n=== Group comparison: ({group_a_name} Δ) − ({group_b_name} Δ) ===")
    group_diff = compare_groups_posterior(delta_a, delta_b, group_a_name, group_b_name)
    for param, r in group_diff.items():
        print(f"  {param}: diff={r['mean_diff']:+.4f}  "
              f"HDI=[{r['hdi_low']:+.4f}, {r['hdi_high']:+.4f}]  "
              f"P({group_a_name} larger reduction)={r['p_a_larger_reduction']:.3f}")

    # === 被験者レベル ΔRT 計算 + frac_t + frac_decision ===
    rt_deltas = compute_observed_rt_deltas(hddm_df)
    rt_deltas.to_csv(out_dir / "observed_rt_deltas.csv", index=False)

    frac_df = compute_frac_t_per_subject(
        fit_a["subject_traces"], fit_b["subject_traces"], rt_deltas)
    frac_df.to_csv(out_dir / "frac_t_of_rt.csv", index=False)
    print(f"\n=== frac_t = Δt / ΔRT (subject-level, HDDM posterior means) ===")
    if frac_df.empty or "Group" not in frac_df.columns:
        print("  (no subject-level Δt available — check subject_traces extraction)")
    else:
        for group_name in [group_a_name, group_b_name]:
            g = frac_df[frac_df["Group"] == group_name]
            if len(g) == 0:
                continue
            vals = g["frac_t_of_rt"].replace([np.inf, -np.inf], np.nan).dropna()
            if len(vals) == 0:
                continue
            print(f"  {group_name}: mean={vals.mean():+.3f}  "
                  f"median={vals.median():+.3f}  n={len(vals)}")

    # H2d: frac_decision = Δ決定時間 / ΔRT
    frac_dec_df = compute_frac_decision_per_subject(
        fit_a["subject_traces"], fit_b["subject_traces"], rt_deltas)
    frac_dec_df.to_csv(out_dir / "frac_decision_of_rt.csv", index=False)
    print(f"\n=== frac_decision = Δ決定時間 / ΔRT (subject-level) ===")
    if frac_dec_df.empty or "Group" not in frac_dec_df.columns:
        print("  (no subject-level decision time available)")
    else:
        for group_name in [group_a_name, group_b_name]:
            g = frac_dec_df[frac_dec_df["Group"] == group_name]
            if len(g) == 0:
                continue
            vals = g["frac_decision"].replace([np.inf, -np.inf], np.nan).dropna()
            if len(vals) == 0:
                continue
            print(f"  {group_name}: mean={vals.mean():+.3f}  "
                  f"median={vals.median():+.3f}  n={len(vals)}")

    # === プロット ===
    print("\n[Plots] Saving figures...")
    plot_group_posteriors(delta_a, delta_b, group_a_name, group_b_name,
                          out_dir / "hddm_group_delta_posteriors.png")
    plot_subject_deltas(fit_a["subject_traces"], fit_b["subject_traces"],
                        group_a_name, group_b_name,
                        out_dir / "hddm_subject_deltas.png")
    plot_frac_t(frac_df, out_dir / "hddm_frac_t.png")

    # 被験者レベル事後統計の保存
    fit_a["subject_traces"].to_csv(out_dir / f"subject_traces_{group_a_name}.csv",
                                   index=False)
    fit_b["subject_traces"].to_csv(out_dir / f"subject_traces_{group_b_name}.csv",
                                   index=False)

    # === JSON レポート ===
    def _trace_free(d):
        """trace はサイズが大きいので JSON には書かない"""
        return {k: {kk: vv for kk, vv in v.items() if kk != "trace"}
                for k, v in d.items()}

    report = {
        "n_subjects_total": int(hddm_df["subj_idx"].nunique()),
        "n_per_group": {
            group_a_name: int(group_a_df["subj_idx"].nunique()),
            group_b_name: int(group_b_df["subj_idx"].nunique()),
        },
        "n_trials_total": int(len(hddm_df)),
        "hddm_version": hddm.__version__,
        "mcmc": {"samples": args.samples, "burn": args.burn, "thin": args.thin},
        "group_deltas": {
            group_a_name: _trace_free(delta_a),
            group_b_name: _trace_free(delta_b),
        },
        "group_comparison": group_diff,
        "dic": {group_a_name: fit_a["dic"], group_b_name: fit_b["dic"]},
    }
    (out_dir / "hddm_results.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8")
    print(f"\nDone. Results: {out_dir}")


if __name__ == "__main__":
    main()
