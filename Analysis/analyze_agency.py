import argparse
import json
from pathlib import Path
from datetime import datetime
from typing import Tuple, Optional

import numpy as np
import pandas as pd
from scipy import stats
from scipy.optimize import curve_fit
from statsmodels.stats.multicomp import pairwise_tukeyhsd
import matplotlib.pyplot as plt


def iqr_filter(series: pd.Series, lower_k: float = 1.5, upper_k: float = 1.5) -> pd.Series:
    s = series.dropna()
    if s.empty:
        return s
    q1 = s.quantile(0.25)
    q3 = s.quantile(0.75)
    iqr = q3 - q1
    lower = q1 - lower_k * iqr
    upper = q3 + upper_k * iqr
    return s[(s >= lower) & (s <= upper)]


def remove_outliers_within_offset(df: pd.DataFrame) -> pd.DataFrame:
    kept = []
    for _, g in df.groupby("candidate_offset_ms"):
        filtered = iqr_filter(g["agency_likert_7"])
        kept.append(g[g["agency_likert_7"].isin(filtered)])
    if not kept:
        return df.iloc[0:0].copy()
    return pd.concat(kept, ignore_index=True)


def run_oneway_anova(df: pd.DataFrame) -> dict:
    groups = [g["agency_likert_7"].values for _, g in df.groupby("candidate_offset_ms")]
    groups = [g for g in groups if len(g) >= 2]
    if len(groups) < 2:
        return {"available": False, "reason": "ANOVA requires at least 2 offset groups with n>=2."}
    f_val, p_val = stats.f_oneway(*groups)
    return {"available": True, "f_value": float(f_val), "p_value": float(p_val)}


def run_tukey(df: pd.DataFrame) -> pd.DataFrame:
    res = pairwise_tukeyhsd(
        endog=df["agency_likert_7"].astype(float),
        groups=df["candidate_offset_ms"].astype(str),
        alpha=0.05,
    )
    table_data = res.summary().data
    return pd.DataFrame(table_data[1:], columns=table_data[0])


def build_mean_table(df: pd.DataFrame) -> pd.DataFrame:
    summary = (
        df.groupby("candidate_offset_ms")["agency_likert_7"]
        .agg(["count", "mean", "std"])
        .reset_index()
        .sort_values("candidate_offset_ms")
    )
    summary["sem"] = summary["std"] / np.sqrt(summary["count"].clip(lower=1))
    return summary


def save_plot(summary: pd.DataFrame, output_path: Path, task_name: str) -> None:
    plt.figure(figsize=(8, 5))
    plt.errorbar(
        summary["candidate_offset_ms"],
        summary["mean"],
        yerr=summary["sem"],
        fmt="o-",
        capsize=4,
    )
    plt.ylim(1, 7)
    plt.xlabel("Preemptive gain (ms)")
    plt.ylabel("Mean agency score (Likert 1-7)")
    plt.title(f"Agency vs Preemptive gain ({task_name})")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_path, dpi=180)
    plt.close()


def compute_baseline_rt(trial_df: pd.DataFrame, task: str) -> float:
    """ベースラインフェーズ（EMSなし）の平均反応時間を計算"""
    baseline = trial_df[
        (trial_df["phase"] == "Baseline") & 
        (trial_df["task"] == task) &
        (trial_df["is_correct"] == True)
    ]["reaction_time_ms"]
    
    # 外れ値除去（100ms未満、1000ms超）
    baseline = baseline[(baseline >= 100) & (baseline <= 1000)]
    filtered = iqr_filter(baseline)
    
    if filtered.empty:
        return 300.0  # デフォルト値
    return float(filtered.mean())


