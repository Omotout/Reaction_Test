"""
Visualize how practical changes in boundary separation a affect RT and accuracy.

This script varies the group-level a parameter around the calibrated baseline
while holding v, t, and z fixed. Values supplied by --deltas are on the same
HDDM scale used by utils.TRUE_PARAMS. No sqrt(2) scale correction is applied.
"""

import argparse
import os

import hddm
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from utils import SUBJ_VAR, TRUE_PARAMS


def parse_deltas(value):
    return [float(x.strip()) for x in value.split(",") if x.strip()]


def simulate_variant(delta_a, n_subjects, n_trials, reps, seed):
    rng = np.random.default_rng(seed)
    base_sim = TRUE_PARAMS["control"]

    rows = []
    for rep in range(reps):
        rep_seed = int(rng.integers(0, 1_000_000_000))
        rep_rng = np.random.default_rng(rep_seed)

        subj_rows = []
        for subj_idx in range(n_subjects):
            subj_a = rep_rng.normal(
                base_sim["a"] + delta_a,
                SUBJ_VAR["a_sd"],
            )
            subj_v = rep_rng.normal(base_sim["v"], SUBJ_VAR["v_sd"])
            subj_t = rep_rng.normal(base_sim["t"], SUBJ_VAR["t_sd"])
            params = {
                "a": max(0.3, subj_a),
                "v": subj_v,
                "t": max(0.05, subj_t),
                "z": base_sim["z"],
            }
            data, _ = hddm.generate.gen_rand_data(
                params,
                size=n_trials,
                subjs=1,
                subj_noise=0.0,
            )
            data["subj_idx"] = subj_idx
            subj_rows.append(data[["rt", "response", "subj_idx"]])

        df = pd.concat(subj_rows, ignore_index=True)
        rows.append(
            {
                "delta_a_report": delta_a,
                "a": base_sim["a"] + delta_a,
                "rep": rep,
                "mean_rt_ms": df["rt"].mean() * 1000.0,
                "median_rt_ms": df["rt"].median() * 1000.0,
                "accuracy": df["response"].mean(),
                "n_subjects": n_subjects,
                "n_trials_per_subject": n_trials,
                "n_trials_total": len(df),
            }
        )

    return rows


def summarize(raw_df):
    summary = (
        raw_df.groupby(["delta_a_report", "a"])
        .agg(
            mean_rt_ms=("mean_rt_ms", "mean"),
            mean_rt_ms_sd=("mean_rt_ms", "std"),
            median_rt_ms=("median_rt_ms", "mean"),
            accuracy=("accuracy", "mean"),
            accuracy_sd=("accuracy", "std"),
            reps=("rep", "count"),
        )
        .reset_index()
        .sort_values("delta_a_report")
    )

    baseline = summary.loc[summary["delta_a_report"].abs().idxmin()]
    summary["mean_rt_ms_diff_from_baseline"] = (
        summary["mean_rt_ms"] - baseline["mean_rt_ms"]
    )
    summary["accuracy_diff_from_baseline"] = summary["accuracy"] - baseline["accuracy"]
    return summary


def plot_summary(summary, out_png):
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5), constrained_layout=True)

    x = summary["delta_a_report"]

    axes[0].errorbar(
        x,
        summary["mean_rt_ms_diff_from_baseline"],
        yerr=summary["mean_rt_ms_sd"],
        marker="o",
        color="#2f6f73",
        capsize=3,
    )
    axes[0].axhline(0, color="black", linewidth=0.8)
    axes[0].axvline(-0.10, color="#777777", linestyle="--", linewidth=0.9)
    axes[0].axvline(0.10, color="#777777", linestyle="--", linewidth=0.9)
    axes[0].axvline(-0.15, color="#aaaaaa", linestyle=":", linewidth=0.9)
    axes[0].axvline(0.15, color="#aaaaaa", linestyle=":", linewidth=0.9)
    axes[0].set_xlabel("Delta a on reported scale")
    axes[0].set_ylabel("Mean RT change from baseline (ms)")
    axes[0].set_title("Boundary a vs RT")

    axes[1].errorbar(
        x,
        summary["accuracy_diff_from_baseline"] * 100.0,
        yerr=summary["accuracy_sd"] * 100.0,
        marker="o",
        color="#8b4f39",
        capsize=3,
    )
    axes[1].axhline(0, color="black", linewidth=0.8)
    axes[1].axvline(-0.10, color="#777777", linestyle="--", linewidth=0.9, label="+/-0.10")
    axes[1].axvline(0.10, color="#777777", linestyle="--", linewidth=0.9)
    axes[1].axvline(-0.15, color="#aaaaaa", linestyle=":", linewidth=0.9, label="+/-0.15")
    axes[1].axvline(0.15, color="#aaaaaa", linestyle=":", linewidth=0.9)
    axes[1].set_xlabel("Delta a on reported scale")
    axes[1].set_ylabel("Accuracy change from baseline (percentage points)")
    axes[1].set_title("Boundary a vs accuracy")
    axes[1].legend(frameon=False)

    fig.suptitle("Outcome impact of ROPE candidates for boundary separation a")
    fig.savefig(out_png, dpi=200)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--outdir", default="results_a_rope_impact")
    parser.add_argument(
        "--deltas",
        default="-0.15,-0.10,-0.05,0,0.05,0.10,0.15",
        help="Comma-separated delta-a values on the HDDM scale used by TRUE_PARAMS.",
    )
    parser.add_argument("--n-subjects", type=int, default=20)
    parser.add_argument("--n-trials", type=int, default=200)
    parser.add_argument("--reps", type=int, default=20)
    parser.add_argument("--seed", type=int, default=20260501)
    args = parser.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    deltas = parse_deltas(args.deltas)

    all_rows = []
    for delta in deltas:
        print(f"Simulating delta_a_report={delta:+.3f}")
        all_rows.extend(
            simulate_variant(
                delta_a=delta,
                n_subjects=args.n_subjects,
                n_trials=args.n_trials,
                reps=args.reps,
                seed=args.seed + int(round((delta + 1.0) * 1000)),
            )
        )

    raw_df = pd.DataFrame(all_rows)
    summary = summarize(raw_df)

    raw_csv = os.path.join(args.outdir, "a_rope_impact_raw.csv")
    summary_csv = os.path.join(args.outdir, "a_rope_impact_summary.csv")
    plot_png = os.path.join(args.outdir, "a_rope_impact.png")

    raw_df.to_csv(raw_csv, index=False)
    summary.to_csv(summary_csv, index=False)
    plot_summary(summary, plot_png)

    print()
    print("Baseline calibrated control parameters:")
    print(
        f"  a={TRUE_PARAMS['control']['a']:.3f}, "
        f"v={TRUE_PARAMS['control']['v']:.3f}, "
        f"t={TRUE_PARAMS['control']['t']:.3f}"
    )
    print()
    print("Summary:")
    cols = [
        "delta_a_report",
        "a",
        "mean_rt_ms",
        "mean_rt_ms_diff_from_baseline",
        "accuracy",
        "accuracy_diff_from_baseline",
    ]
    print(summary[cols].round(4).to_string(index=False))
    print()
    print(f"Wrote: {summary_csv}")
    print(f"Wrote: {raw_csv}")
    print(f"Wrote: {plot_png}")


if __name__ == "__main__":
    main()
