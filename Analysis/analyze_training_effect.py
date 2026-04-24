"""
analyze_training_effect.py — V3 CRT特化 + EZ-DDM 解析

検定プラン（6本をBH-FDR一括補正）:
  目的1 (RT短縮 + 速度-正答率トレードオフ否定)
    1a. ΔRT         : AgencyEMS vs Voluntary (期待: EMS群で有意に大きな短縮)
    1b. ΔAccuracy   : AgencyEMS vs Voluntary (期待: 正答率は悪化していない)
    1c. ΔIES        : AgencyEMS vs Voluntary (合成指標 RT/P_correct, 補助)
  目的2 (決定時間 / 非決定時間への分解)
    2a. Δa (決定閾値)   : 群間差なし → トレードオフ否定の機序的補強
    2b. Δt (非決定時間) : EMS群で有意な短縮 → 運動プライミング
    2c. Δv (ドリフト率) : 観察(仮説なし)
  分解指標
    frac_t = Δt / ΔRT : RT短縮のうち非決定時間由来の割合 (被験者ごと)

要約統計:
  RT は IQR フィルタ (Q1 - 1.5·IQR, Q3 + 1.5·IQR) 適用後の平均
  正答試行のみ (タイムアウト RT=-1 は事前除外)

DDM 推定:
  EZ-DDM (Wagenmakers et al., 2007) による被験者×フェーズ毎の点推定
  Edge correction (Snodgrass & Corwin, 1988): P_c==0/1 時は 1/(2N) で救済
  スケールパラメータ s = 0.1 (Wagenmakers 慣習)

使用例:
  python analyze_training_effect.py --data_dir ../ExperimentData --outdir ./results
"""
import argparse
import json
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests
import matplotlib.pyplot as plt
import seaborn as sns

try:
    import pingouin as pg
    HAS_PINGOUIN = True
except ImportError:
    HAS_PINGOUIN = False

EZ_SCALE = 0.1  # Wagenmakers EZ-DDM の慣習的スケール


# =====================================================================
# データ読み込み
# =====================================================================

def load_all_subjects(data_dir: Path) -> pd.DataFrame:
    """全被験者の全セッションの trial_log.csv を結合して返す"""
    all_data = []
    for subject_dir in sorted(data_dir.iterdir()):
        if not subject_dir.is_dir():
            continue
        for session_dir in sorted(subject_dir.glob("session_*")):
            trial_log = session_dir / "trial_log.csv"
            if trial_log.exists():
                all_data.append(pd.read_csv(trial_log))
    if not all_data:
        raise ValueError(f"No trial_log.csv found under {data_dir}")
    return pd.concat(all_data, ignore_index=True)


def preprocess(df: pd.DataFrame, min_rt: float = 100, max_rt: float = 1000) -> pd.DataFrame:
    """解析対象フェーズに絞り、タイムアウト・生理制約外の RT を除去。"""
    df = df[df["Phase"].isin(["Baseline", "PostTest"])].copy()
    df["ReactionTime_ms"] = pd.to_numeric(df["ReactionTime_ms"], errors="coerce")
    df["IsCorrect"] = pd.to_numeric(df["IsCorrect"], errors="coerce").fillna(0).astype(int)
    df = df.dropna(subset=["ReactionTime_ms"])
    df = df[df["ReactionTime_ms"] > 0]  # タイムアウト(-1)を除外
    n0 = len(df)
    df = df[(df["ReactionTime_ms"] >= min_rt) & (df["ReactionTime_ms"] <= max_rt)].copy()
    print(f"Preprocess: {n0 - len(df)}/{n0} trials removed by RT bounds [{min_rt}, {max_rt}]ms")
    return df


# =====================================================================
# IQR-filtered mean
# =====================================================================

def iqr_filtered_mean(rts: np.ndarray, k: float = 1.5) -> Optional[float]:
    """IQR フィルタ [Q1 - k·IQR, Q3 + k·IQR] を適用後の平均。データ不足時は None。"""
    rts = np.asarray(rts)
    if len(rts) < 4:
        return float(np.mean(rts)) if len(rts) > 0 else None
    q1, q3 = np.quantile(rts, [0.25, 0.75])
    iqr = q3 - q1
    lo, hi = q1 - k * iqr, q3 + k * iqr
    kept = rts[(rts >= lo) & (rts <= hi)]
    if len(kept) == 0:
        return float(np.median(rts))
    return float(np.mean(kept))


