"""
analyze_agency.py — V3 CRT特化版 Calibration 解析

入力: ExperimentData/<SubjectID>/session_*/trial_log.csv
出力:
  - 被験者別の階段法軌跡プロット（左右別、Yes/No カラー、反転点マーク）
  - 被験者別の psychometric function（左右別、GLM Binomial で Offset vs P(Agency=Yes)）
  - 全被験者集約の psychometric function
  - JSON レポート（反転点 / 収束Offset / GLM パラメータ）

Unity 側 StaircaseCalibrator が既に左右の Agency 閾値を確定しているため、
本スクリプトは後解析・品質チェック用（config.json は更新しない）。
"""
import argparse
import json
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import statsmodels.api as sm

CALIBRATION_PHASE = "Calibration"
TARGET_REVERSALS = 5  # Unity の StaircaseCalibrator.TARGET_REVERSALS と一致


def load_calibration_trials(trial_csv: Path, session_index: int = 0,
                             session_name: str = "") -> pd.DataFrame:
    df = pd.read_csv(trial_csv)
    df = df[df["Phase"] == CALIBRATION_PHASE].copy()
    df["EMSOffset_ms"] = pd.to_numeric(df["EMSOffset_ms"], errors="coerce")
    df["AgencyYes"] = pd.to_numeric(df["AgencyYes"], errors="coerce").fillna(0).astype(int)
    df["IsCorrect"] = pd.to_numeric(df["IsCorrect"], errors="coerce").fillna(0).astype(int)
    df["TrialNumber"] = pd.to_numeric(df["TrialNumber"], errors="coerce")
    # 複数セッション結合後も時系列順に並べ替えられるよう、セッション順と Timestamp を明示列として保持
    df["SessionIndex"] = session_index
    df["SessionName"] = session_name
    df["Timestamp"] = pd.to_datetime(df.get("Timestamp"), errors="coerce", utc=True)
    df = df.dropna(subset=["EMSOffset_ms", "TrialNumber"])
    return df


# セッション跨ぎで時系列順になるソートキー
# SubjectID が列にある場合（pooled 解析）は最優先で被験者ごとにまとめる
_CHRONO_SORT_KEYS = ["SubjectID", "SessionIndex", "Timestamp", "TrialNumber"]


def detect_reversals(agency_yes: np.ndarray, is_correct: np.ndarray,
                     max_reversals: int = TARGET_REVERSALS) -> list:
    """Unity StaircaseLadder.Update と同じロジックで反転点を検出。
    エラー試行 (IsCorrect==0) はスキップ、最大 max_reversals 回で打ち切り。
    返り値は反転が発生した試行のインデックス（side-wise 系列に対する 0-indexed）。"""
    reversals = []
    last_answer = None
    for i in range(len(agency_yes)):
        if is_correct[i] == 0:
            continue
        if last_answer is not None and last_answer != agency_yes[i]:
            reversals.append(i)
            if len(reversals) >= max_reversals:
                break
        last_answer = agency_yes[i]
    return reversals


def summarize_staircase(side_df: pd.DataFrame) -> dict:
    """片側の階段法要約: 反転点・収束Offset（= 反転時 Offset の平均、Unity と同じ式）。"""
    sort_keys = [k for k in _CHRONO_SORT_KEYS if k in side_df.columns]
    side_df = side_df.sort_values(sort_keys).reset_index(drop=True)
    offsets = side_df["EMSOffset_ms"].to_numpy()
    agency = side_df["AgencyYes"].to_numpy().astype(int)
    correct = side_df["IsCorrect"].to_numpy().astype(int)

    reversal_idx = detect_reversals(agency, correct)
    reversal_offsets = [float(offsets[i]) for i in reversal_idx]
    converged = float(np.mean(reversal_offsets)) if reversal_offsets else float(offsets[-1])

    return {
        "n_trials": int(len(side_df)),
        "n_correct": int(correct.sum()),
        "n_errors": int((correct == 0).sum()),
        "n_reversals": len(reversal_offsets),
        "reached_target_reversals": len(reversal_offsets) >= TARGET_REVERSALS,
        "reversal_offsets_ms": reversal_offsets,
        "converged_offset_ms": converged,
        "final_offset_ms": float(offsets[-1]),
        "min_offset_ms": float(offsets.min()),
        "max_offset_ms": float(offsets.max()),
    }


