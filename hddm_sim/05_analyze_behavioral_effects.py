"""
Behavioral analysis for the main EMS effect.

This script analyzes raw trial-level data and reports:
- RT shortening: EMS mean RT - Control mean RT, with a one-sided Welch/paired t-test.
- Accuracy non-inferiority: EMS accuracy - Control accuracy, tested against a margin.

The primary unit of inference is subject-level summary data, not raw trials.
For stim-coded data, accuracy is computed as response == stim.
For correctness-coded data without a stim column, response is treated as correctness.
"""

import argparse
import importlib.util
import json
import os
import sys

import numpy as np
import pandas as pd
from scipy import stats


def load_simulated_data(n_subj, n_trials, rep_id):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    spec = importlib.util.spec_from_file_location(
        "sim_data",
        os.path.join(script_dir, "01_simulate_data.py"),
    )
    sim_data = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sim_data)
    return sim_data.simulate_two_groups(
        n_subj_per_group=n_subj,
        n_trials=n_trials,
        seed=rep_id,
    )


def infer_rt_ms(rt, unit):
    rt = pd.to_numeric(rt, errors="coerce")
    if unit == "ms":
        return rt
    if unit == "s":
        return rt * 1000.0
    median_rt = rt.median()
    if median_rt > 10:
        return rt
    return rt * 1000.0


def add_correct_column(df, response_col, stim_col, correct_col):
    df = df.copy()
    if correct_col and correct_col in df.columns:
        df["correct"] = pd.to_numeric(df[correct_col], errors="coerce")
        return df

    if stim_col and stim_col in df.columns:
        df["correct"] = (df[response_col].astype(int) == df[stim_col].astype(int)).astype(int)
        return df

    values = set(pd.Series(df[response_col]).dropna().astype(float).unique())
    if values.issubset({0.0, 1.0}):
        df["correct"] = pd.to_numeric(df[response_col], errors="coerce")
        return df

    raise ValueError(
        "Cannot compute accuracy. Provide --stim-col for stim-coded data, "
        "or --correct-col for an explicit correctness column."
    )


def prepare_trial_data(args):
    if args.simulate:
        df = load_simulated_data(args.n_subj, args.n_trials, args.rep_id)
    else:
        if args.data is None:
            raise ValueError("Specify --data or use --simulate.")
        df = pd.read_csv(args.data)

    required = [args.condition_col, args.subject_col, args.rt_col, args.response_col]
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    df = df.copy()
    df = df[df[args.condition_col].isin([args.control_label, args.ems_label])].copy()
    df["condition"] = df[args.condition_col].astype(str)
    df["subj_idx"] = df[args.subject_col]
    df["rt_ms"] = infer_rt_ms(df[args.rt_col], args.rt_unit)
    df = add_correct_column(df, args.response_col, args.stim_col, args.correct_col)

    df = df.dropna(subset=["condition", "subj_idx", "rt_ms", "correct"])
    return df


def subject_summary(df):
    return (
        df.groupby(["condition", "subj_idx"], as_index=False)
        .agg(
            mean_rt_ms=("rt_ms", "mean"),
            median_rt_ms=("rt_ms", "median"),
            accuracy=("correct", "mean"),
            n_trials=("rt_ms", "count"),
        )
        .sort_values(["condition", "subj_idx"])
    )


def trial_summary(df):
    return (
        df.groupby("condition", as_index=False)
        .agg(
            mean_rt_ms=("rt_ms", "mean"),
            median_rt_ms=("rt_ms", "median"),
            sd_rt_ms=("rt_ms", "std"),
            accuracy=("correct", "mean"),
            n_trials=("rt_ms", "count"),
            n_subj=("subj_idx", "nunique"),
        )
        .sort_values("condition")
    )


def welch_df(x, y):
    nx = len(x)
    ny = len(y)
    vx = np.var(x, ddof=1)
    vy = np.var(y, ddof=1)
    se2 = vx / nx + vy / ny
    if se2 <= 0:
        return np.nan
    num = se2 ** 2
    den = (vx / nx) ** 2 / (nx - 1) + (vy / ny) ** 2 / (ny - 1)
    return num / den


def independent_test(ems, ctrl, null=0.0, alternative="less", ci_level=0.95):
    ems = np.asarray(ems, dtype=float)
    ctrl = np.asarray(ctrl, dtype=float)
    diff = ems.mean() - ctrl.mean()
    se = np.sqrt(np.var(ems, ddof=1) / len(ems) + np.var(ctrl, ddof=1) / len(ctrl))
    df = welch_df(ems, ctrl)
    t_value = (diff - null) / se

    if alternative == "less":
        p_value = stats.t.cdf(t_value, df)
    elif alternative == "greater":
        p_value = 1.0 - stats.t.cdf(t_value, df)
    else:
        p_value = 2.0 * min(stats.t.cdf(t_value, df), 1.0 - stats.t.cdf(t_value, df))

    alpha = 1.0 - ci_level
    tcrit = stats.t.ppf(1.0 - alpha / 2.0, df)
    ci_low = diff - tcrit * se
    ci_high = diff + tcrit * se
    return diff, se, df, t_value, p_value, ci_low, ci_high


