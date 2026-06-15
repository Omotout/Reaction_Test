"""
Fit a generic correctness-coded HDDM to TestData for direct dummy-data generation.

This is different from fit_pre_experiment.py, which uses HDDMStimCoding. The
purpose here is model consistency: parameters estimated here can be passed
directly to hddm.generate.gen_rand_data and then fit with the same generic HDDM
model used by the dummy-data analyses.
"""

import argparse
import json
import os
import sys
import warnings

import hddm
import pandas as pd


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(SCRIPT_DIR, "pre_experiment_data.csv")


def get_trace(model, names):
    for name in names:
        if name in model.nodes_db.node:
            return model.nodes_db.node[name].trace()
    raise KeyError(f"None of these nodes were found: {names}")


def get_subj_trace(model, param, i):
    candidates = [
        f"{param}_subj.{i}",
        f"{param}_subj(all).{i}",
        f"{param}(all)_subj.{i}",
        f"{param}_subj({i})",
    ]
    for name in candidates:
        if name in model.nodes_db.node:
            return model.nodes_db.node[name].trace()

    for name in model.nodes_db.node.keys():
        if name.startswith(f"{param}_subj") and (
            name.endswith(f".{i}") or f"({i})" in name or f"[{i}]" in name
        ):
            return model.nodes_db.node[name].trace()
    raise KeyError(f"Could not find subject node for {param}, subject {i}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=5000)
    parser.add_argument("--burn", type=int, default=2000)
    parser.add_argument("--thin", type=int, default=2)
    parser.add_argument("--out-prefix", default="testdata_direct_ddm")
    args = parser.parse_args()

    if not os.path.exists(DATA_PATH):
        print(f"ERROR: {DATA_PATH} not found. Run extract_pre_experiment.py first.")
        sys.exit(1)

    df = pd.read_csv(DATA_PATH)
    df_fit = df[["subj_idx", "rt", "response"]].copy()
    df_fit["response"] = df_fit["response"].astype(int)

    print("=" * 72)
    print("Fit generic correctness-coded HDDM to TestData")
    print("=" * 72)
    print(f"Loaded {len(df_fit)} trials from {df_fit['subj_idx'].nunique()} subjects")
    print(f"Accuracy: {df_fit['response'].mean():.4f}")
    print(f"Mean RT: {df_fit['rt'].mean() * 1000:.1f} ms")
    print()

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = hddm.HDDM(
            df_fit,
            include=["a", "v", "t"],
            p_outlier=0.05,
        )
        model.find_starting_values()
        model.sample(args.samples, burn=args.burn, thin=args.thin, dbname=None, db="ram")

    a_group = get_trace(model, ["a"])
    v_group = get_trace(model, ["v"])
    t_group = get_trace(model, ["t"])
    a_group_std = get_trace(model, ["a_std"])
    v_group_std = get_trace(model, ["v_std"])
    t_group_std = get_trace(model, ["t_std"])

    n_subj = int(df_fit["subj_idx"].nunique())
    subj_rows = []
    for i in range(n_subj):
        subj_rows.append(
            {
                "subj_idx": i,
                "subject_id": str(df.loc[df["subj_idx"] == i, "subject_id"].iloc[0]).zfill(3),
                "a": float(get_subj_trace(model, "a", i).mean()),
                "v": float(get_subj_trace(model, "v", i).mean()),
                "t": float(get_subj_trace(model, "t", i).mean()),
            }
        )

    subj_df = pd.DataFrame(subj_rows)
    subj_csv = os.path.join(SCRIPT_DIR, f"{args.out_prefix}_subjlevel.csv")
    subj_df.to_csv(subj_csv, index=False)

    summary = {
        "model": "generic_correctness_coded_HDDM",
        "group_level": {
            "a_mean": float(a_group.mean()),
            "a_post_sd": float(a_group.std()),
            "v_mean": float(v_group.mean()),
            "v_post_sd": float(v_group.std()),
            "t_mean": float(t_group.mean()),
            "t_post_sd": float(t_group.std()),
        },
        "between_subj_sd_posterior": {
            "a_std": float(a_group_std.mean()),
            "v_std": float(v_group_std.mean()),
            "t_std": float(t_group_std.mean()),
        },
        "empirical_subj_var": {
            "a_sd": float(subj_df["a"].std(ddof=1)),
            "v_sd": float(subj_df["v"].std(ddof=1)),
            "t_sd": float(subj_df["t"].std(ddof=1)),
        },
        "empirical_means": {
            "a": float(subj_df["a"].mean()),
            "v": float(subj_df["v"].mean()),
            "t": float(subj_df["t"].mean()),
        },
        "observed_behavior": {
            "accuracy": float(df_fit["response"].mean()),
            "mean_rt_ms": float(df_fit["rt"].mean() * 1000),
            "n_subjects": n_subj,
            "n_trials_total": int(len(df_fit)),
        },
    }

    json_path = os.path.join(SCRIPT_DIR, f"{args.out_prefix}_summary.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print("\nGroup-level posterior:")
    print(f"  a = {summary['group_level']['a_mean']:.4f}")
    print(f"  v = {summary['group_level']['v_mean']:.4f}")
    print(f"  t = {summary['group_level']['t_mean']:.4f}")
    print("\nEmpirical subject-level SD:")
    print(f"  a_sd = {summary['empirical_subj_var']['a_sd']:.4f}")
    print(f"  v_sd = {summary['empirical_subj_var']['v_sd']:.4f}")
    print(f"  t_sd = {summary['empirical_subj_var']['t_sd']:.4f}")
    print("\nSaved:")
    print(f"  {subj_csv}")
    print(f"  {json_path}")


if __name__ == "__main__":
    main()