def compute_ems_latency(trial_df: pd.DataFrame, task: str) -> float:
    """EMSLatencyフェーズの反応時間（EMS発火→ボタン押下の遅延）を計算"""
    ems_trials = trial_df[
        (trial_df["phase"] == "EMSLatency") & 
        (trial_df["task"] == task) &
        (trial_df["is_correct"] == True)
    ]["reaction_time_ms"]
    
    if ems_trials.empty:
        print(f"Warning: No EMSLatency trials found for {task}, using default 50ms")
        return 50.0
    
    # 外れ値除去（生理的に妥当な範囲）
    ems_trials = ems_trials[(ems_trials >= 10) & (ems_trials <= 500)]
    filtered = iqr_filter(ems_trials)
    
    if filtered.empty:
        print(f"Warning: All EMSLatency trials filtered out for {task}, using default 50ms")
        return 50.0
    
    latency = float(filtered.mean())
    print(f"EMSLatency for {task}: {latency:.1f}ms (n={len(filtered)})")
    return latency


# ============================================================
# ロジスティック回帰によるAgency閾値決定（Kasahara et al. CHI'21 準拠）
# ============================================================

def logistic_function(x: np.ndarray, L: float, k: float, x0: float) -> np.ndarray:
    """
    ロジスティック関数
    y = L / (1 + exp(-k * (x - x0)))
    
    L: 最大値（ここでは1.0に固定）
    k: 傾き（負の値で右下がり）
    x0: 中点（Agency=0.5となるx値）
    """
    return L / (1 + np.exp(-k * (x - x0)))


def normalize_agency(agency_scores: np.ndarray) -> np.ndarray:
    """
    Agencyスコアを0-1に正規化
    論文準拠: (score - min) / (max - min)
    7段階リッカートの場合: (score - 1) / 6
    """
    return (agency_scores - 1) / 6


def fit_logistic_regression(
    preemptive_gains: np.ndarray, 
    agency_normalized: np.ndarray
) -> Tuple[Optional[np.ndarray], float, bool]:
    """
    個人のAgency曲線にロジスティック回帰をフィッティング
    
    Returns:
        params: [L, k, x0] のパラメータ（フィット失敗時はNone）
        r_squared: 決定係数
        success: フィッティング成功フラグ
    """
    if len(preemptive_gains) < 5:
        return None, 0.0, False
    
    try:
        # 初期パラメータ推定
        L_init = 1.0  # 最大値は1に固定
        k_init = -0.05  # 負の傾き（Gainが大きいほどAgencyが低い）
        x0_init = np.median(preemptive_gains)  # 中点はデータの中央値
        
        # フィッティング（Lは1.0に固定）
        def logistic_fixed_L(x, k, x0):
            return logistic_function(x, 1.0, k, x0)
        
        popt, pcov = curve_fit(
            logistic_fixed_L,
            preemptive_gains,
            agency_normalized,
            p0=[k_init, x0_init],
            bounds=([-1.0, -500], [0.0, 500]),  # kは負、x0は-500〜500ms
            maxfev=5000
        )
        
        k, x0 = popt
        params = np.array([1.0, k, x0])
        
        # R²計算
        y_pred = logistic_fixed_L(preemptive_gains, k, x0)
        ss_res = np.sum((agency_normalized - y_pred) ** 2)
        ss_tot = np.sum((agency_normalized - np.mean(agency_normalized)) ** 2)
        r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0.0
        
        return params, r_squared, True
        
    except Exception as e:
        print(f"Warning: Logistic fit failed: {e}")
        return None, 0.0, False