def paired_test(ems, ctrl, null=0.0, alternative="less", ci_level=0.95):
    diff_samples = np.asarray(ems, dtype=float) - np.asarray(ctrl, dtype=float)
    diff = diff_samples.mean()
    n = len(diff_samples)
    sd = diff_samples.std(ddof=1)
    se = sd / np.sqrt(n)
    df = n - 1
    t_value = (diff - null) / se

    if alternative == "less":
        p_value = stats.t.cdf(t_value, df)
    elif alternative == "greater":
        p_value = 1.0 - stats.t.cdf(t_value, df)
    else:
        p_value = 2.0 * min(stats.t.cdf(t_value, df), 1.0 - stats.t.cdf(t_value, df))

    alpha = 1.0 - ci_level
    tcrit = stats.t.ppf(1.0 - alpha / 2.0, df)
    ci_low = diff - tcrit * se
    ci_high = diff + tcrit * se
    return diff, se, df, t_value, p_value, ci_low, ci_high


def hedges_g(ems, ctrl):
    ems = np.asarray(ems, dtype=float)
    ctrl = np.asarray(ctrl, dtype=float)
    n1 = len(ems)
    n0 = len(ctrl)
    pooled_var = ((n1 - 1) * ems.var(ddof=1) + (n0 - 1) * ctrl.var(ddof=1)) / (n1 + n0 - 2)
    if pooled_var <= 0:
        return np.nan
    d = (ems.mean() - ctrl.mean()) / np.sqrt(pooled_var)
    correction = 1.0 - 3.0 / (4.0 * (n1 + n0) - 9.0)
    return d * correction