def fit_psychometric(side_df: pd.DataFrame) -> dict:
    """Offset vs P(Agency=Yes) をロジスティック回帰 (GLM Binomial) でフィット。
    エラー試行は階段更新されていないので除外。"""
    df = side_df[side_df["IsCorrect"] == 1].dropna(subset=["EMSOffset_ms", "AgencyYes"])
    if len(df) < 5:
        return {"success": False, "reason": f"n_correct={len(df)} < 5"}
    if df["AgencyYes"].nunique() < 2:
        return {"success": False, "reason": "responses are all identical (no variance)"}

    X = sm.add_constant(df["EMSOffset_ms"].astype(float).values)
    y = df["AgencyYes"].astype(int).values
    try:
        model = sm.GLM(y, X, family=sm.families.Binomial()).fit()
    except Exception as exc:
        return {"success": False, "reason": str(exc)}

    intercept, slope = float(model.params[0]), float(model.params[1])
    threshold = -intercept / slope if slope != 0 else float("nan")
    return {
        "success": True,
        "n": int(len(df)),
        "intercept": intercept,
        "slope": slope,
        "p_intercept": float(model.pvalues[0]),
        "p_slope": float(model.pvalues[1]),
        "threshold_p50_ms": float(threshold),
        "aic": float(model.aic),
    }


def plot_staircase(df: pd.DataFrame, label: str, out_path: Path) -> None:
    """左右の階段法軌跡を 2 パネルでプロット。"""
    fig, axes = plt.subplots(1, 2, figsize=(14, 5), sharey=True)
    for ax, side in zip(axes, ["Left", "Right"]):
        sort_keys = [k for k in _CHRONO_SORT_KEYS if k in df.columns]
        side_df = df[df["TargetSide"] == side].sort_values(sort_keys).reset_index(drop=True)
        if side_df.empty:
            ax.set_title(f"{side} — no data")
            ax.grid(True, alpha=0.3)
            continue
        idx = np.arange(1, len(side_df) + 1)
        offsets = side_df["EMSOffset_ms"].to_numpy()
        yes = side_df["AgencyYes"].to_numpy().astype(int)
        correct = side_df["IsCorrect"].to_numpy().astype(int)

        ax.plot(idx, offsets, color="gray", alpha=0.6, zorder=1)
        mask_yes = (yes == 1) & (correct == 1)
        mask_no = (yes == 0) & (correct == 1)
        mask_err = correct == 0
        ax.scatter(idx[mask_yes], offsets[mask_yes], c="tab:blue", s=40,
                   label="Agency Yes", zorder=2)
        ax.scatter(idx[mask_no], offsets[mask_no], c="tab:red", s=40,
                   label="Agency No", zorder=2)
        if mask_err.any():
            ax.scatter(idx[mask_err], offsets[mask_err], marker="x", c="black", s=40,
                       label="Error (skipped)", zorder=2)

        rev_idx = detect_reversals(yes, correct)
        if rev_idx:
            ax.scatter(idx[rev_idx], offsets[rev_idx], facecolors="none",
                       edgecolors="black", s=130, linewidths=1.5,
                       label=f"Reversal (n={len(rev_idx)})", zorder=3)

        ax.set_xlabel("Calibration trial (side-wise)")
        ax.set_ylabel("EMSOffset (ms)")
        ax.set_title(f"{side} — {len(side_df)} trials")
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=8, loc="best")
    fig.suptitle(f"Staircase trajectory — {label}")
    plt.tight_layout()
    plt.savefig(out_path, dpi=180)
    plt.close()


def plot_psychometric(side_df: pd.DataFrame, fit: Optional[dict],
                      label: str, out_path: Path) -> None:
    df = side_df[side_df["IsCorrect"] == 1].copy()
    if df.empty:
        return

    lo = float(df["EMSOffset_ms"].min())
    hi = float(df["EMSOffset_ms"].max())
    bin_edges = np.arange(np.floor(lo / 5) * 5 - 2.5, np.ceil(hi / 5) * 5 + 5, 5)
    df["_bin"] = pd.cut(df["EMSOffset_ms"], bin_edges)
    agg = (df.groupby("_bin", observed=True)
             .agg(n=("AgencyYes", "size"),
                  p_yes=("AgencyYes", "mean"),
                  offset_mid=("EMSOffset_ms", "mean"))
             .dropna())

    plt.figure(figsize=(9, 5.5))
    if not agg.empty:
        plt.scatter(agg["offset_mid"], agg["p_yes"],
                    s=agg["n"].clip(upper=40) * 8 + 20,
                    alpha=0.55, label="Binned proportions (size ∝ n)")

    if fit and fit.get("success"):
        x_range = np.linspace(lo, hi, 200)
        logits = fit["intercept"] + fit["slope"] * x_range
        p = 1.0 / (1.0 + np.exp(-logits))
        plt.plot(x_range, p, "r-", linewidth=2,
                 label=f"Logistic GLM (slope={fit['slope']:.3f})")
        th = fit.get("threshold_p50_ms")
        if th is not None and np.isfinite(th) and (lo - 20) <= th <= (hi + 20):
            plt.axvline(th, color="g", linestyle="--", alpha=0.7,
                        label=f"P=0.5 threshold: {th:.1f} ms")

    plt.axhline(0.5, color="gray", linestyle=":", alpha=0.5)
    plt.xlabel("EMSOffset (ms)")
    plt.ylabel("P(Agency = Yes)")
    plt.title(f"Psychometric function — {label}")
    plt.ylim(-0.05, 1.05)
    plt.grid(True, alpha=0.3)
    plt.legend(fontsize=9, loc="best")
    plt.tight_layout()
    plt.savefig(out_path, dpi=180)
    plt.close()


