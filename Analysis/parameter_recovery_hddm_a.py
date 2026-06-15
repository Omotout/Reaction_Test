"""
Parameter recovery check for HDDM boundary separation (a).

This mirrors the recovery-study idea in Wiecki, Sofer, & Frank (2013): generate
synthetic two-choice RT data with known DDM parameters, fit HDDM, then compare
recovered posterior means with the known generating values.

The default design is matched to the current TestData task: 10 subjects and
80 trials per subject. Run inside the HDDM Docker image.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import warnings
from datetime import datetime, timezone
from pathlib import Path

import hddm
import numpy as np
import pandas as pd


SUBJ_NODE_RE = re.compile(r"^([vat])_subj\.(\d+)$")


def simulate_subject(
    subject_id: str,
    subj_idx: int,
    true_v: float,
    true_a: float,
    true_t: float,
    n_trials: int,
    rng: np.random.Generator,
    dt: float = 0.001,
    max_time: float = 3.0,
) -> tuple[pd.DataFrame, dict]:
    n_steps = int(max_time / dt)
    sqrt_dt = np.sqrt(dt)

    x = np.full(n_trials, 0.5 * true_a)
    finished = np.zeros(n_trials, dtype=bool)
    rts_s = np.full(n_trials, max_time)
    correct = np.full(n_trials, -1, dtype=int)

    for step in range(n_steps):
        active = ~finished
        if not active.any():
            break
        x[active] += true_v * dt + sqrt_dt * rng.standard_normal(int(active.sum()))

        hit_upper = active & (x >= true_a)
        rts_s[hit_upper] = step * dt + true_t
        correct[hit_upper] = 1
        finished |= hit_upper

        hit_lower = active & (x <= 0.0)
        rts_s[hit_lower] = step * dt + true_t
        correct[hit_lower] = 0
        finished |= hit_lower

    target_sides = np.array(["Left"] * (n_trials // 2) + ["Right"] * (n_trials - n_trials // 2))
    rng.shuffle(target_sides)
    rows = []
    timestamp = datetime.now(timezone.utc).isoformat()
    for i in range(n_trials):
        if correct[i] == -1:
            rt_ms = -1.0
            response_side = "None"
            is_correct = 0
        else:
            rt_ms = rts_s[i] * 1000.0
            response_side = (
                target_sides[i]
                if correct[i] == 1
                else ("Right" if target_sides[i] == "Left" else "Left")
            )
            is_correct = int(correct[i] == 1)

        rows.append({
            "SubjectID": subject_id,
            "subj_idx": subj_idx,
            "TargetSide": target_sides[i],
            "ResponseSide": response_side,
            "IsCorrect": is_correct,
            "ReactionTime_ms": round(rt_ms, 3),
            "Timestamp": timestamp,
        })

    truth = {
        "SubjectID": subject_id,
        "subj_idx": subj_idx,
        "true_v": true_v,
        "true_a": true_a,
        "true_t": true_t,
    }
    return pd.DataFrame(rows), truth


def simulate_dataset(args: argparse.Namespace, rep: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(args.seed + rep)
    frames = []
    truth_rows = []
    for subj_idx in range(args.n_subjects):
        subject_id = f"{subj_idx + 1:03d}"
        true_v = max(0.05, rng.normal(args.v_mean, args.v_sd))
        true_a = max(0.2, rng.normal(args.a_mean, args.a_sd))
        true_t = max(0.05, rng.normal(args.t_mean, args.t_sd))
        df, truth = simulate_subject(
            subject_id,
            subj_idx,
            true_v,
            true_a,
            true_t,
            args.n_trials,
            rng,
        )
        frames.append(df)
        truth_rows.append(truth)
    return pd.concat(frames, ignore_index=True), pd.DataFrame(truth_rows)


def preprocess_for_hddm(df: pd.DataFrame, min_rt: float, max_rt: float) -> pd.DataFrame:
    work = df.copy()
    work["ReactionTime_ms"] = pd.to_numeric(work["ReactionTime_ms"], errors="coerce")
    work["IsCorrect"] = pd.to_numeric(work["IsCorrect"], errors="coerce").fillna(0).astype(int)
    work = work.dropna(subset=["ReactionTime_ms"])
    work = work[work["ReactionTime_ms"] > 0]
    work = work[(work["ReactionTime_ms"] >= min_rt) & (work["ReactionTime_ms"] <= max_rt)].copy()
    work = work[work["ResponseSide"].isin(["Left", "Right"])].copy()
    return pd.DataFrame({
        "subj_idx": work["subj_idx"].astype(int),
        "stim": work["TargetSide"].astype(str),
        "response": work["IsCorrect"].astype(int),
        "rt": work["ReactionTime_ms"].astype(float) / 1000.0,
    })


def fit_hddm(hddm_df: pd.DataFrame, out_dir: Path, rep: int, args: argparse.Namespace):
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
        dbname=str(out_dir / f"traces_rep_{rep:03d}.db"),
        db="pickle",
    )
    model.gen_stats().to_csv(out_dir / f"hddm_stats_rep_{rep:03d}.csv")
    return model


def extract_subject_estimates(model, truth_df: pd.DataFrame, rep: int) -> pd.DataFrame:
    stats = model.gen_stats()
    estimates: dict[tuple[int, str], dict] = {}
    for node_name in stats.index:
        match = SUBJ_NODE_RE.match(str(node_name))
        if not match:
            continue
        param, subj_idx_str = match.groups()
        subj_idx = int(subj_idx_str)
        row = stats.loc[node_name]
        estimates[(subj_idx, param)] = {
            f"est_{param}": float(row["mean"]),
            f"{param}_hdi_low": float(row["2.5q"]),
            f"{param}_hdi_high": float(row["97.5q"]),
            f"{param}_mc_err": float(row["mc err"]),
        }

    rows = []
    for truth in truth_df.itertuples(index=False):
        row = {
            "rep": rep,
            "SubjectID": truth.SubjectID,
            "subj_idx": int(truth.subj_idx),
            "true_v": float(truth.true_v),
            "true_a": float(truth.true_a),
            "true_t": float(truth.true_t),
        }
        for param in ["v", "a", "t"]:
            row.update(estimates.get((int(truth.subj_idx), param), {}))
        if "est_a" in row:
            row["a_error"] = row["est_a"] - row["true_a"]
            row["a_abs_error"] = abs(row["a_error"])
            row["a_covered_by_95hdi"] = (
                row["a_hdi_low"] <= row["true_a"] <= row["a_hdi_high"]
            )
        rows.append(row)
    return pd.DataFrame(rows)


def trimmed_mean(values: pd.Series, trim_fraction: float) -> float:
    x = pd.to_numeric(values, errors="coerce").dropna().sort_values().to_numpy()
    if len(x) == 0:
        return float("nan")
    if trim_fraction <= 0:
        return float(np.mean(x))
    keep = int(np.floor(len(x) * (1.0 - trim_fraction)))
    keep = max(1, keep)
    return float(np.mean(x[:keep]))


def summarize_recovery(subject_recovery: pd.DataFrame, args: argparse.Namespace) -> dict:
    abs_errors = subject_recovery["a_abs_error"]
    return {
        "hddm_version": hddm.__version__,
        "n_reps": int(args.reps),
        "n_subjects": int(args.n_subjects),
        "n_trials_per_subject": int(args.n_trials),
        "mcmc": {"samples": args.samples, "burn": args.burn, "thin": args.thin},
        "generating_params": {
            "v_mean": args.v_mean,
            "v_sd": args.v_sd,
            "a_mean": args.a_mean,
            "a_sd": args.a_sd,
            "t_mean": args.t_mean,
            "t_sd": args.t_sd,
        },
        "a_signed_error_mean": float(subject_recovery["a_error"].mean()),
        "a_abs_error_mean": float(abs_errors.mean()),
        "a_abs_error_median": float(abs_errors.median()),
        "a_abs_error_trimmed_5pct_largest": trimmed_mean(abs_errors, 0.05),
        "a_rmse": float(np.sqrt(np.mean(np.square(subject_recovery["a_error"])))),
        "a_95hdi_coverage": float(subject_recovery["a_covered_by_95hdi"].mean()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="HDDM parameter recovery for boundary a.")
    parser.add_argument("--outdir", type=Path, default=Path("./results_hddm_a_recovery"))
    parser.add_argument("--reps", type=int, default=3)
    parser.add_argument("--n-subjects", type=int, default=10)
    parser.add_argument("--n-trials", type=int, default=80)
    parser.add_argument("--seed", type=int, default=20260501)
    parser.add_argument("--v-mean", type=float, default=3.1)
    parser.add_argument("--v-sd", type=float, default=0.25)
    parser.add_argument("--a-mean", type=float, default=0.55)
    parser.add_argument("--a-sd", type=float, default=0.08)
    parser.add_argument("--t-mean", type=float, default=0.18)
    parser.add_argument("--t-sd", type=float, default=0.03)
    parser.add_argument("--min-rt", type=float, default=100.0)
    parser.add_argument("--max-rt", type=float, default=1000.0)
    parser.add_argument("--samples", type=int, default=1500)
    parser.add_argument("--burn", type=int, default=300)
    parser.add_argument("--thin", type=int, default=1)
    args = parser.parse_args()

    args.outdir.mkdir(parents=True, exist_ok=True)
    all_recovery = []

    for rep in range(args.reps):
        rep_dir = args.outdir / f"rep_{rep:03d}"
        rep_dir.mkdir(parents=True, exist_ok=True)
        print(f"\n=== Recovery replicate {rep + 1}/{args.reps} ===")
        raw_df, truth_df = simulate_dataset(args, rep)
        truth_df.to_csv(rep_dir / "true_params.csv", index=False, encoding="utf-8-sig")
        raw_df.to_csv(rep_dir / "simulated_trial_log.csv", index=False, encoding="utf-8-sig")

        hddm_df = preprocess_for_hddm(raw_df, args.min_rt, args.max_rt)
        hddm_df.to_csv(rep_dir / "hddm_input.csv", index=False)
        print(f"Fitting {hddm_df['subj_idx'].nunique()} subjects, {len(hddm_df)} trials")

        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=RuntimeWarning)
            model = fit_hddm(hddm_df, rep_dir, rep, args)

        recovery_df = extract_subject_estimates(model, truth_df, rep)
        recovery_df.to_csv(rep_dir / "subject_recovery.csv", index=False, encoding="utf-8-sig")
        all_recovery.append(recovery_df)

    subject_recovery = pd.concat(all_recovery, ignore_index=True)
    subject_recovery.to_csv(args.outdir / "subject_recovery_all.csv", index=False, encoding="utf-8-sig")
    summary = summarize_recovery(subject_recovery, args)
    (args.outdir / "recovery_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with (args.outdir / "recovery_summary.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(summary.keys()))
        writer.writeheader()
        writer.writerow(summary)

    print("\n=== a recovery summary ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Done. Results: {args.outdir}")


if __name__ == "__main__":
    main()