def iqr_filtered_var(rts: np.ndarray, k: float = 1.5) -> Optional[float]:
    """EZ-DDM 用: IQR フィルタ後の分散 (ddof=1)。"""
    rts = np.asarray(rts)
    if len(rts) < 4:
        return float(np.var(rts, ddof=1)) if len(rts) >= 2 else None
    q1, q3 = np.quantile(rts, [0.25, 0.75])
    iqr = q3 - q1
    lo, hi = q1 - k * iqr, q3 + k * iqr
    kept = rts[(rts >= lo) & (rts <= hi)]
    if len(kept) < 2:
        return float(np.var(rts, ddof=1))
    return float(np.var(kept, ddof=1))


# =====================================================================
# EZ-DDM (Wagenmakers et al., 2007)
# =====================================================================

def ez_ddm(p_correct: float, mean_rt_s: float, var_rt_s: float,
           n_total: int, s: float = EZ_SCALE) -> dict:
    """EZ-DDM 閉形式推定。RT は秒単位。

    Returns dict with keys: v, a, t, mdt, p_correct_adjusted, edge_corrected, valid, reason
    """
    result = {"v": None, "a": None, "t": None, "mdt": None,
              "p_correct_adjusted": p_correct, "edge_corrected": False,
              "valid": False, "reason": None}

    if n_total < 4 or var_rt_s is None or var_rt_s <= 0 or mean_rt_s <= 0:
        result["reason"] = f"insufficient data (n={n_total}, var={var_rt_s})"
        return result

    # Edge correction: P=0 or P=1 で logit が発散するのを救済
    p_adj = p_correct
    if p_correct >= 1.0:
        p_adj = 1.0 - 1.0 / (2.0 * n_total)
        result["edge_corrected"] = True
    elif p_correct <= 0.0:
        p_adj = 1.0 / (2.0 * n_total)
        result["edge_corrected"] = True

    if abs(p_adj - 0.5) < 1e-6:
        # P=0.5 では v の符号が定まらず推定不能
        result["reason"] = "P_correct == 0.5 (v not identifiable)"
        return result

    result["p_correct_adjusted"] = p_adj

    # Wagenmakers formula
    L = np.log(p_adj / (1.0 - p_adj))
    x = L * (L * p_adj**2 - L * p_adj + p_adj - 0.5) / var_rt_s
    if x <= 0:
        # 分散が大きすぎる or 正答率が 0.5 近傍で x が負
        result["reason"] = f"invalid x={x:.4f} (var_rt may be too large)"
        return result

    sign = 1.0 if p_adj > 0.5 else -1.0
    v = sign * s * x**0.25
    a = s**2 * L / v
    y = -v * a / (s**2)
    mdt = (a / (2.0 * v)) * ((1.0 - np.exp(y)) / (1.0 + np.exp(y)))
    t_er = mean_rt_s - mdt

    result.update({
        "v": float(v), "a": float(a), "t": float(t_er),
        "mdt": float(mdt), "valid": True,
    })
    return result


# =====================================================================
# 被験者×フェーズの要約統計 + EZ-DDM
# =====================================================================

def compute_subject_summaries(df: pd.DataFrame) -> pd.DataFrame:
    """被験者 × フェーズごとに RT/Accuracy/IES/EZ-DDM パラメータを算出。"""
    rows = []
    for (subj, group, phase), g in df.groupby(["SubjectID", "Group", "Phase"]):
        n_total = len(g)
        n_correct = int(g["IsCorrect"].sum())
        p_correct = n_correct / n_total if n_total > 0 else np.nan

        correct_rts_ms = g.loc[g["IsCorrect"] == 1, "ReactionTime_ms"].to_numpy()
        rt_mean = iqr_filtered_mean(correct_rts_ms)
        rt_var = iqr_filtered_var(correct_rts_ms)

        # IES = mean_RT / P_correct (low = efficient)
        ies = rt_mean / p_correct if (rt_mean is not None and p_correct and p_correct > 0) else np.nan

        # EZ-DDM (RT は秒単位で渡す)
        ez = ez_ddm(
            p_correct=p_correct,
            mean_rt_s=(rt_mean / 1000.0) if rt_mean is not None else np.nan,
            var_rt_s=(rt_var / (1000.0**2)) if rt_var is not None else np.nan,
            n_total=n_total,
        )

        rows.append({
            "SubjectID": subj, "Group": group, "Phase": phase,
            "n_total": n_total, "n_correct": n_correct, "p_correct": p_correct,
            "rt_mean_ms": rt_mean, "rt_var_ms2": rt_var,
            "ies_ms": ies,
            "ez_v": ez["v"], "ez_a": ez["a"], "ez_t_s": ez["t"], "ez_mdt_s": ez["mdt"],
            "ez_valid": ez["valid"], "ez_edge_corrected": ez["edge_corrected"],
            "ez_reason": ez["reason"],
        })
    return pd.DataFrame(rows)


