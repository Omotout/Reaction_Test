"""
Pre-post behavioral simulation for the planned training design.

Design:
- Two independent groups: self-training and EMS-training.
- Each subject has pre and post sessions.
- Baseline DDM parameters are sampled once per subject and reused for pre/post.
- By default, only EMS post has shorter non-decision time t.

Primary tests use subject-level pre-post change scores:
- RT: difference-in-differences
      (EMS_post - EMS_pre) - (Self_post - Self_pre) < 0
- Accuracy: non-inferiority of the same change-score contrast
      DeltaAcc_EMS - DeltaAcc_Self > -margin
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


def load_behavior_module():
    spec = importlib.util.spec_from_file_location(
        "behavior",
        os.path.join(SCRIPT_DIR, "05_analyze_behavioral_effects.py"),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


behavior = load_behavior_module()


def sample_subject_params(rng):
    base = TRUE_PARAMS["control"]
    return {
        "a": max(PARAM_LOWER["a"], rng.normal(base["a"], SUBJ_VAR["a_sd"])),
        "v": max(PARAM_LOWER["v"], rng.normal(base["v"], SUBJ_VAR["v_sd"])),
        "t": max(PARAM_LOWER["t"], rng.normal(base["t"], SUBJ_VAR["t_sd"])),
        "z": base["z"],
    }


def simulate_one_subject(params, n_trials, seed):
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


def simulate_prepost(
    n_subj_per_group,
    n_trials,
    seed,
    ems_post_t_delta_ms=-8.0,
    self_post_t_delta_ms=0.0,
):
    rng = np.random.default_rng(seed)
    rows = []

    group_specs = [
        ("self", self_post_t_delta_ms / 1000.0),
        ("ems", ems_post_t_delta_ms / 1000.0),
    ]
    for group, post_t_delta in group_specs:
        for subj_in_group in range(n_subj_per_group):
            subj_idx = f"{group}_{subj_in_group:03d}"
            base_params = sample_subject_params(rng)

            session_specs = [
                ("pre", 0.0),
                ("post", post_t_delta),
            ]
            for phase, t_delta in session_specs:
                params = dict(base_params)
                params["t"] = max(PARAM_LOWER["t"], params["t"] + t_delta)
                session_seed = int(rng.integers(0, 1_000_000_000))
                df = simulate_one_subject(params, n_trials, seed=session_seed)
                df["group"] = group
                df["phase"] = phase
                df["subj_idx"] = subj_idx
                df["a_true"] = params["a"]
                df["v_true"] = params["v"]
                df["t_true"] = params["t"]
                rows.append(df)

    out = pd.concat(rows, ignore_index=True)
    out["condition"] = out["group"] + "_" + out["phase"]
    out["correct"] = (out["response"] == out["stim"]).astype(int)
    return out


def subject_prepost_summary(df):
    subj = (
        df.groupby(["group", "phase", "subj_idx"], as_index=False)
        .agg(
            mean_rt_ms=("rt", lambda x: x.mean() * 1000.0),
            median_rt_ms=("rt", lambda x: x.median() * 1000.0),
            accuracy=("correct", "mean"),
            n_trials=("rt", "count"),
        )
    )
    wide = subj.pivot(index=["group", "subj_idx"], columns="phase")
    wide.columns = [f"{metric}_{phase}" for metric, phase in wide.columns]
    wide = wide.reset_index()
    wide["delta_rt_ms"] = wide["mean_rt_ms_post"] - wide["mean_rt_ms_pre"]
    wide["delta_accuracy"] = wide["accuracy_post"] - wide["accuracy_pre"]
    return subj, wide


def independent_test(ems, ctrl, null=0.0, alternative="less"):
    ems = np.asarray(ems, dtype=float)
    ctrl = np.asarray(ctrl, dtype=float)
    diff = ems.mean() - ctrl.mean()
    se = np.sqrt(ems.var(ddof=1) / len(ems) + ctrl.var(ddof=1) / len(ctrl))
    df_num = se**4
    df_den = (
        (ems.var(ddof=1) / len(ems)) ** 2 / (len(ems) - 1)
        + (ctrl.var(ddof=1) / len(ctrl)) ** 2 / (len(ctrl) - 1)
    )
    df = df_num / df_den
    t_value = (diff - null) / se
    if alternative == "less":
        p_value = stats.t.cdf(t_value, df)
    elif alternative == "greater":
        p_value = 1.0 - stats.t.cdf(t_value, df)
    else:
        p_value = 2.0 * min(stats.t.cdf(t_value, df), 1.0 - stats.t.cdf(t_value, df))
    ci95 = stats.t.ppf(0.975, df) * se
    return {
        "diff": float(diff),
        "se": float(se),
        "df": float(df),
        "t": float(t_value),
        "p": float(p_value),
        "ci95_low": float(diff - ci95),
        "ci95_high": float(diff + ci95),
    }


def mixed_anova_interaction_on_change(ems_change, self_change):
    """
    2(group) x 2(time) mixed ANOVA interaction.

    With two time points, the group x time interaction is equivalent to an
    ordinary between-group ANOVA on subject-level change scores. This reports
    the ANOVA-style F statistic and a two-sided p-value.
    """
    ems_change = np.asarray(ems_change, dtype=float)
    self_change = np.asarray(self_change, dtype=float)
    n_ems = len(ems_change)
    n_self = len(self_change)
    df_between = 1
    df_error = n_ems + n_self - 2

    grand = np.concatenate([ems_change, self_change]).mean()
    ss_between = (
        n_ems * (ems_change.mean() - grand) ** 2
        + n_self * (self_change.mean() - grand) ** 2
    )
    ss_error = (
        ((ems_change - ems_change.mean()) ** 2).sum()
        + ((self_change - self_change.mean()) ** 2).sum()
    )
    ms_between = ss_between / df_between
    ms_error = ss_error / df_error
    f_value = ms_between / ms_error
    p_value = 1.0 - stats.f.cdf(f_value, df_between, df_error)

    return {
        "f": float(f_value),
        "df1": float(df_between),
        "df2": float(df_error),
        "p": float(p_value),
    }


def analyze_one(df, acc_margin=0.03, alpha_rt=0.05, alpha_noninf=0.025):
    subj, wide = subject_prepost_summary(df)
    self_wide = wide[wide["group"] == "self"]
    ems_wide = wide[wide["group"] == "ems"]

    rt = independent_test(
        ems_wide["delta_rt_ms"],
        self_wide["delta_rt_ms"],
        null=0.0,
        alternative="less",
    )
    rt_mixed = mixed_anova_interaction_on_change(
        ems_wide["delta_rt_ms"],
        self_wide["delta_rt_ms"],
    )
    acc = independent_test(
        ems_wide["delta_accuracy"],
        self_wide["delta_accuracy"],
        null=-acc_margin,
        alternative="greater",
    )
    acc_lower = acc["diff"] - stats.t.ppf(1.0 - alpha_noninf, acc["df"]) * acc["se"]

    summary_by_cell = (
        df.groupby(["group", "phase"], as_index=False)
        .agg(
            mean_rt_ms=("rt", lambda x: x.mean() * 1000.0),
            median_rt_ms=("rt", lambda x: x.median() * 1000.0),
            accuracy=("correct", "mean"),
            n_trials=("rt", "count"),
            n_subj=("subj_idx", "nunique"),
        )
    )

    delta_summary = (
        wide.groupby("group", as_index=False)
        .agg(
            delta_rt_ms_mean=("delta_rt_ms", "mean"),
            delta_rt_ms_sd=("delta_rt_ms", "std"),
            delta_accuracy_mean=("delta_accuracy", "mean"),
            delta_accuracy_sd=("delta_accuracy", "std"),
            n_subj=("subj_idx", "nunique"),
        )
    )

    result = {
        "rt_did_ms": rt["diff"],
        "rt_did_se": rt["se"],
        "rt_did_p_one_sided": rt["p"],
        "rt_did_ci95_low": rt["ci95_low"],
        "rt_did_ci95_high": rt["ci95_high"],
        "rt_success": bool(rt["p"] < alpha_rt),
        "rt_mixed_anova_F": rt_mixed["f"],
        "rt_mixed_anova_df1": rt_mixed["df1"],
        "rt_mixed_anova_df2": rt_mixed["df2"],
        "rt_mixed_anova_p": rt_mixed["p"],
        "rt_mixed_anova_success": bool(rt_mixed["p"] < 0.05),
        "acc_did": acc["diff"],
        "acc_did_se": acc["se"],
        "acc_noninf_p": acc["p"],
        "acc_noninf_lower_bound": float(acc_lower),
        "acc_noninf_success": bool(acc["p"] < alpha_noninf and acc_lower > -acc_margin),
        "both_success": bool(rt["p"] < alpha_rt and acc["p"] < alpha_noninf and acc_lower > -acc_margin),
    }
    return result, summary_by_cell, subj, wide, delta_summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n-subj", type=int, default=20, help="Subjects per group.")
    parser.add_argument("--n-trials", type=int, default=80, help="Trials per pre/post session.")
    parser.add_argument("--n-reps", type=int, default=100)
    parser.add_argument("--seed-offset", type=int, default=0)
    parser.add_argument("--ems-post-t-delta-ms", type=float, default=-8.0)
    parser.add_argument("--self-post-t-delta-ms", type=float, default=0.0)
    parser.add_argument("--acc-margin", type=float, default=0.03)
    parser.add_argument("--alpha-rt", type=float, default=0.05)
    parser.add_argument("--alpha-noninf", type=float, default=0.025)
    parser.add_argument("--outdir", type=str, default="results_prepost_behavioral_power")
    parser.add_argument("--save-first-trial-data", action="store_true")
    args = parser.parse_args()

    os.makedirs(args.outdir, exist_ok=True)

    rows = []
    first_outputs = None
    for rep in range(args.n_reps):
        rep_id = args.seed_offset + rep
        df = simulate_prepost(
            n_subj_per_group=args.n_subj,
            n_trials=args.n_trials,
            seed=rep_id,
            ems_post_t_delta_ms=args.ems_post_t_delta_ms,
            self_post_t_delta_ms=args.self_post_t_delta_ms,
        )
        result, cell_summary, subj, wide, delta_summary = analyze_one(
            df,
            acc_margin=args.acc_margin,
            alpha_rt=args.alpha_rt,
            alpha_noninf=args.alpha_noninf,
        )
        result.update(
            {
                "rep_id": rep_id,
                "n_subj": args.n_subj,
                "n_trials": args.n_trials,
                "ems_post_t_delta_ms": args.ems_post_t_delta_ms,
                "self_post_t_delta_ms": args.self_post_t_delta_ms,
            }
        )
        rows.append(result)
        if rep == 0:
            first_outputs = (df, cell_summary, subj, wide, delta_summary)
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
                "rt_did_mean_ms": results["rt_did_ms"].mean(),
                "rt_did_sd_ms": results["rt_did_ms"].std(),
                "rt_direction_rate": (results["rt_did_ms"] < 0).mean(),
                "rt_success_rate": results["rt_success"].mean(),
                "rt_mixed_anova_success_rate": results["rt_mixed_anova_success"].mean(),
                "acc_did_mean": results["acc_did"].mean(),
                "acc_did_sd": results["acc_did"].std(),
                "acc_noninf_success_rate": results["acc_noninf_success"].mean(),
                "both_success_rate": results["both_success"].mean(),
            }
        ]
    )

    tag = f"n{args.n_subj}_t{args.n_trials}_reps{args.n_reps}"
    results_path = os.path.join(args.outdir, f"prepost_behavioral_results_{tag}.csv")
    summary_path = os.path.join(args.outdir, f"prepost_behavioral_summary_{tag}.csv")
    results.to_csv(results_path, index=False)
    summary.to_csv(summary_path, index=False)

    if first_outputs is not None:
        df, cell_summary, subj, wide, delta_summary = first_outputs
        cell_summary.to_csv(os.path.join(args.outdir, "rep0_cell_summary.csv"), index=False)
        subj.to_csv(os.path.join(args.outdir, "rep0_subject_session_summary.csv"), index=False)
        wide.to_csv(os.path.join(args.outdir, "rep0_subject_change_scores.csv"), index=False)
        delta_summary.to_csv(os.path.join(args.outdir, "rep0_delta_summary.csv"), index=False)
        if args.save_first_trial_data:
            df.to_csv(os.path.join(args.outdir, "rep0_trial_data.csv"), index=False)

    print("\nSummary:")
    print(summary.round(4).to_string(index=False))
    print("\nFiles written:")
    print(f"  {results_path}")
    print(f"  {summary_path}")
    print(f"  {os.path.join(args.outdir, 'rep0_delta_summary.csv')}")


if __name__ == "__main__":
    main()
