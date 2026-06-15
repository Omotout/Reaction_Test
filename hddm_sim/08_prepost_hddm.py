"""
HDDMStimCoding analysis for the pre-post training design.

The main HDDM estimands are:
- EMS within-group change:
    a(ems_post) - a(ems_pre)
    t(ems_post) - t(ems_pre)
- Difference-in-differences:
    [ems_post - ems_pre] - [self_post - self_pre]

This script simulates dummy pre/post data via 07_prepost_behavioral_power.py,
fits HDDMStimCoding with condition-specific a/v/t, and summarizes posterior
differences with HDIs, fixed ROPE decisions, and Szul-style P(P|D).
"""

import argparse
import importlib.util
import os
import time
import warnings

import hddm
import numpy as np
import pandas as pd

from utils import (
    ROPE,
    empirical_rope_szul,
    hdi,
    p_pd_szul,
    rope_decision,
    superiority_decision,
)


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def load_prepost_module():
    spec = importlib.util.spec_from_file_location(
        "prepost",
        os.path.join(SCRIPT_DIR, "07_prepost_behavioral_power.py"),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


prepost = load_prepost_module()


CONDITIONS = ["self_pre", "self_post", "ems_pre", "ems_post"]
PARAMS = ["a", "v", "t"]


def trace(model, param, condition):
    return model.nodes_db.node[f"{param}({condition})"].trace()


def summarize_diff(name, diff_samples, rope=None, direction=None):
    low, high = hdi(diff_samples, prob=0.95)
    row = {
        f"{name}_mean": float(diff_samples.mean()),
        f"{name}_sd": float(diff_samples.std()),
        f"{name}_hdi_low": float(low),
        f"{name}_hdi_high": float(high),
    }
    if rope is not None:
        if direction is None:
            row[f"{name}_decision"] = rope_decision(diff_samples, *rope)
        else:
            row[f"{name}_decision"] = superiority_decision(diff_samples, *rope, direction=direction)
    return row


def summarize_empirical_equivalence(name, pre_samples, post_samples, diff_samples):
    rope = empirical_rope_szul(pre_samples, post_samples)
    return {
        f"{name}_rope_emp_low": float(rope[0]),
        f"{name}_rope_emp_high": float(rope[1]),
        f"{name}_rope_emp_width": float(rope[1] - rope[0]),
        f"{name}_decision_emp": rope_decision(diff_samples, *rope),
        f"{name}_p_pd": float(p_pd_szul(diff_samples, *rope)),
    }


def behavioral_summaries(df):
    result, cell_summary, subj, wide, delta_summary = prepost.analyze_one(df)
    return result, cell_summary, subj, wide, delta_summary


def fit_one_replication(
    n_subj,
    n_trials,
    rep_id,
    ems_post_t_delta_ms=-8.0,
    self_post_t_delta_ms=0.0,
    n_samples=2000,
    burn=1000,
    thin=2,
    save_trial_data=False,
    outdir=None,
):
    df = prepost.simulate_prepost(
        n_subj_per_group=n_subj,
        n_trials=n_trials,
        seed=rep_id,
        ems_post_t_delta_ms=ems_post_t_delta_ms,
        self_post_t_delta_ms=self_post_t_delta_ms,
    )
    beh, cell_summary, subj_summary, change_scores, delta_summary = behavioral_summaries(df)

    df_fit = df[["subj_idx", "rt", "response", "stim", "condition"]].copy()
    df_fit["subj_idx"] = pd.factorize(df_fit["subj_idx"])[0]
    df_fit["response"] = df_fit["response"].astype(int)
    df_fit["stim"] = df_fit["stim"].astype(int)
    df_fit["condition"] = pd.Categorical(df_fit["condition"], categories=CONDITIONS)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = hddm.HDDMStimCoding(
            df_fit,
            include=["v", "a", "t"],
            stim_col="stim",
            split_param="v",
            depends_on={"a": "condition", "v": "condition", "t": "condition"},
        )
        model.find_starting_values()
        t0 = time.time()
        model.sample(n_samples, burn=burn, thin=thin, dbname=None, db="ram")
        elapsed = time.time() - t0

    samples = {
        param: {condition: trace(model, param, condition) for condition in CONDITIONS}
        for param in PARAMS
    }

    result = {
        "rep_id": rep_id,
        "n_subj": n_subj,
        "n_trials": n_trials,
        "ems_post_t_delta_ms": ems_post_t_delta_ms,
        "self_post_t_delta_ms": self_post_t_delta_ms,
        "fit_time_sec": float(elapsed),
        "rt_did_ms": beh["rt_did_ms"],
        "rt_success": beh["rt_success"],
        "acc_did": beh["acc_did"],
        "acc_noninf_success": beh["acc_noninf_success"],
    }

    for param in PARAMS:
        self_delta = samples[param]["self_post"] - samples[param]["self_pre"]
        ems_delta = samples[param]["ems_post"] - samples[param]["ems_pre"]
        did = ems_delta - self_delta

        rope = ROPE[param]
        ems_name = f"{param}_ems_prepost"
        did_name = f"{param}_did"

        if param == "t":
            result.update(summarize_diff(ems_name, ems_delta, rope=rope, direction="negative"))
            result.update(summarize_diff(did_name, did, rope=rope, direction="negative"))
        else:
            result.update(summarize_diff(ems_name, ems_delta, rope=rope))
            result.update(summarize_diff(did_name, did, rope=rope))

        result.update(
            summarize_empirical_equivalence(
                ems_name,
                samples[param]["ems_pre"],
                samples[param]["ems_post"],
                ems_delta,
            )
        )
        result.update(
            summarize_empirical_equivalence(
                did_name,
                self_delta,
                ems_delta,
                did,
            )
        )

    if outdir is not None and rep_id == 0:
        os.makedirs(outdir, exist_ok=True)
        cell_summary.to_csv(os.path.join(outdir, "rep0_behavior_cell_summary.csv"), index=False)
        subj_summary.to_csv(os.path.join(outdir, "rep0_behavior_subject_summary.csv"), index=False)
        change_scores.to_csv(os.path.join(outdir, "rep0_behavior_change_scores.csv"), index=False)
        delta_summary.to_csv(os.path.join(outdir, "rep0_behavior_delta_summary.csv"), index=False)
        if save_trial_data:
            df.to_csv(os.path.join(outdir, "rep0_trial_data.csv"), index=False)

    return result


def summarize_results(results):
    df = pd.DataFrame(results)
    summary = pd.DataFrame(
        [
            {
                "n_subj": int(df["n_subj"].iloc[0]),
                "n_trials": int(df["n_trials"].iloc[0]),
                "n_reps": len(df),
                "rt_success_rate": df["rt_success"].mean(),
                "acc_noninf_success_rate": df["acc_noninf_success"].mean(),
                "a_ems_equiv_rate_fixed": (df["a_ems_prepost_decision"] == "equivalent").mean(),
                "a_ems_equiv_rate_emp": (df["a_ems_prepost_decision_emp"] == "equivalent").mean(),
                "a_ems_p_pd_mean": df["a_ems_prepost_p_pd"].mean(),
                "t_ems_super_rate": (df["t_ems_prepost_decision"] == "superior").mean(),
                "t_ems_mean_ms": df["t_ems_prepost_mean"].mean() * 1000.0,
                "a_did_equiv_rate_fixed": (df["a_did_decision"] == "equivalent").mean(),
                "a_did_equiv_rate_emp": (df["a_did_decision_emp"] == "equivalent").mean(),
                "a_did_p_pd_mean": df["a_did_p_pd"].mean(),
                "t_did_super_rate": (df["t_did_decision"] == "superior").mean(),
                "t_did_mean_ms": df["t_did_mean"].mean() * 1000.0,
            }
        ]
    )
    return df, summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n-subj", type=int, default=20, help="Subjects per group.")
    parser.add_argument("--n-trials", type=int, default=80, help="Trials per pre/post session.")
    parser.add_argument("--n-reps", type=int, default=1)
    parser.add_argument("--seed-offset", type=int, default=0)
    parser.add_argument("--ems-post-t-delta-ms", type=float, default=-8.0)
    parser.add_argument("--self-post-t-delta-ms", type=float, default=0.0)
    parser.add_argument("--n-samples", type=int, default=2000)
    parser.add_argument("--burn", type=int, default=1000)
    parser.add_argument("--thin", type=int, default=2)
    parser.add_argument("--outdir", type=str, default="results_prepost_hddm")
    parser.add_argument("--save-first-trial-data", action="store_true")
    args = parser.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    results = []
    for i in range(args.n_reps):
        rep_id = args.seed_offset + i
        print(f"\n=== Rep {i + 1}/{args.n_reps} (rep_id={rep_id}) ===")
        result = fit_one_replication(
            n_subj=args.n_subj,
            n_trials=args.n_trials,
            rep_id=rep_id,
            ems_post_t_delta_ms=args.ems_post_t_delta_ms,
            self_post_t_delta_ms=args.self_post_t_delta_ms,
            n_samples=args.n_samples,
            burn=args.burn,
            thin=args.thin,
            save_trial_data=args.save_first_trial_data,
            outdir=args.outdir,
        )
        results.append(result)
        print(
            "EMS pre-post: "
            f"a={result['a_ems_prepost_mean']:+.4f} "
            f"({result['a_ems_prepost_decision']}, PPD={result['a_ems_prepost_p_pd']:.3f}), "
            f"t={result['t_ems_prepost_mean'] * 1000:+.2f} ms "
            f"({result['t_ems_prepost_decision']})"
        )
        print(
            "DiD: "
            f"a={result['a_did_mean']:+.4f} "
            f"({result['a_did_decision']}, PPD={result['a_did_p_pd']:.3f}), "
            f"t={result['t_did_mean'] * 1000:+.2f} ms "
            f"({result['t_did_decision']})"
        )

    results_df, summary = summarize_results(results)
    tag = f"n{args.n_subj}_t{args.n_trials}_reps{args.n_reps}"
    results_path = os.path.join(args.outdir, f"prepost_hddm_results_{tag}.csv")
    summary_path = os.path.join(args.outdir, f"prepost_hddm_summary_{tag}.csv")
    results_df.to_csv(results_path, index=False)
    summary.to_csv(summary_path, index=False)

    print("\nSummary:")
    print(summary.round(4).to_string(index=False))
    print("\nFiles written:")
    print(f"  {results_path}")
    print(f"  {summary_path}")


if __name__ == "__main__":
    main()
