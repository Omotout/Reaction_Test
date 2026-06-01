"""
Within-subject pre-post behavioral simulation.

Design:
- Every subject performs both self-training and EMS-training conditions.
- Each condition has pre and post sessions.
- Baseline DDM parameters are sampled once per subject and reused across
  conditions and phases.
- By default, only EMS post has shorter non-decision time t.

Primary tests:
- RT gain paired comparison:
      gain = pre RT - post RT
      H1: gain_ems - gain_self > 0
- Equivalent delta form:
      delta = post RT - pre RT
      H1: delta_ems - delta_self < 0
- Accuracy non-inferiority on paired change-score difference:
      DeltaAcc_EMS - DeltaAcc_Self > -margin

This is an optimistic model in the sense that it captures subject-level
individual differences and trial noise, but not carryover, order effects, or
day-to-day parameter drift unless optional session-level t noise is enabled.
"""

import argparse
import importlib.util
import os

import hddm
import numpy as np
import pandas as pd
from scipy import stats

from utils import PARAM_LOWER, SUBJ_VAR, TRUE_PARAMS


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def sample_subject_params(rng, subj_var_scale=1.0):
    base = TRUE_PARAMS["control"]
    return {
        "a": max(PARAM_LOWER["a"], rng.normal(base["a"], SUBJ_VAR["a_sd"] * subj_var_scale)),
        "v": max(PARAM_LOWER["v"], rng.normal(base["v"], SUBJ_VAR["v_sd"] * subj_var_scale)),
        "t": max(PARAM_LOWER["t"], rng.normal(base["t"], SUBJ_VAR["t_sd"] * subj_var_scale)),
        "z": base["z"],
    }


def simulate_one_subject_session(params, n_trials, seed):
    rng = np.random.default_rng(seed)
    stims = rng.integers(0, 2, size=n_trials)
    data, _ = hddm.generate.gen_rand_data(
        {"a": params["a"], "v": params["v"], "t": params["t"], "z": params["z"]},
        size=n_trials,
        subjs=1,
        subj_noise=0.0,
    )
    correct = data["response"].astype(int).values
    response_lr = np.where(correct == 1, stims, 1 - stims)
    return pd.DataFrame(
        {
            "rt": data["rt"].values,
            "response": response_lr.astype(int),
            "stim": stims.astype(int),
        }
    )


def simulate_within_subject(
    n_subj,
    n_trials,
    seed,
    ems_post_t_delta_ms=-8.0,
    self_post_t_delta_ms=0.0,
    session_t_noise_sd_ms=0.0,
    subj_var_scale=1.0,
):
    rng = np.random.default_rng(seed)
    rows = []

    for subj_idx in range(n_subj):
        subj_label = f"subj_{subj_idx:03d}"
        base_params = sample_subject_params(rng, subj_var_scale=subj_var_scale)

        for condition, post_delta_ms in [
            ("self", self_post_t_delta_ms),
            ("ems", ems_post_t_delta_ms),
        ]:
            # Optional condition/session baseline drift. The same condition shift
            # is applied to pre and post, so it mostly represents day-level speed.
            condition_t_shift = rng.normal(0.0, session_t_noise_sd_ms / 1000.0)

            for phase, phase_delta_ms in [
                ("pre", 0.0),
                ("post", post_delta_ms),
            ]:
                params = dict(base_params)
                params["t"] = max(
                    PARAM_LOWER["t"],
                    params["t"] + condition_t_shift + phase_delta_ms / 1000.0,
                )
                session_seed = int(rng.integers(0, 1_000_000_000))
                df = simulate_one_subject_session(params, n_trials, seed=session_seed)
                df["subj_idx"] = subj_label
                df["condition"] = condition
                df["phase"] = phase
                df["cell"] = f"{condition}_{phase}"
                df["a_true"] = params["a"]
                df["v_true"] = params["v"]
                df["t_true"] = params["t"]
                rows.append(df)

    out = pd.concat(rows, ignore_index=True)
    out["correct"] = (out["response"] == out["stim"]).astype(int)
    return out


