"""
Generate dummy data directly from generic HDDM parameters fit to TestData.

Prerequisite:
  python fit_testdata_direct_ddm.py
"""

import argparse
import json
import os

import hddm
import numpy as np
import pandas as pd


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def load_summary(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def simulate_group(base, var, n_subj, n_trials, seed, t_delta=0.0):
    rng = np.random.default_rng(seed)
    rows = []
    for subj_idx in range(n_subj):
        params = {
            "a": max(0.3, rng.normal(base["a"], var["a_sd"])),
            "v": rng.normal(base["v"], var["v_sd"]),
            "t": max(0.05, rng.normal(base["t"] + t_delta, var["t_sd"])),
            "z": 0.5,
        }
        data, _ = hddm.generate.gen_rand_data(
            params,
            size=n_trials,
            subjs=1,
            subj_noise=0.0,
            seed=int(rng.integers(0, 1_000_000_000)),
        )
        if "condition" in data.columns:
            data = data.drop(columns=["condition"])
        data["subj_idx"] = subj_idx
        rows.append(data)
    return pd.concat(rows, ignore_index=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", default="testdata_direct_ddm_summary.json")
    parser.add_argument("--n-subj", type=int, default=20)
    parser.add_argument("--n-trials", type=int, default=80)
    parser.add_argument("--t-delta-ms", type=float, default=-10.0)
    parser.add_argument("--n-seeds", type=int, default=60)
    parser.add_argument("--outdir", default="results_testdata_direct_dummy")
    args = parser.parse_args()

    summary_path = args.summary
    if not os.path.isabs(summary_path):
        summary_path = os.path.join(SCRIPT_DIR, summary_path)
    summary = load_summary(summary_path)

    base = {
        "a": summary["empirical_means"]["a"],
        "v": summary["empirical_means"]["v"],
        "t": summary["empirical_means"]["t"],
    }
    var = summary["empirical_subj_var"]
    t_delta = args.t_delta_ms / 1000.0

    os.makedirs(args.outdir, exist_ok=True)

    seed_rows = []
    for seed in range(args.n_seeds):
        ctrl = simulate_group(base, var, args.n_subj, args.n_trials, seed=seed * 2, t_delta=0.0)
        ems = simulate_group(base, var, args.n_subj, args.n_trials, seed=seed * 2 + 1, t_delta=t_delta)
        ctrl["condition"] = "control"
        ems["condition"] = "ems"
        ems["subj_idx"] = ems["subj_idx"] + args.n_subj
        df = pd.concat([ctrl, ems], ignore_index=True)
        cond = df.groupby("condition").agg(acc=("response", "mean"), rt=("rt", "mean"))
        seed_rows.append(
            {
                "seed": seed,
                "ctrl_acc": cond.loc["control", "acc"],
                "ems_acc": cond.loc["ems", "acc"],
                "acc_diff": cond.loc["ems", "acc"] - cond.loc["control", "acc"],
                "ctrl_rt_ms": cond.loc["control", "rt"] * 1000,
                "ems_rt_ms": cond.loc["ems", "rt"] * 1000,
                "rt_diff_ms": (cond.loc["ems", "rt"] - cond.loc["control", "rt"]) * 1000,
            }
        )
        if seed == 0:
            df.to_csv(os.path.join(args.outdir, "dummy_data_seed0.csv"), index=False)

    seed_df = pd.DataFrame(seed_rows)
    seed_df.to_csv(os.path.join(args.outdir, "seed_behavior_summary.csv"), index=False)

    print("=" * 72)
    print("Dummy data from direct TestData DDM parameters")
    print("=" * 72)
    print("Source parameters:")
    print(f"  a={base['a']:.4f}, v={base['v']:.4f}, t={base['t']:.4f}")
    print(f"  a_sd={var['a_sd']:.4f}, v_sd={var['v_sd']:.4f}, t_sd={var['t_sd']:.4f}")
    print(f"  EMS t_delta={args.t_delta_ms:.1f} ms")
    print()
    print("Across seeds:")
    cols = ["ctrl_acc", "ems_acc", "acc_diff", "ctrl_rt_ms", "ems_rt_ms", "rt_diff_ms"]
    print(seed_df[cols].mean().round(4).to_string())
    print("\nSD across seeds:")
    print(seed_df[cols].std().round(4).to_string())
    print()
    print(f"Wrote: {os.path.join(args.outdir, 'seed_behavior_summary.csv')}")
    print(f"Wrote: {os.path.join(args.outdir, 'dummy_data_seed0.csv')}")


if __name__ == "__main__":
    main()
