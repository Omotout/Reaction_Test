"""
Estimate DDM boundary separation (a) for latest TestData sessions with HDDM.

This script is intended to run inside the hcp4715/hddm Docker image.
It reads TestData/<numeric subject>/test_*/trial_log.csv, keeps only the
latest test session per subject by default, fits a hierarchical single-phase
HDDMStimCoding model, and writes summaries for group-level and subject-level a.

If --true-a is supplied, it also reports mean absolute error (MAE) against that
reference value. Without a true/reference a, MAE is not statistically defined.
"""

from __future__ import annotations

import argparse
import json
import re
import warnings
from pathlib import Path

import hddm
import numpy as np
import pandas as pd


SUBJ_A_RE = re.compile(r"^a_subj\.(\d+)$")


def find_latest_logs(data_dir: Path, subject_start: int, subject_end: int) -> list[Path]:
    logs: list[Path] = []
    for sid in range(subject_start, subject_end + 1):
        subject_dir = data_dir / f"{sid:03d}"
        subject_logs = sorted(subject_dir.glob("test_*/trial_log.csv"))
        if not subject_logs:
            print(f"[WARN] No trial_log.csv for subject {sid:03d}")
            continue
        logs.append(subject_logs[-1])
    return logs


def load_logs(paths: list[Path]) -> tuple[pd.DataFrame, pd.DataFrame]:
    frames: list[pd.DataFrame] = []
    loaded_rows: list[dict] = []
    for path in paths:
        df = pd.read_csv(path, encoding="utf-8-sig")
        subject_id = str(df["SubjectID"].iloc[0]).zfill(3)
        df = df.copy()
        df["SubjectID"] = subject_id
        df["Session"] = path.parent.name
        df["SourceFile"] = str(path)
        frames.append(df)
        loaded_rows.append({
            "SubjectID": subject_id,
            "Session": path.parent.name,
            "Path": str(path),
            "n_rows": int(len(df)),
        })
    if not frames:
        raise ValueError(f"No trial_log.csv files found in {paths}")
    return pd.concat(frames, ignore_index=True), pd.DataFrame(loaded_rows)


def preprocess_for_hddm(df: pd.DataFrame, min_rt: float, max_rt: float) -> pd.DataFrame:
    work = df.copy()
    work["ReactionTime_ms"] = pd.to_numeric(work["ReactionTime_ms"], errors="coerce")
    work["IsCorrect"] = pd.to_numeric(work["IsCorrect"], errors="coerce").fillna(0).astype(int)
    work = work.dropna(subset=["ReactionTime_ms"])
    work = work[work["ReactionTime_ms"] > 0]
    before_rt = len(work)
    work = work[(work["ReactionTime_ms"] >= min_rt) & (work["ReactionTime_ms"] <= max_rt)].copy()
    print(f"Preprocess: removed {before_rt - len(work)}/{before_rt} rows outside [{min_rt}, {max_rt}] ms")
    work = work[work["ResponseSide"].isin(["Left", "Right"])].copy()

    subj_ids = sorted(work["SubjectID"].astype(str).unique())
    subj_map = {sid: i for i, sid in enumerate(subj_ids)}
    idx_to_subject = {i: sid for sid, i in subj_map.items()}

    hddm_df = pd.DataFrame({
        "subj_idx": work["SubjectID"].astype(str).map(subj_map).astype(int),
        "stim": work["TargetSide"].astype(str),
        "response": work["IsCorrect"].astype(int),
        "rt": work["ReactionTime_ms"].astype(float) / 1000.0,
    })
    return hddm_df.reset_index(drop=True), idx_to_subject


