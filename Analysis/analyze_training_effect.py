"""
analyze_training_effect.py

RT Gain（訓練効果）の分析スクリプト
Kasahara et al. (CHI '21) の分析手法に準拠

分析内容:
1. RT Gain計算: POST_RT - PRE_RT（Baseline）
2. 2×3 混合計画ANOVA（群 × タスク）
3. 事後検定（Tukey HSD）
4. 各条件でのone-sample t-test（vs 0）
5. 効果量（Cohen's d）

使用例:
python analyze_training_effect.py --data_dir <subject_data_root> --outdir <output_dir>
"""

import argparse
import json
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from scipy import stats
import matplotlib.pyplot as plt
import seaborn as sns

# 統計パッケージ
try:
    import pingouin as pg
    HAS_PINGOUIN = True
except ImportError:
    HAS_PINGOUIN = False
    print("Warning: pingouin not installed. Mixed ANOVA will be skipped.")
    print("Install with: pip install pingouin")


def load_all_subjects(data_dir: Path) -> pd.DataFrame:
    """全被験者のtrial_log.csvを読み込み、統合"""
    all_data = []
    
    for subject_dir in data_dir.iterdir():
        if not subject_dir.is_dir():
            continue
        
        config_path = subject_dir / "config.json"
        if not config_path.exists():
            continue
        
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        
        subject_id = config.get("SubjectId", subject_dir.name)
        group = config.get("Group", "Unknown")
        
        # 最新のvalidationセッションを探す
        validation_sessions = sorted([
            d for d in subject_dir.iterdir() 
            if d.is_dir() and d.name.startswith("validation_")
        ], reverse=True)
        
        if not validation_sessions:
            print(f"Warning: No validation session for {subject_id}, skipping.")
            continue
        
        session_dir = validation_sessions[0]
        trial_log = session_dir / "trial_log.csv"
        
        if not trial_log.exists():
            print(f"Warning: No trial_log.csv in {session_dir}, skipping.")
            continue
        
        df = pd.read_csv(trial_log)
        df["subject_id"] = subject_id
        df["group"] = group
        all_data.append(df)
    
    if not all_data:
        raise ValueError("No valid subject data found.")
    
    return pd.concat(all_data, ignore_index=True)


def filter_outliers(df: pd.DataFrame, rt_col: str = "reaction_time_ms",
                    min_rt: float = 100, max_rt: float = 1000) -> pd.DataFrame:
    """外れ値除去（論文準拠: 100ms未満、1000ms超を除外）"""
    original_n = len(df)
    df_filtered = df[(df[rt_col] >= min_rt) & (df[rt_col] <= max_rt)].copy()
    removed_n = original_n - len(df_filtered)
    removed_pct = (removed_n / original_n * 100) if original_n > 0 else 0
    print(f"Outlier removal: {removed_n}/{original_n} ({removed_pct:.1f}%) removed")
    return df_filtered


def compute_rt_gain(df: pd.DataFrame) -> pd.DataFrame:
    """
    RT Gain計算: POST_RT - Baseline_RT
    各被験者×タスクごとに計算
    """
    results = []
    
    for (subject_id, group, task), g in df.groupby(["subject_id", "group", "task"]):
        # Baselineの中央値RT
        baseline = g[g["phase"] == "Baseline"]["reaction_time_ms"]
        if baseline.empty:
            continue
        baseline_rt = baseline.median()
        
        # PostTestの中央値RT
        posttest = g[g["phase"] == "PostTest"]["reaction_time_ms"]
        if posttest.empty:
            continue
        posttest_rt = posttest.median()
        
        # Gain = POST - PRE（負の値 = 速くなった）
        gain = posttest_rt - baseline_rt
        
        results.append({
            "subject_id": subject_id,
            "group": group,
            "task": task,
            "baseline_rt": baseline_rt,
            "posttest_rt": posttest_rt,
            "rt_gain": gain,
            "n_baseline": len(baseline),
            "n_posttest": len(posttest)
        })
    
    return pd.DataFrame(results)


def run_mixed_anova(gain_df: pd.DataFrame) -> Dict:
    """
    2×3 混合計画ANOVA
    - 群（Group）: 被験者間要因
    - タスク（Task）: 被験者内要因
    """
    if not HAS_PINGOUIN:
        return {"error": "pingouin not installed"}
    
    # pingouinのmixed_anovaを使用
    aov = pg.mixed_anova(
        data=gain_df,
        dv="rt_gain",
        within="task",
        between="group",
        subject="subject_id"
    )
    
    return {
        "anova_table": aov.to_dict(),
        "summary": aov.to_string()
    }


