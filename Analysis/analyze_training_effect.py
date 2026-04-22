"""
analyze_training_effect.py

V3: CRT特化 + HDDM (階層型ドリフト拡散モデル) 解析対応

分析内容:
1. 従来分析: RT Gain計算 + 群間比較（t検定）
2. HDDM解析: ベイズ推定でDDMパラメータ (a, t) を分離
   - a: Decision threshold (決定閾値) — 慎重さの指標
   - v: Drift rate (ドリフト率) — 情報蓄積速度
   - t: Non-decision time (非決定時間) — 知覚処理+運動実行の時間
3. RT分布プロット: 正答/誤答別のヒストグラム

新CSVフォーマット:
  SubjectID,Group,Phase,TrialNumber,TargetSide,ResponseSide,IsCorrect,ReactionTime_ms,EMSOffset_ms,EMSFireTiming_ms,AgencyLikert,Timestamp

  EMSOffset_ms     : 速めたい量（BaselineRTより何ms前倒しして押させたいか = Agency研究の pre-emptive gain）
  EMSFireTiming_ms : 実発火タイミング（刺激提示から何ms後にEMSを発火したか = BaselineRT - Offset - EMSLatency）

使用例:
  python analyze_training_effect.py --data_dir <subject_data_root> --outdir <output_dir>
"""

import argparse
import json
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests
import matplotlib.pyplot as plt
import seaborn as sns

# 統計パッケージ（オプショナル）
try:
    import pingouin as pg
    HAS_PINGOUIN = True
except ImportError:
    HAS_PINGOUIN = False
    print("Warning: pingouin not installed. Mixed ANOVA will be skipped.")

# HDDM / ベイズ推定パッケージ（オプショナル）
try:
    import pymc as pm
    import arviz as az
    HAS_PYMC = True
except ImportError:
    HAS_PYMC = False
    print("Warning: pymc/arviz not installed. HDDM analysis will be skipped.")
    print("Install with: pip install pymc arviz")


# =====================================================================
# データ読み込み（V3 CSVフォーマット対応）
# =====================================================================

def load_all_subjects(data_dir: Path) -> pd.DataFrame:
    """
    全被験者のtrial_log.csvを読み込み、統合
    V3フォーマット: SubjectID,Group,Phase,...
    """
    all_data = []

    for subject_dir in data_dir.iterdir():
        if not subject_dir.is_dir():
            continue

        # 最新のセッションを探す（session_XX_...）
        sessions = sorted([
            d for d in subject_dir.iterdir()
            if d.is_dir() and d.name.startswith("session_")
        ], reverse=True)

        if not sessions:
            print(f"Warning: No session for {subject_dir.name}, skipping.")
            continue

        session_dir = sessions[0]
        trial_log = session_dir / "trial_log.csv"

        if not trial_log.exists():
            print(f"Warning: No trial_log.csv in {session_dir}, skipping.")
            continue

        df = pd.read_csv(trial_log)
        all_data.append(df)

    if not all_data:
        raise ValueError("No valid subject data found.")

    return pd.concat(all_data, ignore_index=True)


def preprocess(df: pd.DataFrame, min_rt: float = 100, max_rt: float = 1000) -> pd.DataFrame:
    """
    前処理:
    - EMSLatencyフェーズを除外（DDM解析には使わない）
    - Practiceフェーズを除外（習熟用）
    - RT外れ値除去
    """
    # 解析対象フェーズのみ
    analysis_phases = ["Baseline", "Training", "PostTest"]
    df = df[df["Phase"].isin(analysis_phases)].copy()

    # タイムアウト（RT=-1）を除外
    df = df[df["ReactionTime_ms"] > 0].copy()

    # RT外れ値除去
    original_n = len(df)
    df = df[(df["ReactionTime_ms"] >= min_rt) & (df["ReactionTime_ms"] <= max_rt)].copy()
    removed_n = original_n - len(df)
    removed_pct = (removed_n / original_n * 100) if original_n > 0 else 0
    print(f"Outlier removal: {removed_n}/{original_n} ({removed_pct:.1f}%) removed")

    return df


# =====================================================================
# 従来分析: RT Gain
# =====================================================================