def extract_a_summary(model, idx_to_subject: dict[int, str], true_a: float | None) -> tuple[pd.DataFrame, dict]:
    stats = model.gen_stats()
    rows: list[dict] = []

    if "a" in stats.index:
        r = stats.loc["a"]
        rows.append({
            "level": "group",
            "SubjectID": "group",
            "node": "a",
            "mean": float(r["mean"]),
            "std": float(r["std"]),
            "hdi_low": float(r["2.5q"]),
            "hdi_high": float(r["97.5q"]),
            "mc_err": float(r["mc err"]),
            "abs_error": abs(float(r["mean"]) - true_a) if true_a is not None else np.nan,
        })

    for node_name in stats.index:
        match = SUBJ_A_RE.match(str(node_name))
        if not match:
            continue
        subj_idx = int(match.group(1))
        r = stats.loc[node_name]
        mean = float(r["mean"])
        rows.append({
            "level": "subject",
            "SubjectID": idx_to_subject.get(subj_idx, str(subj_idx)),
            "node": node_name,
            "mean": mean,
            "std": float(r["std"]),
            "hdi_low": float(r["2.5q"]),
            "hdi_high": float(r["97.5q"]),
            "mc_err": float(r["mc err"]),
            "abs_error": abs(mean - true_a) if true_a is not None else np.nan,
        })

    summary_df = pd.DataFrame(rows)
    subject_rows = summary_df[summary_df["level"] == "subject"].copy()

    report = {
        "hddm_version": hddm.__version__,
        "true_a": true_a,
        "n_subject_a_estimates": int(len(subject_rows)),
        "group_a_mean": float(summary_df.loc[summary_df["level"].eq("group"), "mean"].iloc[0])
        if (summary_df["level"].eq("group")).any() else None,
        "subject_a_mean": float(subject_rows["mean"].mean()) if len(subject_rows) else None,
        "subject_a_sd": float(subject_rows["mean"].std(ddof=1)) if len(subject_rows) > 1 else None,
        "subject_a_mc_err_mean": float(subject_rows["mc_err"].mean()) if len(subject_rows) else None,
        "subject_a_mae": float(subject_rows["abs_error"].mean()) if true_a is not None and len(subject_rows) else None,
        "mae_note": "MAE is computed only when --true-a is supplied.",
    }
    return summary_df, report


def main() -> None:
    parser = argparse.ArgumentParser(description="HDDM estimate of a for latest TestData sessions.")
    parser.add_argument("--data-dir", type=Path, default=Path("../TestData"))
    parser.add_argument("--outdir", type=Path, default=Path("./results_hddm_testdata_a"))
    parser.add_argument("--subject-start", type=int, default=1)
    parser.add_argument("--subject-end", type=int, default=10)
    parser.add_argument("--min-rt", type=float, default=100.0)
    parser.add_argument("--max-rt", type=float, default=1000.0)
    parser.add_argument("--samples", type=int, default=3000)
    parser.add_argument("--burn", type=int, default=500)
    parser.add_argument("--thin", type=int, default=1)
    parser.add_argument("--true-a", type=float, default=None)
    args = parser.parse_args()

    args.outdir.mkdir(parents=True, exist_ok=True)

    paths = find_latest_logs(args.data_dir, args.subject_start, args.subject_end)
    raw, loaded = load_logs(paths)
    loaded.to_csv(args.outdir / "included_files.csv", index=False, encoding="utf-8-sig")
    hddm_df, idx_to_subject = preprocess_for_hddm(raw, args.min_rt, args.max_rt)
    hddm_df.to_csv(args.outdir / "hddm_input.csv", index=False)

    print(f"Loaded {len(loaded)} subjects, {len(hddm_df)} usable trials")
    print(f"Subjects: {', '.join(loaded['SubjectID'].tolist())}")
    print(f"Sampling HDDM: samples={args.samples}, burn={args.burn}, thin={args.thin}")

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=RuntimeWarning)
        model = hddm.HDDMStimCoding(
            hddm_df,
            stim_col="stim",
            split_param="v",
            drift_criterion=False,
            include=["v", "a", "t"],
            p_outlier=0.05,
        )
        model.find_starting_values()
        model.sample(
            args.samples,
            burn=args.burn,
            thin=args.thin,
            dbname=str(args.outdir / "traces_testdata_a.db"),
            db="pickle",
        )

    stats = model.gen_stats()
    stats.to_csv(args.outdir / "hddm_stats.csv")
    model.save(str(args.outdir / "hddm_model"))

    a_summary, report = extract_a_summary(model, idx_to_subject, args.true_a)
    report.update({
        "mcmc": {"samples": args.samples, "burn": args.burn, "thin": args.thin},
        "n_subjects": int(len(loaded)),
        "n_trials": int(len(hddm_df)),
    })
    a_summary.to_csv(args.outdir / "a_summary.csv", index=False, encoding="utf-8-sig")
    (args.outdir / "a_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"Done. Results: {args.outdir}")


if __name__ == "__main__":
    main()