def find_agency_threshold_logistic(
    agency_df: pd.DataFrame, 
    task: str,
    baseline_rt: float,
    agency_threshold: float = 0.5
) -> Tuple[float, dict]:
    """
    ロジスティック回帰によりAgency閾値を決定（論文準拠）
    
    Args:
        agency_df: Agency評価データ
        task: タスク種別
        baseline_rt: ベースライン反応時間（Preemptive gain計算用）
        agency_threshold: Agency閾値（正規化後、デフォルト0.5）
    
    Returns:
        offset: Agency閾値でのオフセット（ms）
        fit_info: フィッティング情報
    """
    task_df = agency_df[agency_df["task"] == task].copy()
    if task_df.empty:
        return 0.0, {"success": False, "reason": "No data"}
    
    # オフセットとAgencyスコアを取得
    offsets = task_df["candidate_offset_ms"].values
    agency_scores = task_df["agency_likert_7"].values
    
    # Preemptive gain計算
    # Preemptive gain = BaselineRT - (刺激提示からボタン押下までの時間)
    # オフセット = ボタンフィードバックを速める量
    # ここではoffsetをそのままPreemptive gainとして使用
    preemptive_gains = offsets.astype(float)
    
    # Agencyを0-1に正規化
    agency_normalized = normalize_agency(agency_scores)
    
    # ロジスティック回帰フィッティング
    params, r_squared, success = fit_logistic_regression(preemptive_gains, agency_normalized)
    
    if not success:
        # フォールバック: 単純閾値法
        print(f"Warning: Logistic fit failed for {task}, using fallback method")
        return find_agency_threshold_simple(agency_df, task, threshold=5.0), {
            "success": False,
            "method": "fallback_simple",
            "r_squared": 0.0
        }
    
    L, k, x0 = params
    
    # Agency=0.5となるオフセットを計算
    # logistic(x) = 0.5 のとき、x = x0
    optimal_offset = x0
    
    # 実際のAgency閾値での計算（0.5以外の場合）
    if agency_threshold != 0.5:
        # L / (1 + exp(-k * (x - x0))) = threshold
        # 解くと: x = x0 - ln((L/threshold) - 1) / k
        if agency_threshold > 0 and agency_threshold < L:
            optimal_offset = x0 - np.log((L / agency_threshold) - 1) / k
    
    fit_info = {
        "success": True,
        "method": "logistic_regression",
        "params": {"L": L, "k": k, "x0": x0},
        "r_squared": r_squared,
        "optimal_offset": optimal_offset,
        "agency_threshold": agency_threshold
    }
    
    print(f"{task}: Logistic fit R²={r_squared:.3f}, x0={x0:.1f}ms, optimal_offset={optimal_offset:.1f}ms")
    
    return optimal_offset, fit_info


def find_agency_threshold_simple(agency_df: pd.DataFrame, task: str, threshold: float = 5.0) -> float:
    """主体感が閾値以上を維持する最大オフセットを探索（フォールバック用）"""
    task_df = agency_df[agency_df["task"] == task]
    if task_df.empty:
        return 0.0
    
    summary = build_mean_table(task_df)
    good_offsets = summary[summary["mean"] >= threshold]["candidate_offset_ms"]
    
    if good_offsets.empty:
        return 0.0
    
    return float(good_offsets.max())


def plot_agency_curve_with_logistic(
    agency_df: pd.DataFrame,
    task: str,
    fit_info: dict,
    output_path: Path
) -> None:
    """Agency曲線とロジスティック回帰フィットをプロット"""
    task_df = agency_df[agency_df["task"] == task]
    
    # 各オフセットでの平均Agency
    summary = build_mean_table(task_df)
    offsets = summary["candidate_offset_ms"].values
    mean_agency = summary["mean"].values
    sem_agency = summary["sem"].values
    
    # 正規化
    mean_agency_norm = (mean_agency - 1) / 6
    sem_agency_norm = sem_agency / 6
    
    plt.figure(figsize=(10, 6))
    
    # データポイント
    plt.errorbar(offsets, mean_agency_norm, yerr=sem_agency_norm, 
                 fmt='o', capsize=4, label='Data (mean ± SEM)')
    
    # ロジスティック回帰曲線
    if fit_info.get("success"):
        params = fit_info["params"]
        x_fit = np.linspace(min(offsets), max(offsets), 200)
        y_fit = logistic_function(x_fit, params["L"], params["k"], params["x0"])
        plt.plot(x_fit, y_fit, 'r-', linewidth=2, 
                 label=f'Logistic fit (R²={fit_info["r_squared"]:.3f})')
        
        # 最適オフセットを表示
        optimal = fit_info["optimal_offset"]
        plt.axvline(x=optimal, color='g', linestyle='--', alpha=0.7,
                    label=f'Optimal offset: {optimal:.1f}ms')
    
    # Agency=0.5のライン
    plt.axhline(y=0.5, color='gray', linestyle=':', alpha=0.5, label='Agency = 0.5')
    
    plt.xlabel("Preemptive Gain / Offset (ms)")
    plt.ylabel("Normalized Agency Score (0-1)")
    plt.title(f"Agency vs Preemptive Gain ({task})")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.ylim(-0.05, 1.05)
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=180)
    plt.close()