def compute_deltas(summary: pd.DataFrame) -> pd.DataFrame:
    """PostTest - Baseline の Δ を被験者ごとに算出。

    各指標を個別に pivot して位置合わせで結合すると、欠損パターン次第で
    被験者行がずれて別被験者の値が混入する危険がある。Baseline と PostTest を
    SubjectID/Group で明示 merge してから差分を取る。
    """
    metrics = {
        "rt_ms": "rt_mean_ms",
        "acc": "p_correct",
        "ies_ms": "ies_ms",
        "v": "ez_v",
        "a": "ez_a",
        "t_s": "ez_t_s",
    }
    cols = ["SubjectID", "Group"] + list(metrics.values())

    baseline = (summary[summary["Phase"] == "Baseline"][cols]
                .drop_duplicates(subset=["SubjectID", "Group"]))
    posttest = (summary[summary["Phase"] == "PostTest"][cols]
                .drop_duplicates(subset=["SubjectID", "Group"]))

    merged = baseline.merge(
        posttest,
        on=["SubjectID", "Group"],
        how="outer",
        suffixes=("_baseline", "_posttest"),
    )

    out = {"SubjectID": merged["SubjectID"], "Group": merged["Group"]}
    for short, col in metrics.items():
        base = merged[f"{col}_baseline"]
        post = merged[f"{col}_posttest"]
        out[f"baseline_{short}"] = base
        out[f"posttest_{short}"] = post
        out[f"delta_{short}"] = post - base

    deltas = pd.DataFrame(out)

    # Δt 寄与率: Δt_ms / ΔRT_ms (両方が有限で ΔRT != 0 のとき)
    dt_ms = deltas["delta_t_s"] * 1000.0
    with np.errstate(divide="ignore", invalid="ignore"):
        frac_t = np.where(np.abs(deltas["delta_rt_ms"]) > 1e-6,
                          dt_ms / deltas["delta_rt_ms"], np.nan)
    deltas["frac_t_of_rt"] = frac_t
    return deltas


# =====================================================================
# 群間検定 (BH-FDR 一括補正)
# =====================================================================

def independent_ttest(a: np.ndarray, b: np.ndarray) -> dict:
    a = np.asarray(a, float)
    b = np.asarray(b, float)
    a = a[np.isfinite(a)]
    b = b[np.isfinite(b)]
    if len(a) < 2 or len(b) < 2:
        return {"n_a": len(a), "n_b": len(b), "reason": "insufficient data"}
    t, p = stats.ttest_ind(a, b, equal_var=False)  # Welch
    pooled_sd = np.sqrt(((len(a) - 1) * a.var(ddof=1) + (len(b) - 1) * b.var(ddof=1)) /
                        (len(a) + len(b) - 2))
    d = (a.mean() - b.mean()) / pooled_sd if pooled_sd > 0 else 0.0
    result = {
        "n_a": int(len(a)), "n_b": int(len(b)),
        "mean_a": float(a.mean()), "sd_a": float(a.std(ddof=1)),
        "mean_b": float(b.mean()), "sd_b": float(b.std(ddof=1)),
        "mean_diff": float(a.mean() - b.mean()),
        "t": float(t), "p_uncorrected": float(p), "cohens_d": float(d),
    }
    if HAS_PINGOUIN:
        try:
            bf = pg.ttest(a, b, paired=False)
            result["bf10"] = float(bf["BF10"].values[0])
        except Exception:
            pass
    return result