def analyze_subject(subject_dir: Path, out_dir: Path) -> tuple:
    """1 被験者の全セッション横断 Calibration 解析。"""
    subject_id = subject_dir.name
    dfs = []
    for idx, session_dir in enumerate(sorted(subject_dir.glob("session_*"))):
        csv_path = session_dir / "trial_log.csv"
        if csv_path.exists():
            dfs.append(load_calibration_trials(csv_path, session_index=idx,
                                               session_name=session_dir.name))

    if not dfs:
        return {"subject_id": subject_id, "error": "no trial_log.csv found"}, None

    df = pd.concat(dfs, ignore_index=True)
    if df.empty:
        return {"subject_id": subject_id, "error": "no Calibration trials"}, None

    subj_out = out_dir / subject_id
    subj_out.mkdir(exist_ok=True)
    plot_staircase(df, subject_id, subj_out / "staircase.png")

    result = {"subject_id": subject_id}
    for side in ("Left", "Right"):
        side_df = df[df["TargetSide"] == side].reset_index(drop=True)
        if side_df.empty:
            result[side] = {"error": "no data"}
            continue
        summary = summarize_staircase(side_df)
        summary["psychometric"] = fit_psychometric(side_df)
        result[side] = summary
        plot_psychometric(side_df, summary["psychometric"],
                          f"{subject_id} — {side}",
                          subj_out / f"psychometric_{side}.png")
    return result, df


def main() -> None:
    parser = argparse.ArgumentParser(
        description="V3 Calibration 解析: 階段法軌跡 + Offset vs P(Agency=Yes) ロジスティック回帰")
    parser.add_argument("--data-dir", required=True,
                        help="ExperimentData ルート（P001/, P002/ ... を含む）")
    parser.add_argument("--outdir", required=True, help="出力ディレクトリ")
    parser.add_argument("--subject", default=None,
                        help="単一被験者 ID（省略時は全被験者）")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    out_dir = Path(args.outdir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.subject:
        subject_dirs = [data_dir / args.subject]
    else:
        subject_dirs = sorted(d for d in data_dir.iterdir()
                              if d.is_dir() and any(d.glob("session_*")))

    all_results = {}
    pooled = []
    for sdir in subject_dirs:
        if not sdir.exists():
            print(f"[WARN] {sdir} does not exist, skipping")
            continue
        print(f"=== {sdir.name} ===")
        result, df = analyze_subject(sdir, out_dir)
        all_results[sdir.name] = result
        if df is not None:
            pooled.append(df.assign(SubjectID=sdir.name))

    if pooled:
        pooled_df = pd.concat(pooled, ignore_index=True)
        pooled_out = out_dir / "_pooled"
        pooled_out.mkdir(exist_ok=True)
        plot_staircase(pooled_df, "All subjects (stacked)", pooled_out / "staircase.png")
        pooled_result = {}
        for side in ("Left", "Right"):
            side_df = pooled_df[pooled_df["TargetSide"] == side]
            fit = fit_psychometric(side_df)
            pooled_result[side] = {"n_trials": int(len(side_df)), "psychometric": fit}
            plot_psychometric(side_df, fit, f"All subjects — {side}",
                              pooled_out / f"psychometric_{side}.png")
        all_results["_pooled"] = pooled_result

    report_path = out_dir / "agency_analysis_report.json"
    report_path.write_text(
        json.dumps(all_results, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8")
    print(f"\nSaved report: {report_path}")

    print("\n=== Summary ===")
    for sid, r in all_results.items():
        if sid == "_pooled" or not isinstance(r, dict):
            continue
        for side in ("Left", "Right"):
            s = r.get(side, {})
            if "converged_offset_ms" not in s:
                continue
            psy = s.get("psychometric", {}) or {}
            th = psy.get("threshold_p50_ms") if psy.get("success") else None
            th_str = f"{th:6.1f}ms" if th is not None and np.isfinite(th) else "   n/a"
            ok = "✓" if s.get("reached_target_reversals") else "!"
            print(f"  {sid} {side:5s}: converged={s['converged_offset_ms']:6.1f}ms  "
                  f"GLM_P50={th_str}  reversals={s['n_reversals']}{ok}  n={s['n_trials']}")


if __name__ == "__main__":
    main()