def run_posthoc_tests(gain_df: pd.DataFrame) -> Dict:
    """事後検定"""
    results = {}
    
    # 1. 各タスクでの群間比較（独立t検定）
    task_comparisons = []
    for task in gain_df["task"].unique():
        task_data = gain_df[gain_df["task"] == task]
        
        agency = task_data[task_data["group"] == "AgencyEMS"]["rt_gain"]
        voluntary = task_data[task_data["group"] == "Voluntary"]["rt_gain"]
        
        if len(agency) >= 2 and len(voluntary) >= 2:
            t_stat, p_val = stats.ttest_ind(agency, voluntary)
            cohens_d = (agency.mean() - voluntary.mean()) / np.sqrt(
                ((len(agency)-1)*agency.std()**2 + (len(voluntary)-1)*voluntary.std()**2) / 
                (len(agency) + len(voluntary) - 2)
            )
            
            task_comparisons.append({
                "task": task,
                "agency_mean": agency.mean(),
                "agency_sd": agency.std(),
                "agency_n": len(agency),
                "voluntary_mean": voluntary.mean(),
                "voluntary_sd": voluntary.std(),
                "voluntary_n": len(voluntary),
                "t_statistic": t_stat,
                "p_value": p_val,
                "cohens_d": cohens_d
            })
    
    results["task_group_comparisons"] = task_comparisons
    
    # 2. 各条件でのone-sample t-test（Gain vs 0）
    one_sample_tests = []
    for (group, task), g in gain_df.groupby(["group", "task"]):
        gains = g["rt_gain"]
        if len(gains) >= 2:
            t_stat, p_val = stats.ttest_1samp(gains, 0)
            one_sample_tests.append({
                "group": group,
                "task": task,
                "mean_gain": gains.mean(),
                "sd": gains.std(),
                "n": len(gains),
                "t_statistic": t_stat,
                "p_value": p_val,
                "significant": p_val < 0.05
            })
    
    results["one_sample_tests"] = one_sample_tests
    
    return results


def run_normality_tests(gain_df: pd.DataFrame) -> Dict:
    """正規性検定（Shapiro-Wilk）"""
    results = []
    
    for (group, task), g in gain_df.groupby(["group", "task"]):
        gains = g["rt_gain"]
        if len(gains) >= 3:
            stat, p_val = stats.shapiro(gains)
            results.append({
                "group": group,
                "task": task,
                "n": len(gains),
                "shapiro_stat": stat,
                "p_value": p_val,
                "normal": p_val > 0.05
            })
    
    return {"shapiro_wilk": results}


def create_plots(gain_df: pd.DataFrame, output_dir: Path) -> List[Path]:
    """可視化"""
    plots = []
    
    # 1. RT Gain by Group and Task（箱ひげ図）
    fig, ax = plt.subplots(figsize=(10, 6))
    sns.boxplot(data=gain_df, x="task", y="rt_gain", hue="group", ax=ax)
    ax.axhline(y=0, color='gray', linestyle='--', alpha=0.5)
    ax.set_xlabel("Task")
    ax.set_ylabel("RT Gain (ms)\n(negative = faster)")
    ax.set_title("Reaction Time Gain by Group and Task")
    ax.legend(title="Group")
    
    plot_path = output_dir / "rt_gain_boxplot.png"
    plt.tight_layout()
    plt.savefig(plot_path, dpi=150)
    plt.close()
    plots.append(plot_path)
    
    # 2. 個人別プロット
    fig, ax = plt.subplots(figsize=(12, 6))
    
    for i, (group, color) in enumerate([("AgencyEMS", "blue"), ("Voluntary", "orange")]):
        group_data = gain_df[gain_df["group"] == group]
        
        for subject in group_data["subject_id"].unique():
            subj_data = group_data[group_data["subject_id"] == subject]
            tasks = subj_data["task"].values
            gains = subj_data["rt_gain"].values
            
            x_pos = np.arange(len(tasks)) + i * 0.3 - 0.15
            ax.scatter(x_pos, gains, alpha=0.6, color=color, s=50)
    
    # 平均線
    for i, (group, color) in enumerate([("AgencyEMS", "blue"), ("Voluntary", "orange")]):
        group_data = gain_df[gain_df["group"] == group]
        means = group_data.groupby("task")["rt_gain"].mean()
        x_pos = np.arange(len(means)) + i * 0.3 - 0.15
        ax.plot(x_pos, means.values, 'o-', color=color, markersize=12, 
                linewidth=2, label=f"{group} (mean)")
    
    ax.axhline(y=0, color='gray', linestyle='--', alpha=0.5)
    ax.set_xticks(range(3))
    ax.set_xticklabels(["SRT", "DRT", "CRT"])
    ax.set_xlabel("Task")
    ax.set_ylabel("RT Gain (ms)")
    ax.set_title("Individual RT Gains (colored dots) with Group Means (lines)")
    ax.legend()
    
    plot_path = output_dir / "rt_gain_individual.png"
    plt.tight_layout()
    plt.savefig(plot_path, dpi=150)
    plt.close()
    plots.append(plot_path)
    
    # 3. Pre/Post比較
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    
    for i, task in enumerate(["SRT", "DRT", "CRT"]):
        ax = axes[i]
        task_data = gain_df[gain_df["task"] == task]
        
        for group, color in [("AgencyEMS", "blue"), ("Voluntary", "orange")]:
            group_data = task_data[task_data["group"] == group]
            
            for _, row in group_data.iterrows():
                ax.plot([0, 1], [row["baseline_rt"], row["posttest_rt"]], 
                       'o-', color=color, alpha=0.4)
        
        ax.set_xticks([0, 1])
        ax.set_xticklabels(["Baseline", "PostTest"])
        ax.set_ylabel("Reaction Time (ms)")
        ax.set_title(f"{task}")
    
    plt.suptitle("Pre/Post Reaction Times by Task")
    plot_path = output_dir / "rt_pre_post.png"
    plt.tight_layout()
    plt.savefig(plot_path, dpi=150)
    plt.close()
    plots.append(plot_path)
    
    return plots


