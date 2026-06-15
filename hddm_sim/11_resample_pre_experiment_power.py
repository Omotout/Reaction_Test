"""
Bootstrap/resampling power check based on the pre-experiment trial data.

This avoids assuming a full DDM generative model for behavioral power. Instead,
it resamples participant-level trial RT/accuracy from pre_experiment_data.csv
and injects a hypothesized EMS post RT shift.

Supported designs:
- within: each simulated subject contributes self and EMS conditions.
- between: independent self and EMS groups.

Main RT test:
- RT gain = pre - post, computed on correct trials by default.
- within: paired t-test on gain_ems - gain_self > 0.
- between: Welch one-sided t-test on gain_ems - gain_self > 0.
"""

import argparse
import os

import numpy as np
import pandas as pd
from scipy import stats


def load_pre_experiment(path):
    df = pd.read_csv(path)
    required = {"subj_idx", "rt", "response"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")
    df = df.copy()
    df["correct"] = pd.to_numeric(df["response"], errors="coerce").astype(int)
    df["rt_ms"] = pd.to_numeric(df["rt"], errors="coerce") * 1000.0
    df = df.dropna(subset=["subj_idx", "rt_ms", "correct"])
    return df


def sample_trials(pool, n_trials, rng, correct_only=False):
    if correct_only:
        pool = pool[pool["correct"] == 1]
    if len(pool) == 0:
        raise ValueError("No trials available after filtering.")
    idx = rng.integers(0, len(pool), size=n_trials)
    return pool.iloc[idx].copy()


def summarize_rt(trials, rt_stat, correct_only):
    data = trials[trials["correct"] == 1] if correct_only else trials
    if len(data) == 0:
        return np.nan
    if rt_stat == "mean":
        return float(data["rt_ms"].mean())
    if rt_stat == "median":
        return float(data["rt_ms"].median())
    raise ValueError(f"Unknown rt_stat: {rt_stat}")


def simulate_condition(pool, n_trials, rng, post_shift_ms, rt_stat, correct_only):
    pre = sample_trials(pool, n_trials, rng, correct_only=False)
    post = sample_trials(pool, n_trials, rng, correct_only=False)
    post = post.copy()
    post["rt_ms"] = np.maximum(1.0, post["rt_ms"] + post_shift_ms)

    pre_rt = summarize_rt(pre, rt_stat=rt_stat, correct_only=correct_only)
    post_rt = summarize_rt(post, rt_stat=rt_stat, correct_only=correct_only)
    return {
        "pre_rt_ms": pre_rt,
        "post_rt_ms": post_rt,
        "gain_rt_ms": pre_rt - post_rt,
        "pre_acc": float(pre["correct"].mean()),
        "post_acc": float(post["correct"].mean()),
        "delta_acc": float(post["correct"].mean() - pre["correct"].mean()),
    }


def paired_test(values, null=0.0, alternative="greater"):
    values = np.asarray(values, dtype=float)
    values = values[~np.isnan(values)]
    n = len(values)
    mean = values.mean()
    sd = values.std(ddof=1)
    se = sd / np.sqrt(n)
    df = n - 1
    t = (mean - null) / se
    if alternative == "greater":
        p = 1.0 - stats.t.cdf(t, df)
    elif alternative == "less":
        p = stats.t.cdf(t, df)
    else:
        p = 2.0 * min(stats.t.cdf(t, df), 1.0 - stats.t.cdf(t, df))
    return mean, sd, se, df, t, p


def welch_test(x, y, null=0.0, alternative="greater"):
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    x = x[~np.isnan(x)]
    y = y[~np.isnan(y)]
    diff = x.mean() - y.mean()
    vx = x.var(ddof=1)
    vy = y.var(ddof=1)
    se = np.sqrt(vx / len(x) + vy / len(y))
    df = (vx / len(x) + vy / len(y)) ** 2 / (
        (vx / len(x)) ** 2 / (len(x) - 1) + (vy / len(y)) ** 2 / (len(y) - 1)
    )
    t = (diff - null) / se
    if alternative == "greater":
        p = 1.0 - stats.t.cdf(t, df)
    elif alternative == "less":
        p = stats.t.cdf(t, df)
    else:
        p = 2.0 * min(stats.t.cdf(t, df), 1.0 - stats.t.cdf(t, df))
    return diff, se, df, t, p


def run_one_within(df, n_subj, n_trials, rng, effect_ms, rt_stat, correct_only, acc_margin):
    source_subjects = np.array(sorted(df["subj_idx"].unique()))
    chosen = rng.choice(source_subjects, size=n_subj, replace=True)
    rows = []
    for i, src in enumerate(chosen):
        pool = df[df["subj_idx"] == src]
        self_cond = simulate_condition(
            pool, n_trials, rng, post_shift_ms=0.0, rt_stat=rt_stat, correct_only=correct_only
        )
        ems_cond = simulate_condition(
            pool, n_trials, rng, post_shift_ms=-effect_ms, rt_stat=rt_stat, correct_only=correct_only
        )
        rows.append(
            {
                "sim_subj": i,
                "source_subj": src,
                "gain_self": self_cond["gain_rt_ms"],
                "gain_ems": ems_cond["gain_rt_ms"],
                "gain_diff": ems_cond["gain_rt_ms"] - self_cond["gain_rt_ms"],
                "delta_acc_self": self_cond["delta_acc"],
                "delta_acc_ems": ems_cond["delta_acc"],
                "acc_did": ems_cond["delta_acc"] - self_cond["delta_acc"],
            }
        )
    subj = pd.DataFrame(rows)

    gain_mean, gain_sd, gain_se, gain_df, gain_t, gain_p = paired_test(
        subj["gain_diff"], null=0.0, alternative="greater"
    )
    acc_mean, acc_sd, acc_se, acc_df, acc_t, acc_p = paired_test(
        subj["acc_did"], null=-acc_margin, alternative="greater"
    )
    acc_lower = acc_mean - stats.t.ppf(0.975, acc_df) * acc_se
    return {
        "rt_gain_diff_ms": gain_mean,
        "rt_gain_diff_sd_ms": gain_sd,
        "rt_gain_p_one_sided": gain_p,
        "rt_success": bool(gain_p < 0.05),
        "rt_direction": bool(gain_mean > 0),
        "acc_did": acc_mean,
        "acc_noninf_p": acc_p,
        "acc_noninf_lower_95": acc_lower,
        "acc_noninf_success": bool(acc_p < 0.025 and acc_lower > -acc_margin),
    }, subj


def run_one_between(df, n_subj_per_group, n_trials, rng, effect_ms, rt_stat, correct_only, acc_margin):
    source_subjects = np.array(sorted(df["subj_idx"].unique()))
    self_sources = rng.choice(source_subjects, size=n_subj_per_group, replace=True)
    ems_sources = rng.choice(source_subjects, size=n_subj_per_group, replace=True)

    self_rows = []
    ems_rows = []
    for i, src in enumerate(self_sources):
        cond = simulate_condition(
            df[df["subj_idx"] == src], n_trials, rng, post_shift_ms=0.0,
            rt_stat=rt_stat, correct_only=correct_only,
        )
        self_rows.append({"sim_subj": i, "source_subj": src, "gain": cond["gain_rt_ms"], "delta_acc": cond["delta_acc"]})
    for i, src in enumerate(ems_sources):
        cond = simulate_condition(
            df[df["subj_idx"] == src], n_trials, rng, post_shift_ms=-effect_ms,
            rt_stat=rt_stat, correct_only=correct_only,
        )
        ems_rows.append({"sim_subj": i, "source_subj": src, "gain": cond["gain_rt_ms"], "delta_acc": cond["delta_acc"]})

    self_subj = pd.DataFrame(self_rows)
    ems_subj = pd.DataFrame(ems_rows)
    gain_diff, gain_se, gain_df, gain_t, gain_p = welch_test(
        ems_subj["gain"], self_subj["gain"], null=0.0, alternative="greater"
    )
    acc_diff, acc_se, acc_df, acc_t, acc_p = welch_test(
        ems_subj["delta_acc"], self_subj["delta_acc"], null=-acc_margin, alternative="greater"
    )
    acc_lower = acc_diff - stats.t.ppf(0.975, acc_df) * acc_se
    return {
        "rt_gain_diff_ms": gain_diff,
        "rt_gain_p_one_sided": gain_p,
        "rt_success": bool(gain_p < 0.05),
        "rt_direction": bool(gain_diff > 0),
        "acc_did": acc_diff,
        "acc_noninf_p": acc_p,
        "acc_noninf_lower_95": acc_lower,
        "acc_noninf_success": bool(acc_p < 0.025 and acc_lower > -acc_margin),
    }, pd.concat(
        [self_subj.assign(condition="self"), ems_subj.assign(condition="ems")],
        ignore_index=True,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="pre_experiment_data.csv")
    parser.add_argument("--design", choices=["within", "between"], default="within")
    parser.add_argument("--n-subj", type=int, default=20)
    parser.add_argument("--n-trials", type=int, default=80)
    parser.add_argument("--n-reps", type=int, default=1000)
    parser.add_argument("--effect-ms", type=float, default=8.0)
    parser.add_argument("--rt-stat", choices=["mean", "median"], default="median")
    parser.add_argument("--all-trials", action="store_true", help="Use all trials for RT instead of correct-only.")
    parser.add_argument("--acc-margin", type=float, default=0.03)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--outdir", default="results_resample_pre_experiment_power")
    args = parser.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    df = load_pre_experiment(args.data)
    rng = np.random.default_rng(args.seed)
    correct_only = not args.all_trials

    rows = []
    first_subj = None
    for rep in range(args.n_reps):
        if args.design == "within":
            result, subj = run_one_within(
                df, args.n_subj, args.n_trials, rng, args.effect_ms,
                args.rt_stat, correct_only, args.acc_margin,
            )
        else:
            result, subj = run_one_between(
                df, args.n_subj, args.n_trials, rng, args.effect_ms,
                args.rt_stat, correct_only, args.acc_margin,
            )
        result.update(
            {
                "rep_id": rep,
                "design": args.design,
                "n_subj": args.n_subj,
                "n_trials": args.n_trials,
                "effect_ms": args.effect_ms,
                "rt_stat": args.rt_stat,
                "correct_only": correct_only,
            }
        )
        rows.append(result)
        if rep == 0:
            first_subj = subj
        if (rep + 1) % 100 == 0 or rep + 1 == args.n_reps:
            print(f"Completed {rep + 1}/{args.n_reps} reps")

    results = pd.DataFrame(rows)
    summary = pd.DataFrame(
        [
            {
                "design": args.design,
                "n_subj": args.n_subj,
                "n_trials": args.n_trials,
                "n_reps": args.n_reps,
                "effect_ms": args.effect_ms,
                "rt_stat": args.rt_stat,
                "correct_only": correct_only,
                "rt_gain_diff_mean_ms": results["rt_gain_diff_ms"].mean(),
                "rt_gain_diff_sd_ms": results["rt_gain_diff_ms"].std(),
                "rt_direction_rate": results["rt_direction"].mean(),
                "rt_success_rate": results["rt_success"].mean(),
                "acc_did_mean": results["acc_did"].mean(),
                "acc_noninf_success_rate": results["acc_noninf_success"].mean(),
            }
        ]
    )

    tag = f"{args.design}_n{args.n_subj}_t{args.n_trials}_reps{args.n_reps}_{args.rt_stat}"
    results_path = os.path.join(args.outdir, f"resample_results_{tag}.csv")
    summary_path = os.path.join(args.outdir, f"resample_summary_{tag}.csv")
    first_path = os.path.join(args.outdir, f"resample_rep0_subjects_{tag}.csv")
    results.to_csv(results_path, index=False)
    summary.to_csv(summary_path, index=False)
    if first_subj is not None:
        first_subj.to_csv(first_path, index=False)

    print("\nPre-experiment source summary:")
    print(
        df.groupby("subj_idx")
        .agg(rt_mean_ms=("rt_ms", "mean"), rt_sd_ms=("rt_ms", "std"), acc=("correct", "mean"), n=("rt_ms", "count"))
        .round(3)
        .to_string()
    )
    print("\nPower summary:")
    print(summary.round(4).to_string(index=False))
    print("\nFiles written:")
    print(f"  {results_path}")
    print(f"  {summary_path}")
    print(f"  {first_path}")


if __name__ == "__main__":
    main()
