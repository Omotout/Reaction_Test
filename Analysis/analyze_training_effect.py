"""
analyze_training_effect.py — FastestBaseline 枠組み RT 訓練効果解析

実験設計:
  1セッション = 1条件（EMS or Voluntary）、同じ被験者が別日に2条件を実施する
  被験者内 2 条件 × 3 フェーズ（Pre, Post1, Post2）デザイン。

検定設計:
  Primary:   2-way Repeated Measures ANOVA (Condition × Phase) on RT
             - Condition × Phase 交互作用 = 「訓練効果が条件で異なるか」の直接検定
             - 主効果 Phase（訓練効果）/ Condition（条件差）も同時に評価
  Secondary: paired t-test on ΔRT (= Post̄ − Pre) between conditions per subject
             Wilcoxon signed-rank (正規性違反時の頑健性チェック)
  補助:       ΔAccuracy も同様に検定（速度-正答率トレードオフの否定）

要約統計:
  RT は ExclusionFlag=Normal の正答試行の IQR フィルタ (Q1 − 1.5·IQR, Q3 + 1.5·IQR) 適用後の平均
  Accuracy は全試行（タイムアウト除外）の正答率

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


ANALYSIS_PHASES = ["Pre", "Post1", "Post2"]
CONDITIONS = ["EMS", "Voluntary"]


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


def preprocess(df: pd.DataFrame, intervention_mode_filter: Optional[str] = None) -> pd.DataFrame:
    """解析対象フェーズ(Pre/Post1/Post2)に絞る最小限の前処理。

    ExclusionFlag による絞り込みは RT/accuracy で要件が異なるため、ここでは行わず
    compute_subject_summaries で個別に行う（accuracy=全試行、RT=Normal のみ）。

    InterventionMode 列が無い古い CSV では仮想的に "Fastest" を割り当てる（旧データ互換）。
    intervention_mode_filter を指定するとそのモードに絞り込む（"Fastest" or "Deadline"）。
    """
    # 旧スキーマ検出: Condition 列が無いログは旧 Agency 枠組み (Group=AgencyEMS/Voluntary) の可能性が高い。
    # 黙って空データを返すと「セッション数 0」で気付きにくいので明示エラーで止める。
    if "Condition" not in df.columns:
        if "Group" in df.columns:
            raise ValueError(
                "Legacy schema detected: 'Group' column exists but no 'Condition'. "
                "Old AgencyEMS/Voluntary CSVs are not compatible with FastestBaseline analysis. "
                "Either migrate the CSVs (rename Group→Condition, AgencyEMS→EMS) or "
                "checkout the pre-migration version of this script.")
        raise ValueError("CSV is missing required 'Condition' column.")

    df = df[df["Phase"].isin(ANALYSIS_PHASES)].copy()
    df["ReactionTime_ms"] = pd.to_numeric(df["ReactionTime_ms"], errors="coerce")
    df["IsCorrect"] = pd.to_numeric(df["IsCorrect"], errors="coerce").fillna(0).astype(int)
    df = df.dropna(subset=["ReactionTime_ms"])

    # Condition が整数で保存されているレガシーデータへの対応（JsonUtility がenumを int 化するケース）
    if df["Condition"].dtype.kind in ("i", "f"):
        df["Condition"] = df["Condition"].map({0: "EMS", 1: "Voluntary"}).fillna(df["Condition"].astype(str))

    # InterventionMode 列の整備（無ければ全行 Fastest 扱い、int も string にマップ）
    if "InterventionMode" not in df.columns:
        df["InterventionMode"] = "Fastest"
    elif df["InterventionMode"].dtype.kind in ("i", "f"):
        df["InterventionMode"] = (df["InterventionMode"]
                                  .map({0: "Fastest", 1: "Deadline"})
                                  .fillna(df["InterventionMode"].astype(str)))

    if intervention_mode_filter is not None:
        df = df[df["InterventionMode"] == intervention_mode_filter].copy()

    return df


# =====================================================================
# IQR-filtered mean
# =====================================================================

def iqr_filtered_mean(rts: np.ndarray, k: float = 1.5) -> Optional[float]:
    """IQR フィルタ [Q1 − k·IQR, Q3 + k·IQR] 後の平均。データ不足時は単純平均/中央値。"""
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
# 被験者×条件×フェーズの要約統計
# =====================================================================

def compute_subject_summaries(df: pd.DataFrame, min_rt: float, max_rt: float) -> pd.DataFrame:
    """被験者 × 介入モード × 条件 × フェーズごとに RT 平均と Accuracy を算出 (long-form)。

    Accuracy は **全試行**（タイムアウトのみ除外）の正答率。
    RT は **ExclusionFlag=Normal の正答試行** に min_rt/max_rt の二重ガードを掛けた上で IQR フィルタ平均。
    InterventionMode を groupby に含めるので、同じ被験者の Fastest セッションと Deadline セッションが
    同じセルに混入しない。
    """
    has_excl = "ExclusionFlag" in df.columns
    rows = []
    for (subj, mode, cond, phase), g in df.groupby(
            ["SubjectID", "InterventionMode", "Condition", "Phase"]):
        # ── Accuracy: タイムアウト(RT<=0)のみ除外、anticipation/lapse は含める ──
        acc_pool = g[g["ReactionTime_ms"] > 0]
        n_total = len(acc_pool)
        n_correct = int(acc_pool["IsCorrect"].sum())
        p_correct = n_correct / n_total if n_total > 0 else np.nan

        # ── RT: ExclusionFlag=Normal の正答試行 × bounds × IQR ──
        rt_pool = g[g["IsCorrect"] == 1]
        if has_excl:
            rt_pool = rt_pool[rt_pool["ExclusionFlag"].astype(str) == "Normal"]
        rt_pool = rt_pool[(rt_pool["ReactionTime_ms"] >= min_rt)
                          & (rt_pool["ReactionTime_ms"] <= max_rt)]
        rt_mean = iqr_filtered_mean(rt_pool["ReactionTime_ms"].to_numpy())

        rows.append({
            "SubjectID": subj, "InterventionMode": mode, "Condition": cond, "Phase": phase,
            "n_total_for_acc": n_total, "n_correct_for_acc": n_correct,
            "n_rt_used": len(rt_pool),
            "p_correct": p_correct,
            "rt_mean_ms": rt_mean,
        })
    return pd.DataFrame(rows)


def compute_deltas(summary: pd.DataFrame) -> pd.DataFrame:
    """ΔRT = mean(Post1, Post2) − Pre を被験者×介入モード×条件ごとに算出。

    Post̄ は Post1 と Post2 の平均（片方しか無ければそれを使う）。両方とも欠損なら
    Δ は欠損で残す。Pre が欠損なら Δ は計算しない。
    """
    metrics = {"rt_ms": "rt_mean_ms", "acc": "p_correct"}
    pivot = summary.pivot_table(
        index=["SubjectID", "InterventionMode", "Condition"], columns="Phase",
        values=list(metrics.values()),
    )

    out_rows = []
    for (subj, mode, cond), row in pivot.iterrows():
        rec = {"SubjectID": subj, "InterventionMode": mode, "Condition": cond}
        for short, col in metrics.items():
            pre = row.get((col, "Pre"), np.nan)
            p1 = row.get((col, "Post1"), np.nan)
            p2 = row.get((col, "Post2"), np.nan)
            post_vals = [v for v in (p1, p2) if pd.notna(v)]
            post_mean = float(np.mean(post_vals)) if post_vals else np.nan
            rec[f"pre_{short}"] = pre
            rec[f"post1_{short}"] = p1
            rec[f"post2_{short}"] = p2
            rec[f"post_mean_{short}"] = post_mean
            rec[f"delta_{short}"] = (post_mean - pre) if pd.notna(pre) and pd.notna(post_mean) else np.nan
        out_rows.append(rec)
    return pd.DataFrame(out_rows)


# =====================================================================
# 検定: 2-way RM ANOVA (Primary) + 補助検定
# =====================================================================

def run_rm_anova(summary: pd.DataFrame, dv: str = "rt_mean_ms") -> dict:
    """2-way Repeated Measures ANOVA (Condition × Phase, both within)。

    全被験者で「両条件 × 3フェーズ」のセルが揃っている被験者だけが ANOVA に含まれる。
    """
    if not HAS_PINGOUIN:
        return {"reason": "pingouin not installed; install with `pip install pingouin`"}

    # 全6セル揃っている被験者だけを残す
    pivot = summary.pivot_table(index="SubjectID",
                                columns=["Condition", "Phase"], values=dv).dropna()
    valid_subjects = pivot.index.tolist()
    long = summary[summary["SubjectID"].isin(valid_subjects)
                   & summary["Phase"].isin(ANALYSIS_PHASES)
                   & summary["Condition"].isin(CONDITIONS)].copy()

    if long["Condition"].nunique() < 2 or long["Phase"].nunique() < 2:
        return {"reason": "need ≥2 conditions and ≥2 phases", "n_subjects": len(valid_subjects)}
    if len(valid_subjects) < 4:
        return {"reason": f"insufficient subjects (n={len(valid_subjects)})"}

    aov = pg.rm_anova(data=long, dv=dv, within=["Condition", "Phase"],
                      subject="SubjectID", detailed=True)
    rows = {}
    for _, row in aov.iterrows():
        rows[row["Source"]] = {k: (float(row[k]) if isinstance(row[k], (int, float, np.floating))
                                   else row[k])
                               for k in aov.columns if k != "Source"}
    return {
        "n_subjects": len(valid_subjects),
        "table": rows,
    }


def shapiro_per_condition(deltas: pd.DataFrame, col: str) -> dict:
    """条件ごとに ΔRT (or Δacc) の Shapiro-Wilk 正規性検定。"""
    out = {}
    for cond, g in deltas.groupby("Condition"):
        vals = g[col].dropna().to_numpy()
        if len(vals) < 3:
            out[cond] = {"n": int(len(vals)), "reason": "n<3"}
            continue
        W, p = stats.shapiro(vals)
        out[cond] = {
            "n": int(len(vals)), "W": float(W), "p": float(p),
            "normal_at_0.05": bool(p >= 0.05),
        }
    return out


def paired_ttest_within_subject(deltas: pd.DataFrame, col: str) -> dict:
    """被験者内ペア t-test (Δ_EMS vs Δ_Voluntary)。両条件揃った被験者のみ。"""
    pivot = deltas.pivot_table(index="SubjectID", columns="Condition", values=col).dropna()
    if "EMS" not in pivot.columns or "Voluntary" not in pivot.columns:
        return {"reason": "missing condition column", "n_pairs": int(len(pivot))}
    a = pivot["EMS"].to_numpy()
    b = pivot["Voluntary"].to_numpy()
    if len(a) < 2:
        return {"n_pairs": int(len(a)), "reason": "insufficient paired data"}
    t, p = stats.ttest_rel(a, b)
    diff = a - b
    sd_diff = float(np.std(diff, ddof=1)) if len(diff) > 1 else 0.0
    cohens_dz = float(np.mean(diff) / sd_diff) if sd_diff > 0 else 0.0
    return {
        "n_pairs": int(len(a)),
        "mean_ems": float(a.mean()), "sd_ems": float(a.std(ddof=1)),
        "mean_volu": float(b.mean()), "sd_volu": float(b.std(ddof=1)),
        "mean_diff_ems_minus_volu": float(np.mean(diff)),
        "t": float(t), "p": float(p), "cohens_dz": cohens_dz,
    }


def wilcoxon_within_subject(deltas: pd.DataFrame, col: str) -> dict:
    """被験者内 Wilcoxon signed-rank (Δ_EMS vs Δ_Voluntary)。"""
    pivot = deltas.pivot_table(index="SubjectID", columns="Condition", values=col).dropna()
    if "EMS" not in pivot.columns or "Voluntary" not in pivot.columns:
        return {"reason": "missing condition column", "n_pairs": int(len(pivot))}
    a = pivot["EMS"].to_numpy()
    b = pivot["Voluntary"].to_numpy()
    if len(a) < 2:
        return {"n_pairs": int(len(a)), "reason": "insufficient paired data"}
    try:
        W, p = stats.wilcoxon(a, b)
    except ValueError as e:
        return {"n_pairs": int(len(a)), "reason": str(e)}
    return {
        "n_pairs": int(len(a)),
        "median_ems": float(np.median(a)), "median_volu": float(np.median(b)),
        "median_diff_ems_minus_volu": float(np.median(a - b)),
        "W": float(W), "p": float(p),
    }


# =====================================================================
# プロット
# =====================================================================

def plot_rt_distributions(df: pd.DataFrame, out_dir: Path) -> list:
    """フェーズ × 条件の RT 分布ヒストグラム (3×2 グリッド)。タイムアウト(RT<=0)は除外。"""
    df = df[df["ReactionTime_ms"] > 0]
    fig, axes = plt.subplots(len(ANALYSIS_PHASES), len(CONDITIONS),
                             figsize=(12, 4 * len(ANALYSIS_PHASES)), sharex=True)
    if len(ANALYSIS_PHASES) == 1:
        axes = np.array([axes])
    for r, phase in enumerate(ANALYSIS_PHASES):
        for c, cond in enumerate(CONDITIONS):
            ax = axes[r, c]
            sub = df[(df["Phase"] == phase) & (df["Condition"] == cond)]
            if sub.empty:
                ax.set_title(f"{cond} — {phase} (no data)")
                continue
            corr = sub.loc[sub["IsCorrect"] == 1, "ReactionTime_ms"]
            err = sub.loc[sub["IsCorrect"] == 0, "ReactionTime_ms"]
            if len(corr) > 0:
                ax.hist(corr, bins=30, alpha=0.7, color="steelblue",
                        label=f"Correct (n={len(corr)})", density=True)
            if len(err) > 0:
                ax.hist(err, bins=15, alpha=0.7, color="salmon",
                        label=f"Error (n={len(err)})", density=True)
            ax.set_xlabel("RT (ms)"); ax.set_ylabel("Density")
            ax.set_title(f"{cond} — {phase}")
            ax.legend(); ax.set_xlim(0, 1000)
    plt.suptitle("RT distributions by Condition × Phase")
    plt.tight_layout()
    p = out_dir / "rt_distributions.png"
    plt.savefig(p, dpi=150); plt.close()
    return [p]


def plot_phase_trajectory(summary: pd.DataFrame, out_dir: Path) -> list:
    """RT の Pre → Post1 → Post2 軌跡（条件別、被験者別線 + 平均線）。"""
    fig, ax = plt.subplots(figsize=(9, 6))
    x = np.arange(len(ANALYSIS_PHASES))
    for cond, color in [("EMS", "steelblue"), ("Voluntary", "coral")]:
        sub = summary[summary["Condition"] == cond]
        pivot = sub.pivot_table(index="SubjectID", columns="Phase", values="rt_mean_ms")
        pivot = pivot.reindex(columns=ANALYSIS_PHASES)
        for _, row in pivot.iterrows():
            ax.plot(x, row.values, "o-", color=color, alpha=0.25)
        means = pivot.mean(axis=0).values
        ax.plot(x, means, "s-", color=color, markersize=12, linewidth=3,
                label=f"{cond} (mean, n={len(pivot.dropna())})")
    ax.set_xticks(x); ax.set_xticklabels(ANALYSIS_PHASES)
    ax.set_ylabel("RT (IQR-filtered mean, ms)")
    ax.set_title("RT trajectory across phases by Condition")
    ax.legend()
    plt.tight_layout()
    p = out_dir / "rt_phase_trajectory.png"
    plt.savefig(p, dpi=150); plt.close()
    return [p]


def plot_delta_boxplots(deltas: pd.DataFrame, out_dir: Path) -> list:
    """ΔRT, ΔAccuracy を条件別に箱ひげ + ストリップで可視化。"""
    specs = [
        ("delta_rt_ms",  "ΔRT (ms)  negative = faster"),
        ("delta_acc",    "ΔAccuracy  positive = more accurate"),
    ]
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5))
    for ax, (col, title) in zip(axes, specs):
        d = deltas.dropna(subset=[col])
        if d.empty:
            ax.set_title(f"{title} — no data"); continue
        sns.boxplot(data=d, x="Condition", y=col, ax=ax,
                    hue="Condition", palette="Set2", legend=False,
                    order=CONDITIONS)
        sns.stripplot(data=d, x="Condition", y=col, ax=ax, color="black",
                      alpha=0.5, jitter=True, order=CONDITIONS)
        ax.axhline(0, color="gray", ls="--", alpha=0.5)
        ax.set_title(title)
    plt.suptitle("Within-subject deltas (Δ = mean(Post1, Post2) − Pre)")
    plt.tight_layout()
    p = out_dir / "condition_deltas_boxplots.png"
    plt.savefig(p, dpi=150); plt.close()
    return [p]


def plot_sat_scatter(deltas: pd.DataFrame, out_dir: Path) -> list:
    """ΔRT vs ΔAccuracy 散布図（条件別）。"""
    fig, ax = plt.subplots(figsize=(8, 7))
    for cond, color in [("EMS", "steelblue"), ("Voluntary", "coral")]:
        g = deltas[deltas["Condition"] == cond].dropna(subset=["delta_rt_ms", "delta_acc"])
        ax.scatter(g["delta_rt_ms"], g["delta_acc"], s=80, alpha=0.7,
                   color=color, label=f"{cond} (n={len(g)})")
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


def plot_within_subject_pair(deltas: pd.DataFrame, out_dir: Path) -> list:
    """同一被験者の ΔRT を EMS vs Voluntary でペア線プロット。"""
    pivot = deltas.pivot_table(index="SubjectID", columns="Condition", values="delta_rt_ms").dropna()
    if pivot.empty or not set(CONDITIONS).issubset(pivot.columns):
        return []
    fig, ax = plt.subplots(figsize=(7, 6))
    for _, row in pivot.iterrows():
        ax.plot([0, 1], [row["EMS"], row["Voluntary"]], "o-", color="gray", alpha=0.5)
    ax.plot([0, 1], [pivot["EMS"].mean(), pivot["Voluntary"].mean()],
            "s-", color="black", markersize=12, linewidth=3, label=f"mean (n={len(pivot)})")
    ax.set_xticks([0, 1]); ax.set_xticklabels(CONDITIONS)
    ax.set_ylabel("ΔRT (ms)  negative = faster")
    ax.axhline(0, color="gray", ls="--", alpha=0.5)
    ax.set_title("Within-subject ΔRT: EMS vs Voluntary")
    ax.legend()
    plt.tight_layout()
    p = out_dir / "within_subject_delta_rt.png"
    plt.savefig(p, dpi=150); plt.close()
    return [p]


# =====================================================================
# Main
# =====================================================================

def run_analysis(df: pd.DataFrame, out_dir: Path, min_rt: float, max_rt: float):
    """1つの InterventionMode 分のデータに対して全パイプラインを実行する。
    呼び出し側で df を1モードに絞ってから渡すこと（複数モードの混在は groupby で防げるが
    ANOVA や paired test の自然な解釈には単一モードが望ましい）。"""
    out_dir.mkdir(parents=True, exist_ok=True)

    print("\n[1/4] Computing per-subject summaries (RT, Accuracy)...")
    summary = compute_subject_summaries(df, min_rt, max_rt)
    summary.to_csv(out_dir / "subject_phase_summary.csv", index=False)

    deltas = compute_deltas(summary)
    deltas.to_csv(out_dir / "deltas.csv", index=False)

    # ----------------------------------------------------------------
    # Primary: 2-way RM ANOVA on RT
    # ----------------------------------------------------------------
    print("\n[2/4] 2-way RM ANOVA (Condition × Phase) on RT...")
    aov_rt = run_rm_anova(summary, dv="rt_mean_ms")
    aov_acc = run_rm_anova(summary, dv="p_correct")  # accuracy も同様

    def _print_aov(label, aov):
        if "table" not in aov:
            print(f"  {label}: skipped — {aov.get('reason')}")
            return
        print(f"  {label}: n={aov['n_subjects']} subjects (with all 6 cells)")
        for source, row in aov["table"].items():
            F = row.get("F"); p = row.get("p-unc")
            np2 = row.get("np2") or row.get("ng2")
            if F is None or p is None:
                continue
            np2_str = f"  ηp²={np2:.3f}" if isinstance(np2, (int, float)) else ""
            print(f"    {source:18s}  F={F:>6.3f}  p={p:.4f}{np2_str}")
    _print_aov("RT  (ms)", aov_rt)
    _print_aov("Acc      ", aov_acc)

    # ----------------------------------------------------------------
    # Secondary: ΔRT に対する補助検定（被験者内ペア比較）
    # ----------------------------------------------------------------
    print("\n[3/4] Within-subject paired tests on ΔRT and ΔAccuracy...")
    secondary = {}
    for col, label in [("delta_rt_ms", "ΔRT (ms)"),
                       ("delta_acc", "ΔAccuracy")]:
        normality = shapiro_per_condition(deltas, col)
        paired = paired_ttest_within_subject(deltas, col)
        wilcoxon = wilcoxon_within_subject(deltas, col)
        secondary[col] = {
            "shapiro": normality,
            "paired_ttest": paired,
            "wilcoxon_signed_rank": wilcoxon,
        }

        print(f"\n  --- {label} ---")
        print(f"  Shapiro-Wilk (per condition):")
        for cond, info in normality.items():
            if "p" not in info:
                print(f"    {cond}: {info.get('reason')}")
                continue
            flag = "ok" if info["normal_at_0.05"] else "VIOLATED"
            print(f"    {cond}: W={info['W']:.3f}  p={info['p']:.4f}  [{flag}]")

        if "p" in paired:
            print(f"  Paired t-test (EMS−Volu): t={paired['t']:+.3f}  p={paired['p']:.4f}  "
                  f"dz={paired['cohens_dz']:+.3f}  "
                  f"(EMS={paired['mean_ems']:+.3g}±{paired['sd_ems']:.3g}, "
                  f"Volu={paired['mean_volu']:+.3g}±{paired['sd_volu']:.3g}, "
                  f"n_pairs={paired['n_pairs']})")
        else:
            print(f"  Paired t-test:    skipped — {paired.get('reason')}")

        if "p" in wilcoxon:
            print(f"  Wilcoxon signed:  W={wilcoxon['W']:.1f}  p={wilcoxon['p']:.4f}  "
                  f"(median EMS={wilcoxon['median_ems']:+.3g}, "
                  f"Volu={wilcoxon['median_volu']:+.3g}, "
                  f"n_pairs={wilcoxon['n_pairs']})")
        else:
            print(f"  Wilcoxon signed:  skipped — {wilcoxon.get('reason')}")

        all_normal = all(info.get("normal_at_0.05", False) for info in normality.values()
                         if "p" in info)
        if all_normal:
            print(f"  → 正規性 OK: RM ANOVA / paired t-test を主たる推論に用いる")
        else:
            print(f"  → 正規性違反あり: Wilcoxon signed-rank を主たる推論に用いる")

    # ----------------------------------------------------------------
    # プロット
    # ----------------------------------------------------------------
    print("\n[4/4] Saving plots...")
    plots = []
    plots += plot_rt_distributions(df, out_dir)
    plots += plot_phase_trajectory(summary, out_dir)
    plots += plot_delta_boxplots(deltas, out_dir)
    plots += plot_sat_scatter(deltas, out_dir)
    plots += plot_within_subject_pair(deltas, out_dir)
    print(f"  Saved {len(plots)} plots")

    # ----------------------------------------------------------------
    # JSON レポート
    # ----------------------------------------------------------------
    report = {
        "n_subjects": int(df["SubjectID"].nunique()),
        "n_per_condition": df.groupby("Condition")["SubjectID"].nunique().to_dict(),
        "n_trials_total": int(len(df)),
        "intervention_modes": df["InterventionMode"].unique().tolist(),
        "rt_bounds_ms": [min_rt, max_rt],
        "primary_rm_anova": {
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


def main():
    parser = argparse.ArgumentParser(description="FastestBaseline RT training effect analysis")
    parser.add_argument("--data_dir", required=True, help="ExperimentData root")
    parser.add_argument("--outdir", required=True, help="Output directory")
    parser.add_argument("--min_rt", type=float, default=100)
    parser.add_argument("--max_rt", type=float, default=1000)
    parser.add_argument("--intervention_mode",
                        choices=["Fastest", "Deadline"], default=None,
                        help="Filter to a single InterventionMode. "
                             "Default: if data has multiple modes, run each in its own subdir.")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    out_dir = Path(args.outdir); out_dir.mkdir(parents=True, exist_ok=True)

    print("Loading subject data...")
    df = load_all_subjects(data_dir)
    print(f"Loaded {len(df)} trials, {df['SubjectID'].nunique()} subjects")

    df = preprocess(df, intervention_mode_filter=args.intervention_mode)
    if args.intervention_mode:
        print(f"Filtered to InterventionMode={args.intervention_mode}: {len(df)} trials")
    print(f"After preprocessing: {len(df)} trials (analysis phases only)")
    print(f"InterventionMode counts: {df['InterventionMode'].value_counts().to_dict()}")

    # Fastest と Deadline は別の介入なので、両方含まれているなら出力を分ける。
    # Filter 指定時は単一モードに絞り込み済みなので分割しない。
    modes_in_data = df["InterventionMode"].unique().tolist()
    if len(modes_in_data) > 1 and args.intervention_mode is None:
        print(f"\n>>> Multiple InterventionModes present: {modes_in_data}. "
              f"Running separately under {out_dir}/intervention_<Mode>/")
        for mode in modes_in_data:
            sub_df = df[df["InterventionMode"] == mode].copy()
            sub_out = out_dir / f"intervention_{mode}"
            print(f"\n===== InterventionMode={mode} ({len(sub_df)} trials) =====")
            run_analysis(sub_df, sub_out, args.min_rt, args.max_rt)
    else:
        run_analysis(df, out_dir, args.min_rt, args.max_rt)


if __name__ == "__main__":
    main()
