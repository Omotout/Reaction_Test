"""
Quick design grid for the pre-post behavioral main analysis.

This reuses 07_prepost_behavioral_power.py and evaluates RT gain power across
sample sizes, trials per session, and assumed EMS post t shortening.
"""

import argparse
import importlib.util
import os
from itertools import product

import pandas as pd


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


def run_cell(n_subj, n_trials, t_delta_ms, n_reps, seed_offset, acc_margin):
    rows = []
    for rep in range(n_reps):
        rep_id = seed_offset + rep
        df = prepost.simulate_prepost(
            n_subj_per_group=n_subj,
            n_trials=n_trials,
            seed=rep_id,
            ems_post_t_delta_ms=t_delta_ms,
            self_post_t_delta_ms=0.0,
        )
        result, *_ = prepost.analyze_one(df, acc_margin=acc_margin)
        rows.append(result)

    df = pd.DataFrame(rows)
    return {
        "n_subj": n_subj,
        "n_trials": n_trials,
        "n_reps": n_reps,
        "ems_post_t_delta_ms": t_delta_ms,
        "rt_did_mean_ms": df["rt_did_ms"].mean(),
        "rt_did_sd_ms": df["rt_did_ms"].std(),
        "rt_direction_rate": (df["rt_did_ms"] < 0).mean(),
        "rt_success_rate": df["rt_success"].mean(),
        "acc_noninf_success_rate": df["acc_noninf_success"].mean(),
        "both_success_rate": df["both_success"].mean(),
    }


def parse_list(value, cast):
    return [cast(x.strip()) for x in value.split(",") if x.strip()]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n-subj-list", default="20,25,30,40")
    parser.add_argument("--n-trials-list", default="80,120")
    parser.add_argument("--t-delta-list", default="-8,-10,-12")
    parser.add_argument("--n-reps", type=int, default=100)
    parser.add_argument("--seed-offset", type=int, default=0)
    parser.add_argument("--acc-margin", type=float, default=0.03)
    parser.add_argument("--outdir", default="results_prepost_behavioral_design_grid")
    args = parser.parse_args()

    os.makedirs(args.outdir, exist_ok=True)

    n_subj_list = parse_list(args.n_subj_list, int)
    n_trials_list = parse_list(args.n_trials_list, int)
    t_delta_list = parse_list(args.t_delta_list, float)

    rows = []
    cells = list(product(n_subj_list, n_trials_list, t_delta_list))
    for i, (n_subj, n_trials, t_delta_ms) in enumerate(cells, start=1):
        print(
            f"Cell {i}/{len(cells)}: n={n_subj}/group, "
            f"trials={n_trials}/phase, t_delta={t_delta_ms} ms"
        )
        rows.append(
            run_cell(
                n_subj=n_subj,
                n_trials=n_trials,
                t_delta_ms=t_delta_ms,
                n_reps=args.n_reps,
                seed_offset=args.seed_offset,
                acc_margin=args.acc_margin,
            )
        )

    summary = pd.DataFrame(rows).sort_values(
        ["ems_post_t_delta_ms", "n_trials", "n_subj"]
    )
    path = os.path.join(args.outdir, "prepost_behavioral_design_grid.csv")
    summary.to_csv(path, index=False)

    print("\nSummary:")
    print(summary.round(3).to_string(index=False))
    print(f"\nWrote: {path}")


if __name__ == "__main__":
    main()