def find_agency_threshold(agency_df: pd.DataFrame, task: str, threshold: float = 5.0) -> float:
    """後方互換性のためのラッパー（単純閾値法）"""
    return find_agency_threshold_simple(agency_df, task, threshold)


def update_subject_config(subject_dir: Path, calibration_result: dict, fit_results: dict = None) -> None:
    """被験者のconfig.jsonを更新（SubjectDataManager形式）"""
    config_path = subject_dir / "config.json"
    
    if not config_path.exists():
        print(f"Warning: config.json not found at {config_path}")
        return
    
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    
    # キャリブレーション結果を更新
    config["SRT_Offset"] = calibration_result.get("SRT", 0.0)
    config["DRT_Offset"] = calibration_result.get("DRT", 0.0)
    config["CRT_Offset"] = calibration_result.get("CRT", 0.0)
    config["BaselineRT_SRT"] = calibration_result.get("BaselineRT_SRT", 300.0)
    config["BaselineRT_DRT"] = calibration_result.get("BaselineRT_DRT", 300.0)
    config["BaselineRT_CRT"] = calibration_result.get("BaselineRT_CRT", 300.0)
    config["EMSLatency_SRT"] = calibration_result.get("EMSLatency_SRT", 50.0)
    config["EMSLatency_DRT"] = calibration_result.get("EMSLatency_DRT", 50.0)
    config["EMSLatency_CRT"] = calibration_result.get("EMSLatency_CRT", 50.0)
    config["CalibrationCompleted"] = True
    config["LastUpdated"] = datetime.now().isoformat()
    
    # ロジスティック回帰フィット情報を追加
    if fit_results:
        config["LogisticFitResults"] = fit_results
    
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    
    print(f"Updated subject config: {config_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Likert analysis: outlier removal, means, ANOVA, and Tukey post-hoc.")
    parser.add_argument("--agency", required=True, help="Path to agency_log.csv")
    parser.add_argument("--trial", help="Path to trial_log.csv (for baseline RT and EMS latency)")
    parser.add_argument("--outdir", required=True, help="Output directory")
    parser.add_argument("--subject-dir", help="Subject directory for config.json update (optional)")
    parser.add_argument("--task", default="ALL", help="Task filter (SRT/DRT/CRT/ALL)")
    parser.add_argument("--no-outlier-removal", action="store_true", help="Disable IQR outlier removal")
    parser.add_argument("--agency-threshold", type=float, default=0.5, 
                        help="Normalized agency threshold for logistic regression (default: 0.5)")
    parser.add_argument("--use-simple-threshold", action="store_true",
                        help="Use simple threshold method instead of logistic regression")
    parser.add_argument("--simple-threshold", type=float, default=5.0,
                        help="Simple threshold value (Likert scale 1-7, default: 5.0)")
    args = parser.parse_args()

    agency_df = pd.read_csv(args.agency)
    agency_df["agency_likert_7"] = pd.to_numeric(agency_df["agency_likert_7"], errors="coerce")
    agency_df = agency_df.dropna(subset=["candidate_offset_ms", "agency_likert_7"])
    agency_df = agency_df[(agency_df["agency_likert_7"] >= 1) & (agency_df["agency_likert_7"] <= 7)]

    # trial_log.csvが指定されている場合は読み込み
    trial_df = None
    if args.trial:
        trial_df = pd.read_csv(args.trial)

    if args.task != "ALL":
        agency_df = agency_df[agency_df["task"] == args.task]

    if agency_df.empty:
        raise ValueError("No rows available after filtering. Check --task and input file.")

    if not args.no_outlier_removal:
        agency_df = remove_outliers_within_offset(agency_df)

    out_dir = Path(args.outdir)
    out_dir.mkdir(parents=True, exist_ok=True)

    results = {}
    offset_config = {}
    fit_results = {}  # ロジスティック回帰フィット情報
    
    for task, g in agency_df.groupby("task"):
        summary = build_mean_table(g)
        anova = run_oneway_anova(g)

        summary_path = out_dir / f"{task}_likert_summary.csv"
        summary.to_csv(summary_path, index=False, encoding="utf-8")

        task_result = {
            "n_rows": int(len(g)),
            "summary_csv": str(summary_path),
            "anova": anova,
        }

        try:
            tukey_df = run_tukey(g)
            tukey_path = out_dir / f"{task}_tukey.csv"
            tukey_df.to_csv(tukey_path, index=False, encoding="utf-8")
            task_result["tukey_csv"] = str(tukey_path)
        except Exception as exc:
            task_result["tukey_error"] = str(exc)

        # ベースラインRTとEMSレイテンシを計算
        baseline_rt = 300.0
        ems_latency = 50.0
        if trial_df is not None:
            baseline_rt = compute_baseline_rt(trial_df, task)
            ems_latency = compute_ems_latency(trial_df, task)
            task_result["baseline_rt_ms"] = baseline_rt
            task_result["ems_latency_ms"] = ems_latency
            offset_config[f"BaselineRT_{task}"] = baseline_rt
            offset_config[f"EMSLatency_{task}"] = ems_latency

        # 推奨オフセットを計算
        if args.use_simple_threshold:
            # 単純閾値法
            recommended_offset = find_agency_threshold_simple(agency_df, task, args.simple_threshold)
            task_result["threshold_method"] = "simple"
            task_result["recommended_offset_ms"] = recommended_offset
            fit_info = {"method": "simple", "threshold": args.simple_threshold}
        else:
            # ロジスティック回帰法（論文準拠）
            recommended_offset, fit_info = find_agency_threshold_logistic(
                agency_df, task, baseline_rt, args.agency_threshold
            )
            task_result["threshold_method"] = "logistic_regression"
            task_result["recommended_offset_ms"] = recommended_offset
            task_result["logistic_fit"] = fit_info
            
            # ロジスティック曲線をプロット
            logistic_plot_path = out_dir / f"{task}_logistic_fit.png"
            plot_agency_curve_with_logistic(agency_df, task, fit_info, logistic_plot_path)
            task_result["logistic_plot_png"] = str(logistic_plot_path)
        
        # 通常のプロット
        plot_path = out_dir / f"{task}_likert_plot.png"
        save_plot(summary, plot_path, task)
        task_result["plot_png"] = str(plot_path)
        
        offset_config[task] = recommended_offset
        fit_results[task] = fit_info
        results[task] = task_result

    out_json_path = out_dir / "likert_analysis_report.json"
    out_json_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    # agency_offset.json を出力
    if offset_config:
        offset_json_path = out_dir / "agency_offset.json"
        offset_json_path.write_text(json.dumps(offset_config, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Saved agency offset config: {offset_json_path}")
        
        # 被験者ディレクトリが指定されている場合はconfig.jsonを更新
        if args.subject_dir:
            update_subject_config(Path(args.subject_dir), offset_config, fit_results)

    print(f"Saved analysis report: {out_json_path}")
    print("\n=== Summary ===")
    for task, r in results.items():
        method = r.get("threshold_method", "unknown")
        offset = r.get("recommended_offset_ms", 0)
        baseline = r.get("baseline_rt_ms", "N/A")
        if method == "logistic_regression":
            fit = r.get("logistic_fit", {})
            r_sq = fit.get("r_squared", 0)
            print(f"  {task}: Offset={offset:.1f}ms (Logistic R²={r_sq:.3f}), BaselineRT={baseline}ms")
        else:
            print(f"  {task}: Offset={offset:.1f}ms (Simple threshold), BaselineRT={baseline}ms")


if __name__ == "__main__":
    main()