def main():
    parser = argparse.ArgumentParser(description="Analyze RT training effect (Kasahara et al. style)")
    parser.add_argument("--data_dir", required=True, help="Root directory containing subject folders")
    parser.add_argument("--outdir", required=True, help="Output directory")
    parser.add_argument("--min_rt", type=float, default=100, help="Minimum valid RT (ms)")
    parser.add_argument("--max_rt", type=float, default=1000, help="Maximum valid RT (ms)")
    args = parser.parse_args()
    
    data_dir = Path(args.data_dir)
    output_dir = Path(args.outdir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print("Loading subject data...")
    df = load_all_subjects(data_dir)
    print(f"Loaded {len(df)} trials from {df['subject_id'].nunique()} subjects")
    
    # 正解試行のみ使用
    df = df[df["is_correct"] == 1]
    print(f"Correct trials: {len(df)}")
    
    # 外れ値除去
    df = filter_outliers(df, min_rt=args.min_rt, max_rt=args.max_rt)
    
    # RT Gain計算
    print("\nComputing RT gains...")
    gain_df = compute_rt_gain(df)
    gain_df.to_csv(output_dir / "rt_gains.csv", index=False)
    print(f"Computed gains for {len(gain_df)} subject-task combinations")
    
    # 記述統計
    print("\n=== Descriptive Statistics ===")
    desc_stats = gain_df.groupby(["group", "task"])["rt_gain"].agg(["mean", "std", "count"])
    print(desc_stats)
    desc_stats.to_csv(output_dir / "descriptive_stats.csv")
    
    # 正規性検定
    print("\n=== Normality Tests (Shapiro-Wilk) ===")
    normality = run_normality_tests(gain_df)
    for item in normality["shapiro_wilk"]:
        status = "Normal" if item["normal"] else "Non-normal"
        print(f"  {item['group']}-{item['task']}: p={item['p_value']:.4f} ({status})")
    
    # 混合ANOVA
    if HAS_PINGOUIN:
        print("\n=== Mixed ANOVA (Group × Task) ===")
        anova_results = run_mixed_anova(gain_df)
        print(anova_results["summary"])
    else:
        anova_results = {"error": "pingouin not installed"}
    
    # 事後検定
    print("\n=== Post-hoc Tests ===")
    posthoc = run_posthoc_tests(gain_df)
    
    print("\n--- Task-wise Group Comparisons (Independent t-test) ---")
    for comp in posthoc["task_group_comparisons"]:
        sig = "*" if comp["p_value"] < 0.05 else ""
        print(f"  {comp['task']}: AgencyEMS={comp['agency_mean']:.1f}±{comp['agency_sd']:.1f} vs "
              f"Voluntary={comp['voluntary_mean']:.1f}±{comp['voluntary_sd']:.1f}, "
              f"t={comp['t_statistic']:.2f}, p={comp['p_value']:.4f}{sig}, d={comp['cohens_d']:.2f}")
    
    print("\n--- One-sample t-tests (Gain vs 0) ---")
    for test in posthoc["one_sample_tests"]:
        sig = "*" if test["significant"] else ""
        print(f"  {test['group']}-{test['task']}: M={test['mean_gain']:.1f}ms, "
              f"t={test['t_statistic']:.2f}, p={test['p_value']:.4f}{sig}")
    
    # 可視化
    print("\nCreating plots...")
    plots = create_plots(gain_df, output_dir)
    print(f"Saved {len(plots)} plots")
    
    # 結果をJSONで保存
    results = {
        "n_subjects": df["subject_id"].nunique(),
        "n_subjects_per_group": df.groupby("group")["subject_id"].nunique().to_dict(),
        "normality_tests": normality,
        "anova": anova_results,
        "posthoc": posthoc,
        "plots": [str(p) for p in plots]
    }
    
    results_path = output_dir / "analysis_results.json"
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    
    print(f"\nResults saved to {results_path}")


if __name__ == "__main__":
    main()