def compute_rt_gain(df: pd.DataFrame) -> pd.DataFrame:
    """
    RT Gain計算: PostTest_RT - Baseline_RT
    CRT特化のため、タスク軸はなし（被験者×群のみ）
    """
    results = []

    for (subject_id, group), g in df.groupby(["SubjectID", "Group"]):
        # 正解試行のみ使用
        correct = g[g["IsCorrect"] == 1]

        baseline = correct[correct["Phase"] == "Baseline"]["ReactionTime_ms"]
        posttest = correct[correct["Phase"] == "PostTest"]["ReactionTime_ms"]

        if baseline.empty or posttest.empty:
            continue

        baseline_rt = baseline.median()
        posttest_rt = posttest.median()
        gain = posttest_rt - baseline_rt

        results.append({
            "SubjectID": subject_id,
            "Group": group,
            "baseline_rt": baseline_rt,
            "posttest_rt": posttest_rt,
            "rt_gain": gain,
            "n_baseline": len(baseline),
            "n_posttest": len(posttest)
        })

    return pd.DataFrame(results)


def run_group_comparison(gain_df: pd.DataFrame) -> Dict:
    """
    群間比較: AgencyEMS vs Voluntary
    - 独立t検定 + Cohen's d
    - BH-FDR 多重比較補正
    - ベイズファクター BF10（pingouin利用可能時）
    """
    agency = gain_df[gain_df["Group"] == "AgencyEMS"]["rt_gain"]
    voluntary = gain_df[gain_df["Group"] == "Voluntary"]["rt_gain"]

    results = {
        "agency_mean": float(agency.mean()) if len(agency) > 0 else None,
        "agency_sd": float(agency.std()) if len(agency) > 0 else None,
        "agency_n": int(len(agency)),
        "voluntary_mean": float(voluntary.mean()) if len(voluntary) > 0 else None,
        "voluntary_sd": float(voluntary.std()) if len(voluntary) > 0 else None,
        "voluntary_n": int(len(voluntary)),
    }

    # 全p値を収集して最後にFDR補正
    all_p_values = []
    all_test_names = []

    if len(agency) >= 2 and len(voluntary) >= 2:
        t_stat, p_val = stats.ttest_ind(agency, voluntary)
        pooled_std = np.sqrt(
            ((len(agency)-1)*agency.std()**2 + (len(voluntary)-1)*voluntary.std()**2) /
            (len(agency) + len(voluntary) - 2)
        )
        cohens_d = (agency.mean() - voluntary.mean()) / pooled_std if pooled_std > 0 else 0

        results.update({
            "t_statistic": float(t_stat),
            "p_value_uncorrected": float(p_val),
            "cohens_d": float(cohens_d),
        })
        all_p_values.append(p_val)
        all_test_names.append("group_comparison")

        # ベイズファクター BF10（pingouin利用可能時）
        if HAS_PINGOUIN:
            try:
                bf_result = pg.ttest(agency, voluntary, paired=False)
                bf10 = float(bf_result["BF10"].values[0])
                results["bf10"] = bf10
            except Exception as e:
                print(f"Warning: BF10 calculation failed: {e}")

    # One-sample t-test: 各群のGain vs 0
    one_sample = []
    for group_name, group_data in [("AgencyEMS", agency), ("Voluntary", voluntary)]:
        if len(group_data) >= 2:
            t_stat, p_val = stats.ttest_1samp(group_data, 0)
            test_result = {
                "group": group_name,
                "mean_gain": float(group_data.mean()),
                "sd": float(group_data.std()),
                "n": int(len(group_data)),
                "t_statistic": float(t_stat),
                "p_value_uncorrected": float(p_val),
            }
            all_p_values.append(p_val)
            all_test_names.append(f"one_sample_{group_name}")

            # BF10
            if HAS_PINGOUIN:
                try:
                    bf_result = pg.ttest(group_data, 0)
                    test_result["bf10"] = float(bf_result["BF10"].values[0])
                except Exception:
                    pass

            one_sample.append(test_result)

    # BH-FDR 多重比較補正
    if len(all_p_values) >= 2:
        rejected, corrected_p, _, _ = multipletests(all_p_values, method="fdr_bh")
        correction_map = dict(zip(all_test_names, corrected_p))

        if "group_comparison" in correction_map:
            results["p_value_fdr"] = float(correction_map["group_comparison"])
            results["significant_fdr"] = bool(correction_map["group_comparison"] < 0.05)

        for test in one_sample:
            key = f"one_sample_{test['group']}"
            if key in correction_map:
                test["p_value_fdr"] = float(correction_map[key])
                test["significant_fdr"] = bool(correction_map[key] < 0.05)
    else:
        # 補正不要（検定1つのみ）
        if "p_value_uncorrected" in results:
            results["p_value_fdr"] = results["p_value_uncorrected"]
            results["significant_fdr"] = results["p_value_uncorrected"] < 0.05
        for test in one_sample:
            test["p_value_fdr"] = test["p_value_uncorrected"]
            test["significant_fdr"] = test["p_value_uncorrected"] < 0.05

    results["one_sample_tests"] = one_sample
    results["correction_method"] = "BH-FDR"
    return results