def run_all_group_tests(deltas: pd.DataFrame) -> dict:
    """AgencyEMS vs Voluntary の 6 主検定 + BH-FDR 補正。"""
    agency = deltas[deltas["Group"] == "AgencyEMS"]
    volu = deltas[deltas["Group"] == "Voluntary"]

    tests = {
        "1a_delta_rt_ms":    ("delta_rt_ms",   "H1a: AgencyEMS group shows larger RT reduction"),
        "1b_delta_acc":      ("delta_acc",     "H1b: AgencyEMS accuracy is not worse"),
        "1c_delta_ies_ms":   ("delta_ies_ms",  "H1c: AgencyEMS shows larger IES improvement"),
        "2a_delta_a":        ("delta_a",       "H2a: No group diff in Δa (tradeoff rejection)"),
        "2b_delta_t_s":      ("delta_t_s",     "H2b: AgencyEMS shows larger Δt reduction"),
        "2c_delta_v":        ("delta_v",       "H2c: Δv observation (no prior hypothesis)"),
    }

    results = {}
    p_list, name_list = [], []
    for key, (col, desc) in tests.items():
        res = independent_ttest(agency[col].to_numpy(), volu[col].to_numpy())
        res["description"] = desc
        res["metric"] = col
        results[key] = res
        if "p_uncorrected" in res:
            p_list.append(res["p_uncorrected"])
            name_list.append(key)

    if len(p_list) >= 2:
        _, p_corr, _, _ = multipletests(p_list, method="fdr_bh")
        for key, pc in zip(name_list, p_corr):
            results[key]["p_fdr"] = float(pc)
            results[key]["significant_fdr"] = bool(pc < 0.05)

    # One-sample vs 0 (各群 × ΔRT, Δt, Δa, Δv) — 参考情報として
    one_sample = {}
    for group_name, g in [("AgencyEMS", agency), ("Voluntary", volu)]:
        for col in ["delta_rt_ms", "delta_acc", "delta_t_s", "delta_a", "delta_v"]:
            vals = g[col].dropna().to_numpy()
            if len(vals) < 2:
                continue
            t, p = stats.ttest_1samp(vals, 0.0)
            one_sample[f"{group_name}_{col}"] = {
                "n": int(len(vals)), "mean": float(vals.mean()),
                "sd": float(vals.std(ddof=1)),
                "t": float(t), "p_uncorrected": float(p),
            }
    results["_one_sample_vs_zero"] = one_sample

    # 分解指標の群平均
    frac_t_summary = {}
    for group_name, g in [("AgencyEMS", agency), ("Voluntary", volu)]:
        vals = g["frac_t_of_rt"].replace([np.inf, -np.inf], np.nan).dropna().to_numpy()
        if len(vals) > 0:
            frac_t_summary[group_name] = {
                "n": int(len(vals)),
                "mean_frac_t": float(vals.mean()),
                "median_frac_t": float(np.median(vals)),
                "sd": float(vals.std(ddof=1)) if len(vals) > 1 else None,
            }
    results["_frac_t_of_rt"] = frac_t_summary

    return results


# =====================================================================
# プロット
# =====================================================================

def plot_rt_distributions(df: pd.DataFrame, out_dir: Path) -> list:
    """正答/誤答 × フェーズ × 群の RT 分布ヒストグラム。"""
    plots = []
    for phase in ["Baseline", "PostTest"]:
        pdf = df[df["Phase"] == phase]
        if pdf.empty:
            continue
        fig, axes = plt.subplots(1, 2, figsize=(14, 5))
        for ax, group in zip(axes, ["AgencyEMS", "Voluntary"]):
            gdf = pdf[pdf["Group"] == group]
            if gdf.empty:
                ax.set_title(f"{group} — no data")
                continue
            corr = gdf.loc[gdf["IsCorrect"] == 1, "ReactionTime_ms"]
            err = gdf.loc[gdf["IsCorrect"] == 0, "ReactionTime_ms"]
            if len(corr) > 0:
                ax.hist(corr, bins=30, alpha=0.7, color="steelblue",
                        label=f"Correct (n={len(corr)})", density=True)
            if len(err) > 0:
                ax.hist(err, bins=15, alpha=0.7, color="salmon",
                        label=f"Error (n={len(err)})", density=True)
            ax.set_xlabel("RT (ms)"); ax.set_ylabel("Density")
            ax.set_title(f"{group} — {phase}")
            ax.legend(); ax.set_xlim(0, 1000)
        plt.suptitle(f"RT Distribution — {phase}")
        plt.tight_layout()
        p = out_dir / f"rt_distribution_{phase.lower()}.png"
        plt.savefig(p, dpi=150); plt.close()
        plots.append(p)
    return plots