def subject_summary(df, rt_stat="mean_correct"):
    df = df.copy()
    df["rt_correct"] = df["rt"].where(df["correct"] == 1)
    subj = (
        df.groupby(["subj_idx", "condition", "phase"], as_index=False)
        .agg(
            mean_rt_ms=("rt", lambda x: x.mean() * 1000.0),
            median_rt_ms=("rt", lambda x: x.median() * 1000.0),
            mean_correct_rt_ms=("rt_correct", lambda x: x.mean() * 1000.0),
            median_correct_rt_ms=("rt_correct", lambda x: x.median() * 1000.0),
            accuracy=("correct", "mean"),
            n_trials=("rt", "count"),
            n_correct=("correct", "sum"),
        )
    )
    wide = subj.pivot(index="subj_idx", columns=["condition", "phase"])
    wide.columns = [f"{metric}_{condition}_{phase}" for metric, condition, phase in wide.columns]
    wide = wide.reset_index()

    metric_by_stat = {
        "mean": "mean_rt_ms",
        "median": "median_rt_ms",
        "mean_correct": "mean_correct_rt_ms",
        "median_correct": "median_correct_rt_ms",
    }
    if rt_stat not in metric_by_stat:
        raise ValueError(f"Unknown rt_stat: {rt_stat}")
    metric = metric_by_stat[rt_stat]

    wide["delta_rt_self_ms"] = wide[f"{metric}_self_post"] - wide[f"{metric}_self_pre"]
    wide["delta_rt_ems_ms"] = wide[f"{metric}_ems_post"] - wide[f"{metric}_ems_pre"]
    wide["gain_rt_self_ms"] = -wide["delta_rt_self_ms"]
    wide["gain_rt_ems_ms"] = -wide["delta_rt_ems_ms"]
    wide["rt_did_ms"] = wide["delta_rt_ems_ms"] - wide["delta_rt_self_ms"]
    wide["rt_gain_diff_ms"] = wide["gain_rt_ems_ms"] - wide["gain_rt_self_ms"]

    wide["delta_acc_self"] = wide["accuracy_self_post"] - wide["accuracy_self_pre"]
    wide["delta_acc_ems"] = wide["accuracy_ems_post"] - wide["accuracy_ems_pre"]
    wide["acc_did"] = wide["delta_acc_ems"] - wide["delta_acc_self"]
    return subj, wide


def paired_test(diff_samples, null=0.0, alternative="greater"):
    diff_samples = np.asarray(diff_samples, dtype=float)
    n = len(diff_samples)
    mean = diff_samples.mean()
    sd = diff_samples.std(ddof=1)
    se = sd / np.sqrt(n)
    df = n - 1
    t_value = (mean - null) / se
    if alternative == "greater":
        p_value = 1.0 - stats.t.cdf(t_value, df)
    elif alternative == "less":
        p_value = stats.t.cdf(t_value, df)
    else:
        p_value = 2.0 * min(stats.t.cdf(t_value, df), 1.0 - stats.t.cdf(t_value, df))
    ci95 = stats.t.ppf(0.975, df) * se
    return {
        "mean": float(mean),
        "sd": float(sd),
        "se": float(se),
        "df": float(df),
        "t": float(t_value),
        "p": float(p_value),
        "ci95_low": float(mean - ci95),
        "ci95_high": float(mean + ci95),
    }


def repeated_measures_interaction(rt_did_ms):
    # For a 2(condition) x 2(time) fully repeated design, the interaction is
    # equivalent to a paired t-test on the condition difference in change scores.
    test = paired_test(rt_did_ms, null=0.0, alternative="two-sided")
    return {
        "f": float(test["t"] ** 2),
        "df1": 1.0,
        "df2": test["df"],
        "p": test["p"],
    }


