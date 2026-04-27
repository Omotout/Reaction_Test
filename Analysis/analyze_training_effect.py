"""
analyze_training_effect.py — V3 CRT特化 RT群間比較 (DDM なし版)

検定設計:
  Primary:   Mixed ANOVA (Group × Phase) on RT
             - Group × Phase 交互作用 = 「訓練効果が群で異なるか」の直接検定
             - 主効果 Phase / Group も同時に評価
  Secondary: Welch t-test on ΔRT      (効果量 Cohen's d 付き)
             Mann-Whitney U on ΔRT     (正規性違反時の頑健性チェック)
             Shapiro-Wilk on ΔRT       (群ごとに正規性を確認)
  補助:       ΔAccuracy も同様に検定 (速度-正答率トレードオフの否定)

要約統計:
  RT は正答試行の IQR フィルタ (Q1 - 1.5·IQR, Q3 + 1.5·IQR) 適用後の平均
  Accuracy は全試行の正答率 (タイムアウトは事前除外)

DDM パラメタ分解 (v, a, t) が必要な場合は analyze_training_effect_hddm.py を使用。

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
import matplotlib.pyplot as plt
import seaborn as sns

try:
    import pingouin as pg
    HAS_PINGOUIN = True
except ImportError:
    HAS_PINGOUIN = False


# =====================================================================
# データ読み込み & 前処理
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
                all_data.append(pd.read_csv(trial_log, encoding="utf-8-sig"))
    if not all_data:
        raise ValueError(f"No trial_log.csv found under {data_dir}")
    return pd.concat(all_data, ignore_index=True, sort=False)


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

    # Group が整数 (0/1) で保存されているレガシーデータへの対応
    if df["Group"].dtype.kind in ("i", "f"):
        group_map = {0: "AgencyEMS", 1: "Voluntary"}
        df["Group"] = df["Group"].map(group_map).fillna(df["Group"].astype(str))

    return df


# =====================================================================
# IQR-filtered mean
# =====================================================================

def iqr_filtered_mean(rts: np.ndarray, k: float = 1.5) -> Optional[float]:
    """IQR フィルタ [Q1 - k·IQR, Q3 + k·IQR] 後の平均。データ不足時は None。"""
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


# =====================================================================
# 被験者×フェーズの要約統計
# =====================================================================

def compute_subject_summaries(df: pd.DataFrame) -> pd.DataFrame:
    """被験者 × フェーズごとに RT 平均と Accuracy を算出 (long-form)。"""
    rows = []
    for (subj, group, phase), g in df.groupby(["SubjectID", "Group", "Phase"]):
        n_total = len(g)
        n_correct = int(g["IsCorrect"].sum())
        p_correct = n_correct / n_total if n_total > 0 else np.nan

        correct_rts = g.loc[g["IsCorrect"] == 1, "ReactionTime_ms"].to_numpy()
        rt_mean = iqr_filtered_mean(correct_rts)

        rows.append({
            "SubjectID": subj, "Group": group, "Phase": phase,
            "n_total": n_total, "n_correct": n_correct,
            "p_correct": p_correct,
            "rt_mean_ms": rt_mean,
        })
    return pd.DataFrame(rows)


def compute_deltas(summary: pd.DataFrame) -> pd.DataFrame:
    """PostTest - Baseline の Δ を被験者ごとに算出。

    Baseline と PostTest を SubjectID/Group で明示 merge してから差分を取り、
    欠損パターンによる位置ズレを防ぐ。両フェーズが揃わない被験者は欠損値で残す。
    """
    metrics = {"rt_ms": "rt_mean_ms", "acc": "p_correct"}
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

    return pd.DataFrame(out)


# =====================================================================
# 検定: Mixed ANOVA (Primary) + 補助検定
# =====================================================================

def run_mixed_anova(summary: pd.DataFrame, dv: str = "rt_mean_ms") -> dict:
    """Mixed ANOVA (Group between × Phase within) を pingouin で実行。

    両フェーズが揃った被験者のみが ANOVA に含まれる。pingouin は欠損行を
    自動的にドロップするが、ここでも明示的にフィルタしてカウントを記録する。
    """
    if not HAS_PINGOUIN:
        return {"reason": "pingouin not installed; install with `pip install pingouin`"}

    # 両フェーズが揃った被験者だけを残す
    pivot = summary.pivot_table(index=["SubjectID", "Group"], columns="Phase",
                                values=dv).dropna()
    valid_subjects = pivot.index.get_level_values("SubjectID").tolist()
    long = summary[summary["SubjectID"].isin(valid_subjects)].copy()

    if long["Group"].nunique() < 2 or long["Phase"].nunique() < 2:
        return {"reason": "need ≥2 groups and ≥2 phases", "n_subjects": len(valid_subjects)}
    if len(valid_subjects) < 4:
        return {"reason": f"insufficient subjects (n={len(valid_subjects)})"}

    aov = pg.mixed_anova(data=long, dv=dv, within="Phase",
                         between="Group", subject="SubjectID")
    # aov の各行を辞書化 (Source: 'Group', 'Phase', 'Interaction')
    rows = {}
    for _, row in aov.iterrows():
        rows[row["Source"]] = {k: (float(row[k]) if isinstance(row[k], (int, float, np.floating))
                                   else row[k])
                               for k in aov.columns if k != "Source"}
    return {
        "n_subjects": len(valid_subjects),
        "n_per_group": long.drop_duplicates("SubjectID")["Group"].value_counts().to_dict(),
        "table": rows,
    }


def shapiro_per_group(deltas: pd.DataFrame, col: str) -> dict:
    """群ごとに ΔRT (or Δacc) の Shapiro-Wilk 正規性検定を実行。"""
    out = {}
    for group, g in deltas.groupby("Group"):
        vals = g[col].dropna().to_numpy()
        if len(vals) < 3:
            out[group] = {"n": int(len(vals)), "reason": "n<3"}
            continue
        W, p = stats.shapiro(vals)
        out[group] = {
            "n": int(len(vals)), "W": float(W), "p": float(p),
            "normal_at_0.05": bool(p >= 0.05),
        }
    return out


def welch_ttest_on_delta(deltas: pd.DataFrame, col: str) -> dict:
    """群間 Welch t-test + Cohen's d (pooled SD)。"""
    a = deltas.loc[deltas["Group"] == "AgencyEMS", col].dropna().to_numpy()
    b = deltas.loc[deltas["Group"] == "Voluntary", col].dropna().to_numpy()
    if len(a) < 2 or len(b) < 2:
        return {"n_a": int(len(a)), "n_b": int(len(b)),
                "reason": "insufficient data"}
    t, p = stats.ttest_ind(a, b, equal_var=False)
    pooled_sd = np.sqrt(((len(a) - 1) * a.var(ddof=1) + (len(b) - 1) * b.var(ddof=1)) /
                        (len(a) + len(b) - 2))
    d = (a.mean() - b.mean()) / pooled_sd if pooled_sd > 0 else 0.0
    return {
        "n_a": int(len(a)), "n_b": int(len(b)),
        "mean_a": float(a.mean()), "sd_a": float(a.std(ddof=1)),
        "mean_b": float(b.mean()), "sd_b": float(b.std(ddof=1)),
        "mean_diff": float(a.mean() - b.mean()),
        "t": float(t), "p": float(p), "cohens_d": float(d),
    }


