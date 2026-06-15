"""
Repeated behavioral power check for the dummy-data design.

Runs 05_analyze_behavioral_effects.py-style subject-level tests across many
simulated replications. This is independent of HDDM fitting and is intended to
check the main behavioral claims:
- RT shortening detection rate.
- Accuracy non-inferiority detection rate.
"""

import argparse
import importlib.util
import os

import pandas as pd


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(SCRIPT_DIR, filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


behavior = load_module("behavior", "05_analyze_behavioral_effects.py")
sim_data = load_module("sim_data", "01_simulate_data.py")


def run_one(rep_id, n_subj, n_trials, acc_margin, alpha_rt, alpha_noninf):
    df = sim_data.simulate_two_groups(
        n_subj_per_group=n_subj,
        n_trials=n_trials,
        seed=rep_id,
    )
    df["condition"] = df["condition"].astype(str)
    df["rt_ms"] = behavior.infer_rt_ms(df["rt"], "s")
    df = behavior.add_correct_column(
        df,
        response_col="response",
        stim_col="stim",
        correct_col=None,
    )
    subj = behavior.subject_summary(df)
    tests, paired = behavior.analyze_subject_level(
        subj,
        control_label="control",
        ems_label="ems",
        acc_margin=acc_margin,
        alpha_rt=alpha_rt,
        alpha_noninf=alpha_noninf,
    )

    rt = tests[tests["outcome"] == "mean_rt_ms"].iloc[0].to_dict()
    acc = tests[tests["outcome"] == "accuracy"].iloc[0].to_dict()
    trial = behavior.trial_summary(df).set_index("condition")

    return {
        "rep_id": rep_id,
        "n_subj": n_subj,
        "n_trials": n_trials,
        "paired_design": paired,
        "rt_ctrl_ms": trial.loc["control", "mean_rt_ms"],
        "rt_ems_ms": trial.loc["ems", "mean_rt_ms"],
        "rt_diff_ms": rt["diff_ems_minus_control"],
        "rt_p_one_sided": rt["p_value_one_sided"],
        "rt_significant": rt["significant"],
        "rt_ci_low": rt["ci_95_low"],
        "rt_ci_high": rt["ci_95_high"],
        "acc_ctrl": trial.loc["control", "accuracy"],
        "acc_ems": trial.loc["ems", "accuracy"],
        "acc_diff": acc["diff_ems_minus_control"],
        "acc_noninferiority_p": acc["p_value_one_sided"],
        "acc_noninferior": acc["significant"],
        "acc_ci_low": acc["ci_95_low"],
        "acc_ci_high": acc["ci_95_high"],
        "both_success": bool(rt["significant"] and acc["significant"]),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n-subj", type=int, default=20)
    parser.add_argument("--n-trials", type=int, default=80)
    parser.add_argument("--n-reps", type=int, default=100)
    parser.add_argument("--seed-offset", type=int, default=0)
    parser.add_argument("--acc-margin", type=float, default=0.03)
    parser.add_argument("--alpha-rt", type=float, default=0.05)
    parser.add_argument("--alpha-noninf", type=float, default=0.025)
    parser.add_argument("--outdir", type=str, default="results_behavioral_power")
    args = parser.parse_args()

    os.makedirs(args.outdir, exist_ok=True)

    rows = []
    for i in range(args.n_reps):
        rep_id = args.seed_offset + i
        rows.append(
            run_one(
                rep_id=rep_id,
                n_subj=args.n_subj,
                n_trials=args.n_trials,
                acc_margin=args.acc_margin,
                alpha_rt=args.alpha_rt,
                alpha_noninf=args.alpha_noninf,
            )
        )
        if (i + 1) % 10 == 0 or (i + 1) == args.n_reps:
            print(f"Completed {i + 1}/{args.n_reps} reps")

    results = pd.DataFrame(rows)
    summary = pd.DataFrame(
        [
            {
                "n_subj": args.n_subj,
                "n_trials": args.n_trials,
                "n_reps": args.n_reps,
                "rt_diff_mean_ms": results["rt_diff_ms"].mean(),
                "rt_diff_sd_ms": results["rt_diff_ms"].std(),
                "rt_significant_rate": results["rt_significant"].mean(),
                "rt_direction_rate": (results["rt_diff_ms"] < 0).mean(),
                "acc_diff_mean": results["acc_diff"].mean(),
                "acc_diff_sd": results["acc_diff"].std(),
                "acc_noninferiority_rate": results["acc_noninferior"].mean(),
                "both_success_rate": results["both_success"].mean(),
            }
        ]
    )

    results_path = os.path.join(args.outdir, f"behavioral_power_n{args.n_subj}_t{args.n_trials}.csv")
    summary_path = os.path.join(args.outdir, f"behavioral_power_summary_n{args.n_subj}_t{args.n_trials}.csv")
    results.to_csv(results_path, index=False)
    summary.to_csv(summary_path, index=False)

    print("\nSummary:")
    print(summary.round(4).to_string(index=False))
    print("\nFiles written:")
    print(f"  {results_path}")
    print(f"  {summary_path}")


if __name__ == "__main__":
    main()