def plot_deltas_boxplot(deltas: pd.DataFrame, out_dir: Path) -> list:
    """Δ 系列（RT, Acc, IES, v, a, t）を群別に箱ひげ + ストリップでプロット。"""
    specs = [
        ("delta_rt_ms", "ΔRT (ms)  negative = faster"),
        ("delta_acc", "ΔAccuracy  positive = more accurate"),
        ("delta_ies_ms", "ΔIES (ms)  negative = more efficient"),
        ("delta_v", "Δv (drift rate)"),
        ("delta_a", "Δa (threshold)  negative could indicate tradeoff"),
        ("delta_t_s", "Δt (non-decision, s)  negative = motor priming"),
    ]
    fig, axes = plt.subplots(2, 3, figsize=(18, 10))
    for ax, (col, title) in zip(axes.flatten(), specs):
        d = deltas.dropna(subset=[col])
        if d.empty:
            ax.set_title(f"{title} — no data"); continue
        sns.boxplot(data=d, x="Group", y=col, ax=ax, palette="Set2",
                    order=["AgencyEMS", "Voluntary"])
        sns.stripplot(data=d, x="Group", y=col, ax=ax, color="black",
                      alpha=0.5, jitter=True, order=["AgencyEMS", "Voluntary"])
        ax.axhline(0, color="gray", ls="--", alpha=0.5)
        ax.set_title(title)
    plt.suptitle("Group comparisons: AgencyEMS vs Voluntary (Δ = PostTest − Baseline)")
    plt.tight_layout()
    p = out_dir / "group_deltas_boxplots.png"
    plt.savefig(p, dpi=150); plt.close()
    return [p]


def plot_pre_post(deltas: pd.DataFrame, out_dir: Path) -> list:
    """RT の Pre/Post ペアプロット。"""
    fig, ax = plt.subplots(figsize=(8, 6))
    for group, color in [("AgencyEMS", "steelblue"), ("Voluntary", "coral")]:
        g = deltas[deltas["Group"] == group].dropna(subset=["baseline_rt_ms", "posttest_rt_ms"])
        for _, row in g.iterrows():
            ax.plot([0, 1], [row["baseline_rt_ms"], row["posttest_rt_ms"]],
                    "o-", color=color, alpha=0.35)
        if not g.empty:
            mb = g["baseline_rt_ms"].mean(); mp = g["posttest_rt_ms"].mean()
            ax.plot([0, 1], [mb, mp], "s-", color=color, markersize=12, linewidth=3,
                    label=f"{group} (mean)")
    ax.set_xticks([0, 1]); ax.set_xticklabels(["Baseline", "PostTest"])
    ax.set_ylabel("RT (IQR-filtered mean, ms)")
    ax.set_title("Pre/Post RT by Group")
    ax.legend()
    plt.tight_layout()
    p = out_dir / "rt_pre_post.png"
    plt.savefig(p, dpi=150); plt.close()
    return [p]


def plot_sat_scatter(deltas: pd.DataFrame, out_dir: Path) -> list:
    """ΔRT vs ΔAccuracy 散布図 — 速度-正答率トレードオフの可視化。"""
    fig, ax = plt.subplots(figsize=(8, 7))
    for group, color in [("AgencyEMS", "steelblue"), ("Voluntary", "coral")]:
        g = deltas[deltas["Group"] == group].dropna(subset=["delta_rt_ms", "delta_acc"])
        ax.scatter(g["delta_rt_ms"], g["delta_acc"], s=80, alpha=0.7,
                   color=color, label=f"{group} (n={len(g)})")
    ax.axhline(0, color="gray", ls="--", alpha=0.5)
    ax.axvline(0, color="gray", ls="--", alpha=0.5)
    ax.set_xlabel("ΔRT (ms)  ← faster")
    ax.set_ylabel("ΔAccuracy  ↑ more accurate")
    ax.set_title("Speed-Accuracy Change: ΔRT vs ΔAccuracy\n"
                 "Lower-right = tradeoff; lower-left/upper = real improvement")
    ax.legend()
    plt.tight_layout()
    p = out_dir / "sat_scatter.png"
    plt.savefig(p, dpi=150); plt.close()
    return [p]


# =====================================================================
# Main
# =====================================================================