def mannwhitney_on_delta(deltas: pd.DataFrame, col: str) -> dict:
    """群間 Mann-Whitney U (両側) + 効果量 r (= |Z| / √N)。"""
    a = deltas.loc[deltas["Group"] == "AgencyEMS", col].dropna().to_numpy()
    b = deltas.loc[deltas["Group"] == "Voluntary", col].dropna().to_numpy()
    if len(a) < 2 or len(b) < 2:
        return {"n_a": int(len(a)), "n_b": int(len(b)),
                "reason": "insufficient data"}
    U, p = stats.mannwhitneyu(a, b, alternative="two-sided")
    n1, n2 = len(a), len(b)
    mu_U = n1 * n2 / 2.0
    sigma_U = np.sqrt(n1 * n2 * (n1 + n2 + 1) / 12.0)
    z = (U - mu_U) / sigma_U if sigma_U > 0 else 0.0
    r = abs(z) / np.sqrt(n1 + n2)
    return {
        "n_a": int(n1), "n_b": int(n2),
        "median_a": float(np.median(a)), "median_b": float(np.median(b)),
        "U": float(U), "p": float(p),
        "z_approx": float(z), "effect_size_r": float(r),
    }


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


def plot_delta_boxplots(deltas: pd.DataFrame, out_dir: Path) -> list:
    """ΔRT, ΔAccuracy を群別に箱ひげ + ストリップで可視化。"""
    specs = [
        ("delta_rt_ms",  "ΔRT (ms)  negative = faster"),
        ("delta_acc",    "ΔAccuracy  positive = more accurate"),
    ]
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5))
    for ax, (col, title) in zip(axes, specs):
        d = deltas.dropna(subset=[col])
        if d.empty:
            ax.set_title(f"{title} — no data"); continue
        sns.boxplot(data=d, x="Group", y=col, ax=ax,
                    hue="Group", palette="Set2", legend=False,
                    order=["AgencyEMS", "Voluntary"])
        sns.stripplot(data=d, x="Group", y=col, ax=ax, color="black",
                      alpha=0.5, jitter=True, order=["AgencyEMS", "Voluntary"])
        ax.axhline(0, color="gray", ls="--", alpha=0.5)
        ax.set_title(title)
    plt.suptitle("Group comparisons (Δ = PostTest − Baseline)")
    plt.tight_layout()
    p = out_dir / "group_deltas_boxplots.png"
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
    parser = argparse.ArgumentParser(description="CRT training effect — RT group comparison (V3)")
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

    print("\n[1/4] Computing per-subject summaries (RT, Accuracy)...")
    summary = compute_subject_summaries(df)
    summary.to_csv(out_dir / "subject_phase_summary.csv", index=False)

    deltas = compute_deltas(summary)
    deltas.to_csv(out_dir / "deltas.csv", index=False)

    # ----------------------------------------------------------------
    # Primary: Mixed ANOVA on RT
    # ----------------------------------------------------------------
    print("\n[2/4] Mixed ANOVA (Group × Phase) on RT...")
    aov_rt = run_mixed_anova(summary, dv="rt_mean_ms")
    aov_acc = run_mixed_anova(summary, dv="p_correct")

    def _print_aov(label, aov):
        if "table" not in aov:
            print(f"  {label}: skipped — {aov.get('reason')}")
            return
        print(f"  {label}: n={aov['n_subjects']} subjects "
              f"({aov['n_per_group']})")
        for source in ["Group", "Phase", "Interaction"]:
            row = aov["table"].get(source)
            if row is None:
                continue
            F = row.get("F"); p = row.get("p-unc")
            np2 = row.get("np2") or row.get("n2p")
            if F is None or p is None:
                print(f"    {source}: missing stats")
                continue
            np2_str = f"  ηp²={np2:.3f}" if isinstance(np2, (int, float)) else ""
            print(f"    {source:11s}  F={F:>6.3f}  p={p:.4f}{np2_str}")
    _print_aov("RT  (ms)", aov_rt)
    _print_aov("Acc      ", aov_acc)

    # ----------------------------------------------------------------
    # Secondary: ΔRT に対する補助検定
    # ----------------------------------------------------------------
    print("\n[3/4] Secondary tests on ΔRT and ΔAccuracy...")
    secondary = {}
    for col, label in [("delta_rt_ms", "ΔRT (ms)"),
                       ("delta_acc", "ΔAccuracy")]:
        normality = shapiro_per_group(deltas, col)
        welch = welch_ttest_on_delta(deltas, col)
        mwu = mannwhitney_on_delta(deltas, col)
        secondary[col] = {
            "shapiro": normality,
            "welch_ttest": welch,
            "mann_whitney_u": mwu,
        }

        print(f"\n  --- {label} ---")
        print(f"  Shapiro-Wilk (per group):")
        for grp, info in normality.items():
            if "p" not in info:
                print(f"    {grp}: {info.get('reason')}")
                continue
            flag = "ok" if info["normal_at_0.05"] else "VIOLATED"
            print(f"    {grp}: W={info['W']:.3f}  p={info['p']:.4f}  [{flag}]")

        if "p" in welch:
            print(f"  Welch t-test:    t={welch['t']:+.3f}  p={welch['p']:.4f}  "
                  f"d={welch['cohens_d']:+.3f}  "
                  f"(EMS={welch['mean_a']:+.3g}±{welch['sd_a']:.3g}, "
                  f"Volu={welch['mean_b']:+.3g}±{welch['sd_b']:.3g})")
        else:
            print(f"  Welch t-test:    skipped — {welch.get('reason')}")

        if "p" in mwu:
            print(f"  Mann-Whitney U:  U={mwu['U']:.1f}  p={mwu['p']:.4f}  "
                  f"r={mwu['effect_size_r']:.3f}  "
                  f"(median EMS={mwu['median_a']:+.3g}, Volu={mwu['median_b']:+.3g})")
        else:
            print(f"  Mann-Whitney U:  skipped — {mwu.get('reason')}")

        # 推奨検定の指針
        all_normal = all(info.get("normal_at_0.05", False) for info in normality.values()
                         if "p" in info)
        if all_normal:
            print(f"  → 正規性 OK: Mixed ANOVA / Welch t-test を主たる推論に用いる")
        else:
            print(f"  → 正規性違反あり: Mann-Whitney U を主たる推論に用いる")

    # ----------------------------------------------------------------
    # プロット
    # ----------------------------------------------------------------
    print("\n[4/4] Saving plots...")
    plots = []
    plots += plot_rt_distributions(df, out_dir)
    plots += plot_pre_post(deltas, out_dir)
    plots += plot_delta_boxplots(deltas, out_dir)
    plots += plot_sat_scatter(deltas, out_dir)
    print(f"  Saved {len(plots)} plots")

    # ----------------------------------------------------------------
    # JSON レポート
    # ----------------------------------------------------------------
    report = {
        "n_subjects": int(df["SubjectID"].nunique()),
        "n_per_group": df.groupby("Group")["SubjectID"].nunique().to_dict(),
        "n_trials_total": int(len(df)),
        "rt_bounds_ms": [args.min_rt, args.max_rt],
        "primary_mixed_anova": {
            "rt_mean_ms": aov_rt,
            "p_correct": aov_acc,
        },
        "secondary": secondary,
        "plots": [str(p) for p in plots],
    }
    (out_dir / "analysis_results.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8")
    print(f"\nDone. Results: {out_dir}")


if __name__ == "__main__":
    main()
