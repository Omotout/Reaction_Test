"""
Final dummy-data HDDM check for the planned design.

Outputs:
- observed behavior by condition
- fixed ROPE + HDI decision for a
- Szul-style empirical ROPE and P(P|D)
- accuracy non-inferiority test
- posterior estimate for delta t = t(EMS) - t(Control)
"""

import argparse
import importlib.util
import os
import sys
import time
import warnings

import hddm
import numpy as np
import pandas as pd

from utils import ROPE, accuracy_noninferiority, hdi, rope_decision
from fit_szul_style_dummy import empirical_rope, p_pd_from_hdi_and_rope


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


def summarize_difference(param, ctrl, ems):
    diff = ems - ctrl
    hdi_low, hdi_high = hdi(diff, prob=0.95)
    paper_rope = empirical_rope(ctrl, ems)
    p_pd = p_pd_from_hdi_and_rope(
        hdi_low,
        hdi_high,
        paper_rope["paper_rope_low"],
        paper_rope["paper_rope_high"],
    )

    row = {
        "param": param,
        "ctrl_mean": float(ctrl.mean()),
        "ems_mean": float(ems.mean()),
        "diff_mean": float(diff.mean()),
        "diff_sd": float(diff.std()),
        "hdi_low": float(hdi_low),
        "hdi_high": float(hdi_high),
        "paper_rope_low": paper_rope["paper_rope_low"],
        "paper_rope_high": paper_rope["paper_rope_high"],
        "p_pd": float(p_pd),
    }

    if param in ROPE:
        row["fixed_rope_low"] = ROPE[param][0]
        row["fixed_rope_high"] = ROPE[param][1]
        row["fixed_rope_decision"] = rope_decision(diff, *ROPE[param])
        row["prob_in_fixed_rope"] = float(((diff >= ROPE[param][0]) & (diff <= ROPE[param][1])).mean())
    else:
        row["fixed_rope_low"] = np.nan
        row["fixed_rope_high"] = np.nan
        row["fixed_rope_decision"] = ""
        row["prob_in_fixed_rope"] = np.nan

    return row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n-subj", type=int, default=20, help="Subjects per group.")
    parser.add_argument("--n-trials", type=int, default=80, help="Trials per subject.")
    parser.add_argument("--rep-id", type=int, default=0)
    parser.add_argument("--samples", type=int, default=2000)
    parser.add_argument("--burn", type=int, default=1000)
    parser.add_argument("--thin", type=int, default=2)
    parser.add_argument("--outdir", default="results_final_dummy_analysis")
    args = parser.parse_args()

    os.makedirs(args.outdir, exist_ok=True)

    print("=" * 72)
    print("Final dummy-data analysis")
    print("=" * 72)
    print(
        f"n_subj_per_group={args.n_subj}, n_trials={args.n_trials}, "
        f"rep_id={args.rep_id}, samples={args.samples}, burn={args.burn}, thin={args.thin}"
    )

    df = sim_data.simulate_two_groups(args.n_subj, args.n_trials, seed=args.rep_id)
    df.to_csv(os.path.join(args.outdir, "dummy_data.csv"), index=False)

    observed = (
        df.groupby("condition")
        .agg(
            mean_rt_ms=("rt", lambda x: x.mean() * 1000.0),
            median_rt_ms=("rt", lambda x: x.median() * 1000.0),
            accuracy=("response", "mean"),
            n_trials=("rt", "count"),
            n_subj=("subj_idx", "nunique"),
        )
        .reset_index()
    )
    observed.to_csv(os.path.join(args.outdir, "observed_behavior.csv"), index=False)

    acc_ctrl = df.loc[df["condition"] == "control", "response"].mean()
    acc_ems = df.loc[df["condition"] == "ems", "response"].mean()
    n_ctrl = int((df["condition"] == "control").sum())
    n_ems = int((df["condition"] == "ems").sum())
    acc_noninf = accuracy_noninferiority(
        acc_ems,
        acc_ctrl,
        n_ems,
        n_ctrl,
        margin=0.03,
        alpha=0.025,
    )
    acc_summary = pd.DataFrame(
        [
            {
                "acc_ctrl": acc_ctrl,
                "acc_ems": acc_ems,
                "acc_diff": acc_noninf["diff"],
                "margin": -0.03,
                "z": acc_noninf["z"],
                "p_value": acc_noninf["p_value"],
                "ci_lower_95": acc_noninf["ci_lower"],
                "noninferior": acc_noninf["noninferior"],
            }
        ]
    )
    acc_summary.to_csv(os.path.join(args.outdir, "accuracy_noninferiority.csv"), index=False)

    print("\nObserved behavior:")
    print(observed.round(4).to_string(index=False))
    print("\nAccuracy non-inferiority:")
    print(acc_summary.round(5).to_string(index=False))

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
    posterior = {}
    for param, (ctrl_node, ems_node) in PARAM_NODES.items():
        ctrl = model.nodes_db.node[ctrl_node].trace()
        ems = model.nodes_db.node[ems_node].trace()
        diff = ems - ctrl
        rows.append(summarize_difference(param, ctrl, ems))
        posterior[f"{param}_ctrl"] = ctrl
        posterior[f"{param}_ems"] = ems
        posterior[f"{param}_diff"] = diff

    hddm_summary = pd.DataFrame(rows)
    hddm_summary.to_csv(os.path.join(args.outdir, "hddm_difference_summary.csv"), index=False)
    pd.DataFrame(posterior).to_csv(os.path.join(args.outdir, "posterior_samples.csv"), index=False)

    print(f"\nHDDM fit time: {elapsed:.1f}s")
    print("\nHDDM difference summary:")
    display_cols = [
        "param",
        "diff_mean",
        "hdi_low",
        "hdi_high",
        "fixed_rope_low",
        "fixed_rope_high",
        "fixed_rope_decision",
        "paper_rope_low",
        "paper_rope_high",
        "p_pd",
    ]
    print(hddm_summary[display_cols].round(5).to_string(index=False))

    print("\nKey files:")
    print(f"  {os.path.join(args.outdir, 'observed_behavior.csv')}")
    print(f"  {os.path.join(args.outdir, 'accuracy_noninferiority.csv')}")
    print(f"  {os.path.join(args.outdir, 'hddm_difference_summary.csv')}")
    print(f"  {os.path.join(args.outdir, 'posterior_samples.csv')}")


if __name__ == "__main__":
    main()
