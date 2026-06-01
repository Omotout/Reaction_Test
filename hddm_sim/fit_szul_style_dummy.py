"""
Fit one dummy-data HDDM run and report Szul et al.-style descriptive metrics.

The script is intentionally for reporting/inspection, not for replacing the
power grid. It generates one simulated Control/EMS dataset, fits HDDM, and
computes empirical ROPEs from odd-vs-even posterior samples within each
condition, following Szul et al. (2020).

Primary ROPE/P(P|D) definition here:
1. Split each condition's posterior chain into odd and even samples.
2. Compute the odd-even difference distribution within each condition.
3. Compute each condition's 95% HDI of that within-chain difference.
4. Use the widest lower/upper bounds across the two conditions as the ROPE.
5. P(P|D) is the proportion of the between-condition 95% HDI that falls inside
   that empirical ROPE.
"""

import argparse
import importlib.util
import os
import sys
import time
import warnings

import hddm
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from utils import hdi


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location(
    "sim_data", os.path.join(os.path.dirname(os.path.abspath(__file__)), "01_simulate_data.py")
)
sim_data = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sim_data)


PARAM_NODES = {
    "a": ("a(control)", "a(ems)"),
    "v": ("v(control)", "v(ems)"),
    "t": ("t(control)", "t(ems)"),
}


def same_chain_diff(samples):
    n = len(samples) - (len(samples) % 2)
    even = samples[:n:2]
    odd = samples[1:n:2]
    return odd - even


def condition_chain_rope(samples):
    return hdi(same_chain_diff(samples), prob=0.95)


def empirical_rope(samples_control, samples_ems):
    ctrl_low, ctrl_high = hdi(same_chain_diff(samples_control), prob=0.95)
    ems_low, ems_high = hdi(same_chain_diff(samples_ems), prob=0.95)
    return {
        "control_rope_low": float(ctrl_low),
        "control_rope_high": float(ctrl_high),
        "ems_rope_low": float(ems_low),
        "ems_rope_high": float(ems_high),
        "paper_rope_low": float(min(ctrl_low, ems_low)),
        "paper_rope_high": float(max(ctrl_high, ems_high)),
    }


def p_pd_from_hdi_and_rope(hdi_low, hdi_high, rope_low, rope_high):
    """Szul-style P(P|D): proportion of the 95% HDI inside the ROPE."""
    hdi_width = hdi_high - hdi_low
    if hdi_width <= 0:
        return 0.0

    overlap_low = max(hdi_low, rope_low)
    overlap_high = min(hdi_high, rope_high)
    if overlap_high <= overlap_low:
        return 0.0
    return float((overlap_high - overlap_low) / hdi_width)


def summarize_param(param, ctrl, ems):
    diff = ems - ctrl
    hdi_low, hdi_high = hdi(diff, prob=0.95)
    rope = empirical_rope(ctrl, ems)
    rope_low = rope["paper_rope_low"]
    rope_high = rope["paper_rope_high"]
    in_rope_prob = float(((diff >= rope_low) & (diff <= rope_high)).mean())

    p_pd_empirical_rope = p_pd_from_hdi_and_rope(hdi_low, hdi_high, rope_low, rope_high)

    if param in ("a", "v"):
        fixed_rope_low = -0.10
        fixed_rope_high = 0.10
    else:
        fixed_rope_low = -0.02
        fixed_rope_high = 0.02

    fixed_in_rope_prob = float(((diff >= fixed_rope_low) & (diff <= fixed_rope_high)).mean())

    return {
        "param": param,
        "ctrl_mean": float(ctrl.mean()),
        "ems_mean": float(ems.mean()),
        "diff_mean": float(diff.mean()),
        "diff_sd": float(diff.std()),
        "hdi_low": float(hdi_low),
        "hdi_high": float(hdi_high),
        **rope,
        "prob_posterior_samples_in_paper_rope": in_rope_prob,
        "p_pd": p_pd_empirical_rope,
        "p_pd_empirical_rope": p_pd_empirical_rope,
        "prob_diff_in_fixed_rope": fixed_in_rope_prob,
        "fixed_rope_low": fixed_rope_low,
        "fixed_rope_high": fixed_rope_high,
    }


