"""
Plot trial-wise mean correct RT trajectory for pre-experiment data.

Y-axis: mean RT over subjects who were correct on that trial.
X-axis: trial index.
Incorrect trials are excluded from each trial-wise mean.
"""

import argparse
import os

import matplotlib.pyplot as plt
import pandas as pd


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="pre_experiment_data.csv")
    parser.add_argument("--outdir", default="results_pre_experiment_trajectory")
    parser.add_argument("--rolling", type=int, default=5, help="Rolling window for smoothed line.")
    args = parser.parse_args()

    os.makedirs(args.outdir, exist_ok=True)

    df = pd.read_csv(args.data)
    df = df.copy()
    df["trial_idx"] = df.groupby("subj_idx").cumcount() + 1
    df["correct"] = pd.to_numeric(df["response"], errors="coerce").astype(int)
    df["rt_ms"] = pd.to_numeric(df["rt"], errors="coerce") * 1000.0

    correct = df[df["correct"] == 1].copy()
    summary = (
        correct.groupby("trial_idx", as_index=False)
        .agg(
            mean_correct_rt_ms=("rt_ms", "mean"),
            sd_correct_rt_ms=("rt_ms", "std"),
            n_correct_subjects=("subj_idx", "nunique"),
        )
        .sort_values("trial_idx")
    )
    summary["sem_correct_rt_ms"] = summary["sd_correct_rt_ms"] / summary["n_correct_subjects"] ** 0.5
    summary["rolling_mean_correct_rt_ms"] = (
        summary["mean_correct_rt_ms"]
        .rolling(window=args.rolling, center=True, min_periods=1)
        .mean()
    )

    summary_path = os.path.join(args.outdir, "pre_experiment_trialwise_correct_rt.csv")
    fig_path = os.path.join(args.outdir, "pre_experiment_trialwise_correct_rt.png")
    summary.to_csv(summary_path, index=False)

    plt.figure(figsize=(10, 5))
    plt.plot(
        summary["trial_idx"],
        summary["mean_correct_rt_ms"],
        color="#7a7a7a",
        linewidth=1.0,
        alpha=0.55,
        label="Trial-wise mean",
    )
    plt.plot(
        summary["trial_idx"],
        summary["rolling_mean_correct_rt_ms"],
        color="#1f77b4",
        linewidth=2.2,
        label=f"{args.rolling}-trial rolling mean",
    )
    plt.fill_between(
        summary["trial_idx"],
        summary["mean_correct_rt_ms"] - summary["sem_correct_rt_ms"],
        summary["mean_correct_rt_ms"] + summary["sem_correct_rt_ms"],
        color="#1f77b4",
        alpha=0.12,
        linewidth=0,
        label="SEM",
    )
    plt.axvline(40.5, color="#d62728", linestyle="--", linewidth=1.2, alpha=0.8, label="Halfway")
    plt.xlabel("Trial number")
    plt.ylabel("Mean correct RT across subjects (ms)")
    plt.title("Pre-experiment correct RT trajectory")
    plt.xlim(summary["trial_idx"].min(), summary["trial_idx"].max())
    plt.grid(True, axis="y", alpha=0.25)
    plt.legend(frameon=False)
    plt.tight_layout()
    plt.savefig(fig_path, dpi=180)
    plt.close()

    first_half = correct[correct["trial_idx"] <= 40]["rt_ms"].mean()
    second_half = correct[correct["trial_idx"] > 40]["rt_ms"].mean()

    print(f"Subjects: {df['subj_idx'].nunique()}")
    print(f"Trials per subject max: {df['trial_idx'].max()}")
    print(f"Correct trials: {len(correct)}/{len(df)}")
    print(f"First half correct RT mean: {first_half:.2f} ms")
    print(f"Second half correct RT mean: {second_half:.2f} ms")
    print(f"Wrote: {summary_path}")
    print(f"Wrote: {fig_path}")


if __name__ == "__main__":
    main()