def analyze_one(df, acc_margin=0.03, alpha_rt=0.05, alpha_noninf=0.025, rt_stat="mean_correct"):
    df = df.copy()
    df["rt_correct"] = df["rt"].where(df["correct"] == 1)
    subj, wide = subject_summary(df, rt_stat=rt_stat)

    # Main planned comparison in gain notation: gain_ems - gain_self > 0.
    rt_gain = paired_test(wide["rt_gain_diff_ms"], null=0.0, alternative="greater")
    rt_rm = repeated_measures_interaction(wide["rt_did_ms"])

    # Accuracy non-inferiority: acc_did > -margin.
    acc = paired_test(wide["acc_did"], null=-acc_margin, alternative="greater")
    acc_lower = acc["mean"] - stats.t.ppf(1.0 - alpha_noninf, acc["df"]) * acc["se"]

    cell_summary = (
        df.groupby(["condition", "phase"], as_index=False)
        .agg(
            mean_rt_ms=("rt", lambda x: x.mean() * 1000.0),
            median_rt_ms=("rt", lambda x: x.median() * 1000.0),
            mean_correct_rt_ms=("rt_correct", lambda x: x.mean() * 1000.0),
            median_correct_rt_ms=("rt_correct", lambda x: x.median() * 1000.0),
            accuracy=("correct", "mean"),
            n_trials=("rt", "count"),
            n_correct=("correct", "sum"),
            n_subj=("subj_idx", "nunique"),
        )
    )

    result = {
        "rt_gain_diff_ms": rt_gain["mean"],
        "rt_gain_diff_sd_ms": rt_gain["sd"],
        "rt_gain_p_one_sided": rt_gain["p"],
        "rt_gain_ci95_low": rt_gain["ci95_low"],
        "rt_gain_ci95_high": rt_gain["ci95_high"],
        "rt_success": bool(rt_gain["p"] < alpha_rt),
        "rt_direction": bool(rt_gain["mean"] > 0),
        "rt_rm_anova_F": rt_rm["f"],
        "rt_rm_anova_df1": rt_rm["df1"],
        "rt_rm_anova_df2": rt_rm["df2"],
        "rt_rm_anova_p": rt_rm["p"],
        "rt_rm_anova_success": bool(rt_rm["p"] < 0.05),
        "acc_did": acc["mean"],
        "acc_did_sd": acc["sd"],
        "acc_noninf_p": acc["p"],
        "acc_noninf_lower_bound": float(acc_lower),
        "acc_noninf_success": bool(acc["p"] < alpha_noninf and acc_lower > -acc_margin),
        "both_success": bool(rt_gain["p"] < alpha_rt and acc["p"] < alpha_noninf and acc_lower > -acc_margin),
    }
    return result, cell_summary, subj, wide


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n-subj", type=int, default=20)
    parser.add_argument("--n-trials", type=int, default=80, help="Trials per condition-phase cell.")
    parser.add_argument("--n-reps", type=int, default=100)
    parser.add_argument("--seed-offset", type=int, default=0)
    parser.add_argument("--ems-post-t-delta-ms", type=float, default=-8.0)
    parser.add_argument("--self-post-t-delta-ms", type=float, default=0.0)
    parser.add_argument("--session-t-noise-sd-ms", type=float, default=0.0)
    parser.add_argument("--subj-var-scale", type=float, default=1.0)
    parser.add_argument(
        "--rt-stat",
        choices=["mean", "median", "mean_correct", "median_correct"],
        default="mean_correct",
        help="RT statistic used for the main gain analysis.",
    )
    parser.add_argument("--acc-margin", type=float, default=0.03)
    parser.add_argument("--alpha-rt", type=float, default=0.05)
    parser.add_argument("--alpha-noninf", type=float, default=0.025)
    parser.add_argument("--outdir", default="results_within_subject_behavioral_power")
    parser.add_argument("--save-first-trial-data", action="store_true")
    args = parser.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    rows = []
    first_outputs = None

    for rep in range(args.n_reps):
        rep_id = args.seed_offset + rep
        df = simulate_within_subject(
            n_subj=args.n_subj,
            n_trials=args.n_trials,
            seed=rep_id,
            ems_post_t_delta_ms=args.ems_post_t_delta_ms,
            self_post_t_delta_ms=args.self_post_t_delta_ms,
            session_t_noise_sd_ms=args.session_t_noise_sd_ms,
            subj_var_scale=args.subj_var_scale,
        )
        result, cell_summary, subj, wide = analyze_one(
            df,
            acc_margin=args.acc_margin,
            alpha_rt=args.alpha_rt,
            alpha_noninf=args.alpha_noninf,
            rt_stat=args.rt_stat,
        )
        result.update(
            {
                "rep_id": rep_id,
                "n_subj": args.n_subj,
                "n_trials": args.n_trials,
                "ems_post_t_delta_ms": args.ems_post_t_delta_ms,
                "self_post_t_delta_ms": args.self_post_t_delta_ms,
                "session_t_noise_sd_ms": args.session_t_noise_sd_ms,
                "subj_var_scale": args.subj_var_scale,
                "rt_stat": args.rt_stat,
            }
        )
        rows.append(result)
        if rep == 0:
            first_outputs = (df, cell_summary, subj, wide)
        if (rep + 1) % 10 == 0 or rep + 1 == args.n_reps:
            print(f"Completed {rep + 1}/{args.n_reps} reps")

    results = pd.DataFrame(rows)
    summary = pd.DataFrame(
        [
            {
                "n_subj": args.n_subj,
                "n_trials": args.n_trials,
                "n_reps": args.n_reps,
                "ems_post_t_delta_ms": args.ems_post_t_delta_ms,
                "self_post_t_delta_ms": args.self_post_t_delta_ms,
                "session_t_noise_sd_ms": args.session_t_noise_sd_ms,
                "subj_var_scale": args.subj_var_scale,
                "rt_stat": args.rt_stat,
                "rt_gain_diff_mean_ms": results["rt_gain_diff_ms"].mean(),
                "rt_gain_diff_sd_ms": results["rt_gain_diff_ms"].std(),
                "rt_direction_rate": results["rt_direction"].mean(),
                "rt_success_rate": results["rt_success"].mean(),
                "rt_rm_anova_success_rate": results["rt_rm_anova_success"].mean(),
                "acc_did_mean": results["acc_did"].mean(),
                "acc_did_sd": results["acc_did"].std(),
                "acc_noninf_success_rate": results["acc_noninf_success"].mean(),
                "both_success_rate": results["both_success"].mean(),
            }
        ]
    )

    tag = f"n{args.n_subj}_t{args.n_trials}_reps{args.n_reps}"
    results_path = os.path.join(args.outdir, f"within_subject_behavioral_results_{tag}.csv")
    summary_path = os.path.join(args.outdir, f"within_subject_behavioral_summary_{tag}.csv")
    results.to_csv(results_path, index=False)
    summary.to_csv(summary_path, index=False)

    if first_outputs is not None:
        df, cell_summary, subj, wide = first_outputs
        cell_summary.to_csv(os.path.join(args.outdir, "rep0_cell_summary.csv"), index=False)
        subj.to_csv(os.path.join(args.outdir, "rep0_subject_session_summary.csv"), index=False)
        wide.to_csv(os.path.join(args.outdir, "rep0_subject_change_scores.csv"), index=False)
        if args.save_first_trial_data:
            df.to_csv(os.path.join(args.outdir, "rep0_trial_data.csv"), index=False)

    print("\nSummary:")
    print(summary.round(4).to_string(index=False))
    print("\nFiles written:")
    print(f"  {results_path}")
    print(f"  {summary_path}")
    print(f"  {os.path.join(args.outdir, 'rep0_subject_change_scores.csv')}")


if __name__ == "__main__":
    main()