def plot_param(param, diff, rope_low, rope_high, hdi_low, hdi_high, out_path):
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.hist(diff, bins=40, density=True, color="#708d81", alpha=0.75)
    ax.axvspan(rope_low, rope_high, color="#d9a441", alpha=0.25, label="Empirical ROPE")
    ax.axvline(hdi_low, color="#333333", linestyle="--", linewidth=1.0, label="95% HDI")
    ax.axvline(hdi_high, color="#333333", linestyle="--", linewidth=1.0)
    ax.axvline(0, color="black", linewidth=0.8)
    ax.set_title(f"Posterior difference: {param}(EMS) - {param}(Control)")
    ax.set_xlabel("Posterior difference")
    ax.set_ylabel("Density")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(out_path, dpi=180)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n-subj", type=int, default=20, help="Subjects per group.")
    parser.add_argument("--n-trials", type=int, default=80, help="Trials per subject.")
    parser.add_argument("--rep-id", type=int, default=0)
    parser.add_argument("--samples", type=int, default=5000)
    parser.add_argument("--burn", type=int, default=2000)
    parser.add_argument("--thin", type=int, default=2)
    parser.add_argument("--outdir", default="results_szul_style_dummy")
    args = parser.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    seed = args.rep_id * 1000

    print("=" * 70)
    print("Szul-style HDDM check on dummy data")
    print("=" * 70)
    print(f"n_subj_per_group={args.n_subj}, n_trials={args.n_trials}, rep_id={args.rep_id}")

    df = sim_data.simulate_two_groups(args.n_subj, args.n_trials, seed=seed)
    data_path = os.path.join(args.outdir, "dummy_data.csv")
    df.to_csv(data_path, index=False)

    observed = (
        df.groupby("condition")
        .agg(mean_rt_ms=("rt", lambda x: x.mean() * 1000.0),
             accuracy=("response", "mean"),
             n_trials=("rt", "count"),
             n_subj=("subj_idx", "nunique"))
        .reset_index()
    )
    observed.to_csv(os.path.join(args.outdir, "observed_behavior.csv"), index=False)
    print()
    print("Observed behavior:")
    print(observed.round(4).to_string(index=False))

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = hddm.HDDM(
            df,
            depends_on={"a": "condition", "v": "condition", "t": "condition"},
            include=["a", "v", "t"],
            p_outlier=0.05,
        )
        model.find_starting_values()
        t0 = time.time()
        model.sample(args.samples, burn=args.burn, thin=args.thin, dbname=None, db="ram")
        elapsed = time.time() - t0

    rows = []
    posterior_rows = {}
    for param, (ctrl_node, ems_node) in PARAM_NODES.items():
        ctrl = model.nodes_db.node[ctrl_node].trace()
        ems = model.nodes_db.node[ems_node].trace()
        diff = ems - ctrl
        row = summarize_param(param, ctrl, ems)
        rows.append(row)
        posterior_rows[f"{param}_ctrl"] = ctrl
        posterior_rows[f"{param}_ems"] = ems
        posterior_rows[f"{param}_diff"] = diff
        plot_param(
            param,
            diff,
            row["paper_rope_low"],
            row["paper_rope_high"],
            row["hdi_low"],
            row["hdi_high"],
            os.path.join(args.outdir, f"{param}_diff_empirical_rope.png"),
        )

    summary = pd.DataFrame(rows)
    summary_path = os.path.join(args.outdir, "szul_style_summary.csv")
    posterior_path = os.path.join(args.outdir, "posterior_samples.csv")
    summary.to_csv(summary_path, index=False)
    pd.DataFrame(posterior_rows).to_csv(posterior_path, index=False)

    print()
    print(f"HDDM fit time: {elapsed:.1f}s")
    print()
    print("Szul-style summary:")
    display_cols = [
        "param",
        "diff_mean",
        "hdi_low",
        "hdi_high",
        "paper_rope_low",
        "paper_rope_high",
        "p_pd",
        "prob_posterior_samples_in_paper_rope",
    ]
    print(summary[display_cols].round(4).to_string(index=False))
    print()
    print(f"Wrote: {summary_path}")
    print(f"Wrote: {posterior_path}")
    print(f"Wrote: {data_path}")


if __name__ == "__main__":
    main()