def analyze_subject_level(subj, control_label, ems_label, acc_margin, alpha_rt, alpha_noninf):
    ctrl = subj[subj["condition"] == control_label]
    ems = subj[subj["condition"] == ems_label]
    common_subjects = sorted(set(ctrl["subj_idx"]) & set(ems["subj_idx"]))
    paired = len(common_subjects) >= 2

    rows = []
    if paired:
        ctrl_rt = ctrl.set_index("subj_idx").loc[common_subjects, "mean_rt_ms"].to_numpy()
        ems_rt = ems.set_index("subj_idx").loc[common_subjects, "mean_rt_ms"].to_numpy()
        ctrl_acc = ctrl.set_index("subj_idx").loc[common_subjects, "accuracy"].to_numpy()
        ems_acc = ems.set_index("subj_idx").loc[common_subjects, "accuracy"].to_numpy()
        test_name = "paired t-test"
    else:
        ctrl_rt = ctrl["mean_rt_ms"].to_numpy()
        ems_rt = ems["mean_rt_ms"].to_numpy()
        ctrl_acc = ctrl["accuracy"].to_numpy()
        ems_acc = ems["accuracy"].to_numpy()
        test_name = "Welch t-test"

    if paired:
        rt = paired_test(ems_rt, ctrl_rt, null=0.0, alternative="less")
    else:
        rt = independent_test(ems_rt, ctrl_rt, null=0.0, alternative="less")
    rt_diff, rt_se, rt_df, rt_t, rt_p, rt_ci_low, rt_ci_high = rt
    rows.append(
        {
            "outcome": "mean_rt_ms",
            "test": test_name,
            "hypothesis": "EMS < Control",
            "control_mean": float(ctrl_rt.mean()),
            "ems_mean": float(ems_rt.mean()),
            "diff_ems_minus_control": float(rt_diff),
            "se": float(rt_se),
            "df": float(rt_df),
            "t": float(rt_t),
            "p_value_one_sided": float(rt_p),
            "ci_95_low": float(rt_ci_low),
            "ci_95_high": float(rt_ci_high),
            "margin": 0.0,
            "significant": bool(rt_p < alpha_rt),
            "effect_hedges_g": float(hedges_g(ems_rt, ctrl_rt)) if not paired else np.nan,
        }
    )

    # Non-inferiority: H0 diff <= -margin, H1 diff > -margin.
    null = -acc_margin
    if paired:
        acc = paired_test(ems_acc, ctrl_acc, null=null, alternative="greater")
    else:
        acc = independent_test(ems_acc, ctrl_acc, null=null, alternative="greater")
    acc_diff, acc_se, acc_df, acc_t, acc_p, acc_ci_low, acc_ci_high = acc
    lower_bound = acc_diff - stats.t.ppf(1.0 - alpha_noninf, acc_df) * acc_se
    rows.append(
        {
            "outcome": "accuracy",
            "test": test_name,
            "hypothesis": f"EMS - Control > -{acc_margin:.3f}",
            "control_mean": float(ctrl_acc.mean()),
            "ems_mean": float(ems_acc.mean()),
            "diff_ems_minus_control": float(acc_diff),
            "se": float(acc_se),
            "df": float(acc_df),
            "t": float(acc_t),
            "p_value_one_sided": float(acc_p),
            "ci_95_low": float(acc_ci_low),
            "ci_95_high": float(acc_ci_high),
            "one_sided_lower_bound": float(lower_bound),
            "margin": float(-acc_margin),
            "significant": bool(acc_p < alpha_noninf and lower_bound > -acc_margin),
            "effect_hedges_g": float(hedges_g(ems_acc, ctrl_acc)) if not paired else np.nan,
        }
    )

    return pd.DataFrame(rows), paired


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=str, default=None, help="Raw trial-level CSV.")
    parser.add_argument("--simulate", action="store_true", help="Generate dummy data via 01_simulate_data.py.")
    parser.add_argument("--n-subj", type=int, default=20, help="Subjects per group for --simulate.")
    parser.add_argument("--n-trials", type=int, default=80, help="Trials per subject for --simulate.")
    parser.add_argument("--rep-id", type=int, default=0, help="Seed/replication id for --simulate.")
    parser.add_argument("--outdir", type=str, default="results_behavioral_effects")

    parser.add_argument("--condition-col", type=str, default="condition")
    parser.add_argument("--subject-col", type=str, default="subj_idx")
    parser.add_argument("--rt-col", type=str, default="rt")
    parser.add_argument("--response-col", type=str, default="response")
    parser.add_argument("--stim-col", type=str, default="stim")
    parser.add_argument("--correct-col", type=str, default=None)
    parser.add_argument("--rt-unit", choices=["auto", "s", "ms"], default="auto")
    parser.add_argument("--control-label", type=str, default="control")
    parser.add_argument("--ems-label", type=str, default="ems")

    parser.add_argument("--acc-margin", type=float, default=0.03)
    parser.add_argument("--alpha-rt", type=float, default=0.05)
    parser.add_argument("--alpha-noninf", type=float, default=0.025)
    args = parser.parse_args()

    os.makedirs(args.outdir, exist_ok=True)

    df = prepare_trial_data(args)
    subj = subject_summary(df)
    trial = trial_summary(df)
    tests, paired = analyze_subject_level(
        subj,
        args.control_label,
        args.ems_label,
        args.acc_margin,
        args.alpha_rt,
        args.alpha_noninf,
    )

    df.to_csv(os.path.join(args.outdir, "trial_data_used.csv"), index=False)
    trial.to_csv(os.path.join(args.outdir, "trial_summary_by_condition.csv"), index=False)
    subj.to_csv(os.path.join(args.outdir, "subject_summary.csv"), index=False)
    tests.to_csv(os.path.join(args.outdir, "behavior_tests.csv"), index=False)

    metadata = {
        "source": "simulated" if args.simulate else args.data,
        "paired_design_detected": paired,
        "accuracy_rule": (
            "correct column"
            if args.correct_col and args.correct_col in df.columns
            else "response == stim"
            if args.stim_col in df.columns
            else "response as correctness"
        ),
        "rt_unit": args.rt_unit,
        "acc_noninferiority_margin": args.acc_margin,
        "alpha_rt": args.alpha_rt,
        "alpha_noninferiority": args.alpha_noninf,
    }
    with open(os.path.join(args.outdir, "analysis_metadata.json"), "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    print("=" * 72)
    print("Behavioral effects analysis")
    print("=" * 72)
    print(f"Output: {args.outdir}")
    print(f"Design: {'paired' if paired else 'independent groups'}")
    print("\nTrial-level descriptive summary:")
    print(trial.round(4).to_string(index=False))
    print("\nPrimary subject-level tests:")
    display_cols = [
        "outcome",
        "test",
        "hypothesis",
        "control_mean",
        "ems_mean",
        "diff_ems_minus_control",
        "ci_95_low",
        "ci_95_high",
        "p_value_one_sided",
        "significant",
    ]
    print(tests[display_cols].round(6).to_string(index=False))
    print("\nFiles written:")
    print(f"  {os.path.join(args.outdir, 'trial_summary_by_condition.csv')}")
    print(f"  {os.path.join(args.outdir, 'subject_summary.csv')}")
    print(f"  {os.path.join(args.outdir, 'behavior_tests.csv')}")


if __name__ == "__main__":
    main()