def main():
    parser = argparse.ArgumentParser(description="CRT training effect + EZ-DDM (V3)")
    parser.add_argument("--data_dir", required=True, help="ExperimentData root")
    parser.add_argument("--outdir", required=True, help="Output directory")
    parser.add_argument("--min_rt", type=float, default=100)
    parser.add_argument("--max_rt", type=float, default=1000)
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    out_dir = Path(args.outdir); out_dir.mkdir(parents=True, exist_ok=True)

    print("Loading subject data...")
    df = load_all_subjects(data_dir)
    print(f"Loaded {len(df)} trials, {df['SubjectID'].nunique()} subjects")

    df = preprocess(df, args.min_rt, args.max_rt)
    print(f"After preprocessing: {len(df)} trials")

    print("\n[1/5] Computing per-subject summaries (RT, Accuracy, IES, EZ-DDM)...")
    summary = compute_subject_summaries(df)
    summary.to_csv(out_dir / "subject_phase_summary.csv", index=False)

    n_invalid = int((~summary["ez_valid"]).sum())
    n_edge = int(summary["ez_edge_corrected"].sum())
    print(f"  EZ-DDM: {len(summary) - n_invalid}/{len(summary)} valid, "
          f"{n_edge} edge-corrected (P_correct=0 or 1)")
    if n_invalid > 0:
        print("  Invalid reasons:")
        print(summary.loc[~summary["ez_valid"], ["SubjectID", "Phase", "ez_reason"]]
              .to_string(index=False))

    print("\n[2/5] Computing PostTest - Baseline deltas...")
    deltas = compute_deltas(summary)
    deltas.to_csv(out_dir / "deltas.csv", index=False)

    print("\n[3/5] Group comparisons (AgencyEMS vs Voluntary, BH-FDR corrected)...")
    tests = run_all_group_tests(deltas)

    print("\n=== Main tests ===")
    for key in ["1a_delta_rt_ms", "1b_delta_acc", "1c_delta_ies_ms",
                "2a_delta_a", "2b_delta_t_s", "2c_delta_v"]:
        r = tests.get(key, {})
        if "p_uncorrected" not in r:
            print(f"  {key}: {r.get('reason', 'skipped')}")
            continue
        sig = "*" if r.get("significant_fdr") else " "
        bf = f"  BF10={r['bf10']:.2f}" if "bf10" in r else ""
        print(f"  {sig} {key}: {r['description']}")
        print(f"      EMS={r['mean_a']:+.4g}±{r['sd_a']:.4g} (n={r['n_a']})  "
              f"Volu={r['mean_b']:+.4g}±{r['sd_b']:.4g} (n={r['n_b']})")
        print(f"      Δmean={r['mean_diff']:+.4g}  t={r['t']:+.3f}  "
              f"p={r['p_uncorrected']:.4f}  p_fdr={r.get('p_fdr', float('nan')):.4f}  "
              f"d={r['cohens_d']:+.3f}{bf}")

    print("\n=== Δt contribution to ΔRT (frac_t = Δt_ms / ΔRT_ms) ===")
    for group, info in tests.get("_frac_t_of_rt", {}).items():
        print(f"  {group}: mean={info['mean_frac_t']:+.3f}  "
              f"median={info['median_frac_t']:+.3f}  (n={info['n']})")

    print("\n[4/5] Saving plots...")
    plots = []
    plots += plot_rt_distributions(df, out_dir)
    plots += plot_deltas_boxplot(deltas, out_dir)
    plots += plot_pre_post(deltas, out_dir)
    plots += plot_sat_scatter(deltas, out_dir)
    print(f"  Saved {len(plots)} plots")

    print("\n[5/5] Writing JSON report...")
    report = {
        "n_subjects": int(df["SubjectID"].nunique()),
        "n_per_group": df.groupby("Group")["SubjectID"].nunique().to_dict(),
        "n_trials_total": int(len(df)),
        "ez_ddm_scale_s": EZ_SCALE,
        "ez_valid_ratio": (len(summary) - n_invalid) / len(summary) if len(summary) else 0.0,
        "ez_edge_corrected_count": n_edge,
        "tests": tests,
        "plots": [str(p) for p in plots],
    }
    (out_dir / "analysis_results.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8")
    print(f"Done. Results: {out_dir}")


if __name__ == "__main__":
    main()