# =====================================================================
# HDDM解析（スケルトン）
# =====================================================================

def prepare_hddm_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    HDDM用データフォーマットに変換
    HDDM標準入力形式:
      subj_idx: 被験者ID
      response: 正答=1, 誤答=0
      rt: 反応時間（秒単位）
      condition: 条件ラベル
    """
    hddm_df = pd.DataFrame({
        "subj_idx": df["SubjectID"],
        "response": df["IsCorrect"].astype(int),
        "rt": df["ReactionTime_ms"] / 1000.0,  # 秒に変換
        "condition": df["Phase"] + "_" + df["Group"],
        "phase": df["Phase"],
        "group": df["Group"]
    })

    return hddm_df


def run_hddm_analysis(df: pd.DataFrame, output_dir: Path) -> Optional[Dict]:
    """
    HDDM (Hierarchical Drift Diffusion Model) 解析
    PyMCを用いたベイズ推定でDDMパラメータを推定

    推定パラメータ:
      a: Decision threshold（決定閾値）— 慎重さの指標
      v: Drift rate（ドリフト率）— 情報蓄積速度
      t: Non-decision time（非決定時間）— 知覚+運動の時間

    比較:
      Baseline vs PostTest の a, t の変化を群間で比較

    注意: これはスケルトン実装です。実際の使用時にはサンプリング設定の
    チューニングが必要です。
    """
    if not HAS_PYMC:
        print("PyMC not available. Skipping HDDM analysis.")
        return None

    hddm_df = prepare_hddm_data(df)

    # Baseline と PostTest のみを使用
    analysis_df = hddm_df[hddm_df["phase"].isin(["Baseline", "PostTest"])].copy()

    if len(analysis_df) < 50:
        print(f"Warning: Only {len(analysis_df)} trials available. HDDM may not converge.")

    print("\n=== HDDM Analysis (PyMC) ===")
    print(f"Total trials: {len(analysis_df)}")
    print(f"Subjects: {analysis_df['subj_idx'].nunique()}")
    print(f"Conditions: {analysis_df['condition'].unique()}")

    # ─── 階層DDMモデル定義 ───
    # 各条件（Phase×Group）でのパラメータを推定
    conditions = analysis_df["condition"].unique()
    condition_idx = pd.Categorical(analysis_df["condition"], categories=conditions).codes

    rt_observed = analysis_df["rt"].values
    response_observed = analysis_df["response"].values

    try:
        with pm.Model() as ddm_model:
            # ── 階層事前分布（全条件共通の親分布） ──

            # Decision threshold (a): 0.5〜3.0 程度
            a_mu = pm.HalfNormal("a_mu", sigma=1.0)
            a_sigma = pm.HalfNormal("a_sigma", sigma=0.5)
            a = pm.HalfNormal("a", sigma=a_sigma, shape=len(conditions))

            # Non-decision time (t): 0.1〜0.5秒程度
            t_mu = pm.HalfNormal("t_mu", sigma=0.3)
            t_sigma = pm.HalfNormal("t_sigma", sigma=0.1)
            t = pm.HalfNormal("t", sigma=t_sigma, shape=len(conditions))

            # Drift rate (v): -5〜+5 程度
            v_mu = pm.Normal("v_mu", mu=1.0, sigma=2.0)
            v_sigma = pm.HalfNormal("v_sigma", sigma=1.0)
            v = pm.Normal("v", mu=v_mu, sigma=v_sigma, shape=len(conditions))

            # ── 尤度（簡易版: 正規分布近似） ──
            # 注: 完全なDDMの尤度関数はWiener first-passage timeの密度関数だが、
            #     ここでは正規分布で近似したスケルトンを実装。
            #     本格運用時は hddm ライブラリまたはカスタムWiener分布を使用すること。

            predicted_rt = t[condition_idx] + a[condition_idx] / (2.0 * pm.math.abs(v[condition_idx]) + 0.001)
            rt_sigma = pm.HalfNormal("rt_sigma", sigma=0.2)

            rt_obs = pm.Normal(
                "rt_obs",
                mu=predicted_rt,
                sigma=rt_sigma,
                observed=rt_observed
            )

            # ── サンプリング ──
            print("Starting MCMC sampling (this may take several minutes)...")
            trace = pm.sample(
                draws=1000,
                tune=500,
                chains=2,
                cores=1,  # Unity解析環境のため1コア推奨
                return_inferencedata=True,
                progressbar=True
            )

        # ── 結果の要約 ──
        summary = az.summary(trace, var_names=["a", "t", "v"])
        print("\nDDM Parameter Summary:")
        print(summary)

        # 結果をCSV保存
        summary.to_csv(output_dir / "hddm_summary.csv")

        # トレースプロット保存
        fig = az.plot_trace(trace, var_names=["a", "t", "v"])
        plt.tight_layout()
        plt.savefig(output_dir / "hddm_trace.png", dpi=150)
        plt.close()

        # 条件別パラメータの比較
        results = {
            "conditions": list(conditions),
            "summary": summary.to_dict(),
        }

        # Baseline vs PostTest のパラメータ差分
        for group in ["AgencyEMS", "Voluntary"]:
            baseline_key = f"Baseline_{group}"
            posttest_key = f"PostTest_{group}"

            if baseline_key in conditions and posttest_key in conditions:
                b_idx = list(conditions).index(baseline_key)
                p_idx = list(conditions).index(posttest_key)

                a_posterior_diff = (trace.posterior["a"].sel(a_dim_0=p_idx) -
                                   trace.posterior["a"].sel(a_dim_0=b_idx))
                t_posterior_diff = (trace.posterior["t"].sel(t_dim_0=p_idx) -
                                   trace.posterior["t"].sel(t_dim_0=b_idx))

                results[f"{group}_a_diff_mean"] = float(a_posterior_diff.mean())
                results[f"{group}_a_diff_hdi"] = az.hdi(a_posterior_diff.values.flatten()).tolist()
                results[f"{group}_t_diff_mean"] = float(t_posterior_diff.mean())
                results[f"{group}_t_diff_hdi"] = az.hdi(t_posterior_diff.values.flatten()).tolist()

                print(f"\n{group}: Baseline → PostTest parameter changes:")
                print(f"  Δa (threshold): {results[f'{group}_a_diff_mean']:.4f}")
                print(f"  Δt (non-decision): {results[f'{group}_t_diff_mean']:.4f}")

        return results

    except Exception as e:
        print(f"HDDM analysis failed: {e}")
        print("This is a skeleton implementation. Check data format and model specification.")
        return {"error": str(e)}


# =====================================================================
# RT分布プロット（正答/誤答別）
# =====================================================================

def plot_rt_distributions(df: pd.DataFrame, output_dir: Path) -> List[Path]:
    """
    RT分布のヒストグラム（正答/誤答別）
    DDM解析では正答・誤答のRT分布形状が重要な情報源
    """
    plots = []

    # Baseline と PostTest のRT分布を比較
    for phase in ["Baseline", "PostTest"]:
        phase_data = df[df["Phase"] == phase]
        if phase_data.empty:
            continue

        fig, axes = plt.subplots(1, 2, figsize=(14, 5))

        for i, group in enumerate(["AgencyEMS", "Voluntary"]):
            ax = axes[i]
            group_data = phase_data[phase_data["Group"] == group]

            if group_data.empty:
                ax.set_title(f"{group} - No data")
                continue

            correct = group_data[group_data["IsCorrect"] == 1]["ReactionTime_ms"]
            error = group_data[group_data["IsCorrect"] == 0]["ReactionTime_ms"]

            # 正答RTヒストグラム
            if len(correct) > 0:
                ax.hist(correct, bins=30, alpha=0.7, color="steelblue",
                        label=f"Correct (n={len(correct)})", density=True)

            # 誤答RTヒストグラム（負の軸に反転して表示 = DDM慣習）
            if len(error) > 0:
                ax.hist(error, bins=15, alpha=0.7, color="salmon",
                        label=f"Error (n={len(error)})", density=True)

            ax.set_xlabel("Reaction Time (ms)")
            ax.set_ylabel("Density")
            ax.set_title(f"{group} — {phase}")
            ax.legend()
            ax.set_xlim(0, 1000)

        plt.suptitle(f"RT Distribution: {phase} (Correct vs Error)", fontsize=14)
        plot_path = output_dir / f"rt_distribution_{phase.lower()}.png"
        plt.tight_layout()
        plt.savefig(plot_path, dpi=150)
        plt.close()
        plots.append(plot_path)

    # 全フェーズ重ね合わせ（群別）
    for group in ["AgencyEMS", "Voluntary"]:
        group_data = df[df["Group"] == group]
        if group_data.empty:
            continue

        fig, ax = plt.subplots(figsize=(10, 6))

        for phase, color in [("Baseline", "gray"), ("PostTest", "steelblue")]:
            phase_data = group_data[(group_data["Phase"] == phase) & (group_data["IsCorrect"] == 1)]
            if len(phase_data) > 0:
                ax.hist(phase_data["ReactionTime_ms"], bins=30, alpha=0.5,
                        color=color, label=f"{phase} (n={len(phase_data)})", density=True)

        ax.set_xlabel("Reaction Time (ms)")
        ax.set_ylabel("Density")
        ax.set_title(f"{group}: Baseline vs PostTest RT Distribution (Correct only)")
        ax.legend()
        ax.set_xlim(0, 1000)

        plot_path = output_dir / f"rt_overlay_{group.lower()}.png"
        plt.tight_layout()
        plt.savefig(plot_path, dpi=150)
        plt.close()
        plots.append(plot_path)

    return plots


# =====================================================================
# 従来プロット
# =====================================================================

def create_gain_plots(gain_df: pd.DataFrame, output_dir: Path) -> List[Path]:
    """RT Gain の箱ひげ図 + 個人プロット"""
    plots = []

    # 1. RT Gain by Group（箱ひげ図）
    fig, ax = plt.subplots(figsize=(8, 6))
    sns.boxplot(data=gain_df, x="Group", y="rt_gain", ax=ax, palette="Set2")
    sns.stripplot(data=gain_df, x="Group", y="rt_gain", ax=ax,
                  color="black", alpha=0.5, jitter=True)
    ax.axhline(y=0, color='gray', linestyle='--', alpha=0.5)
    ax.set_xlabel("Group")
    ax.set_ylabel("RT Gain (ms)\n(negative = faster)")
    ax.set_title("Reaction Time Gain: AgencyEMS vs Voluntary")

    plot_path = output_dir / "rt_gain_boxplot.png"
    plt.tight_layout()
    plt.savefig(plot_path, dpi=150)
    plt.close()
    plots.append(plot_path)

    # 2. Pre/Post比較（ペアプロット）
    fig, ax = plt.subplots(figsize=(8, 6))

    for group, color in [("AgencyEMS", "steelblue"), ("Voluntary", "coral")]:
        group_data = gain_df[gain_df["Group"] == group]
        for _, row in group_data.iterrows():
            ax.plot([0, 1], [row["baseline_rt"], row["posttest_rt"]],
                    'o-', color=color, alpha=0.4)

        # 群平均
        mean_bl = group_data["baseline_rt"].mean()
        mean_pt = group_data["posttest_rt"].mean()
        ax.plot([0, 1], [mean_bl, mean_pt], 's-', color=color,
                markersize=12, linewidth=3, label=f"{group} (mean)")

    ax.set_xticks([0, 1])
    ax.set_xticklabels(["Baseline", "PostTest"])
    ax.set_ylabel("Reaction Time (ms)")
    ax.set_title("Pre/Post Reaction Times by Group")
    ax.legend()

    plot_path = output_dir / "rt_pre_post.png"
    plt.tight_layout()
    plt.savefig(plot_path, dpi=150)
    plt.close()
    plots.append(plot_path)

    return plots


# =====================================================================
# Calibration階段法の可視化
# =====================================================================

def plot_calibration_staircase(df: pd.DataFrame, output_dir: Path) -> List[Path]:
    """
    Calibrationフェーズの階段法データを可視化:
    1. 各被験者の左右別Offset推移（階段プロット）
    2. 全被験者のAgency回答 vs Offset（心理測定関数風）
    """
    plots = []
    cal_data = df[df["Phase"] == "Calibration"].copy()
    if cal_data.empty:
        print("No Calibration data found.")
        return plots

    subjects = cal_data["SubjectID"].unique()

    # ── 1. 被験者ごとの階段プロット ──
    for subject in subjects:
        sub_data = cal_data[cal_data["SubjectID"] == subject].sort_values("TrialNumber")

        fig, axes = plt.subplots(1, 2, figsize=(14, 5), sharey=True)

        for i, side in enumerate(["Left", "Right"]):
            ax = axes[i]
            side_data = sub_data[sub_data["TargetSide"] == side]

            if side_data.empty:
                ax.set_title(f"{side} — No data")
                continue

            trials = range(1, len(side_data) + 1)
            offsets = side_data["EMSOffset_ms"].values
            agencies = side_data["AgencyYes"].values
            corrects = side_data["IsCorrect"].values

            # オフセット推移
            ax.plot(trials, offsets, 'o-', color="steelblue", markersize=4, alpha=0.7)

            # Agency回答をカラーマップで表示
            for t, offset, agency, correct in zip(trials, offsets, agencies, corrects):
                if not correct:
                    ax.plot(t, offset, 'x', color="red", markersize=8, zorder=5)
                else:
                    color = "green" if agency else "red"  # True=緑(Yes), False=赤(No)
                    ax.plot(t, offset, 'o', color=color, markersize=6, zorder=5)

            ax.axhline(y=0, color='gray', linestyle='--', alpha=0.5)
            ax.set_xlabel("Trial")
            ax.set_ylabel("EMS Offset (ms)")
            ax.set_title(f"{side} — Staircase")

        plt.suptitle(f"{subject}: Calibration Staircase", fontsize=14)
        plot_path = output_dir / f"calibration_staircase_{subject}.png"
        plt.tight_layout()
        plt.savefig(plot_path, dpi=150)
        plt.close()
        plots.append(plot_path)

    # ── 2. 全被験者集約: Offset vs Agency（心理測定関数風） ──
    correct_cal = cal_data[cal_data["IsCorrect"] == 1].copy()
    if len(correct_cal) > 10:
        fig, ax = plt.subplots(figsize=(10, 6))

        # Offsetを5ms幅でビン化
        correct_cal["offset_bin"] = (correct_cal["EMSOffset_ms"] / 5).round() * 5
        # Yes の割合を計算
        correct_cal["agency_yes"] = correct_cal["AgencyYes"].astype(int)

        binned = correct_cal.groupby("offset_bin").agg(
            agency_rate=("agency_yes", "mean"),
            n=("agency_yes", "count")
        ).reset_index()

        # 十分なデータがあるビンのみ
        binned = binned[binned["n"] >= 3]

        ax.plot(binned["offset_bin"], binned["agency_rate"],
                'o-', color="steelblue", markersize=8)

        # サンプルサイズをアノテーション
        for _, row in binned.iterrows():
            ax.annotate(f'n={int(row["n"])}',
                       (row["offset_bin"], row["agency_rate"]),
                       textcoords="offset points", xytext=(0, 10),
                       fontsize=8, ha='center', alpha=0.7)

        ax.axhline(y=0.5, color='gray', linestyle='--', alpha=0.5)
        ax.set_xlabel("EMS Offset (ms)")
        ax.set_ylabel("P(Agency = Yes)")
        ax.set_title("Psychometric Function: Agency vs EMS Offset (All Subjects)")
        ax.set_ylim(-0.05, 1.05)

        plot_path = output_dir / "calibration_psychometric.png"
        plt.tight_layout()
        plt.savefig(plot_path, dpi=150)
        plt.close()
        plots.append(plot_path)

    return plots


# =====================================================================
# Main
# =====================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Analyze CRT training effect with HDDM (V3)")
    parser.add_argument("--data_dir", required=True,
                        help="Root directory containing subject folders")
    parser.add_argument("--outdir", required=True,
                        help="Output directory")
    parser.add_argument("--min_rt", type=float, default=100,
                        help="Minimum valid RT (ms)")
    parser.add_argument("--max_rt", type=float, default=1000,
                        help="Maximum valid RT (ms)")
    parser.add_argument("--skip_hddm", action="store_true",
                        help="Skip HDDM analysis (faster)")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    output_dir = Path(args.outdir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── データ読み込み ──
    print("Loading subject data...")
    df = load_all_subjects(data_dir)
    print(f"Loaded {len(df)} trials from {df['SubjectID'].nunique()} subjects")

    # ── 前処理 ──
    df = preprocess(df, min_rt=args.min_rt, max_rt=args.max_rt)
    print(f"After preprocessing: {len(df)} trials")

    # ── RT分布プロット（正答/誤答別）──
    print("\nCreating RT distribution plots...")
    rt_plots = plot_rt_distributions(df, output_dir)
    print(f"Saved {len(rt_plots)} RT distribution plots")

    # ── RT Gain計算 ──
    print("\nComputing RT gains...")
    gain_df = compute_rt_gain(df)
    gain_df.to_csv(output_dir / "rt_gains.csv", index=False)
    print(f"Computed gains for {len(gain_df)} subjects")

    # ── 記述統計 ──
    print("\n=== Descriptive Statistics ===")
    desc_stats = gain_df.groupby("Group")["rt_gain"].agg(["mean", "std", "count"])
    print(desc_stats)
    desc_stats.to_csv(output_dir / "descriptive_stats.csv")

    # ── 群間比較 ──
    print("\n=== Group Comparison ===")
    comparison = run_group_comparison(gain_df)

    if "t_statistic" in comparison:
        sig_fdr = "*" if comparison.get("significant_fdr", False) else ""
        print(f"  AgencyEMS: {comparison['agency_mean']:.1f}±{comparison['agency_sd']:.1f}ms (n={comparison['agency_n']})")
        print(f"  Voluntary: {comparison['voluntary_mean']:.1f}±{comparison['voluntary_sd']:.1f}ms (n={comparison['voluntary_n']})")
        print(f"  t={comparison['t_statistic']:.2f}, p={comparison['p_value_uncorrected']:.4f}, "
              f"p_fdr={comparison.get('p_value_fdr', 'N/A')}{sig_fdr}, d={comparison['cohens_d']:.2f}")
        if "bf10" in comparison:
            print(f"  BF10={comparison['bf10']:.2f}")
        print(f"  (Correction: {comparison.get('correction_method', 'none')})")

    print("\n--- One-sample t-tests (Gain vs 0) ---")
    for test in comparison.get("one_sample_tests", []):
        sig_fdr = "*" if test.get("significant_fdr", False) else ""
        bf_str = f", BF10={test['bf10']:.2f}" if "bf10" in test else ""
        print(f"  {test['group']}: M={test['mean_gain']:.1f}ms, "
              f"t={test['t_statistic']:.2f}, p={test['p_value_uncorrected']:.4f}, "
              f"p_fdr={test.get('p_value_fdr', 'N/A')}{sig_fdr}{bf_str}")

    # ── Gainプロット ──
    print("\nCreating gain plots...")
    gain_plots = create_gain_plots(gain_df, output_dir)
    print(f"Saved {len(gain_plots)} gain plots")

    # ── HDDM解析 ──
    hddm_results = None
    if not args.skip_hddm:
        # 全試行（正答+誤答）を使用（DDMでは誤答RTも情報源）
        df_for_hddm = df.copy()
        print(f"\nHDDM input: {len(df_for_hddm)} trials (including errors)")
        hddm_results = run_hddm_analysis(df_for_hddm, output_dir)
    else:
        print("\nHDDM analysis skipped (--skip_hddm flag).")

    # ── Calibration階段法の可視化 ──
    print("\nAnalyzing Calibration staircase data...")
    df_all = load_all_subjects(data_dir)  # 全フェーズ含む
    cal_plots = plot_calibration_staircase(df_all, output_dir)
    print(f"Saved {len(cal_plots)} calibration plots")

    # ── 結果をJSONで保存 ──
    results = {
        "n_subjects": int(df["SubjectID"].nunique()),
        "n_subjects_per_group": df.groupby("Group")["SubjectID"].nunique().to_dict(),
        "total_trials": int(len(df)),
        "group_comparison": comparison,
        "hddm": hddm_results,
        "plots": [str(p) for p in rt_plots + gain_plots + cal_plots]
    }

    results_path = output_dir / "analysis_results.json"
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)

    print(f"\nResults saved to {results_path}")


if __name__ == "__main__":
    main()
