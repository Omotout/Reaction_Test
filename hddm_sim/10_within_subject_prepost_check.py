"""
Within-subject pre/post check for the EMS training design.

Design:
- Every subject completes self-training and EMS-training blocks.
- Each training type has pre and post sessions.
- Subject-level DDM parameters are sampled once and reused across all four cells.
- Only EMS post has a non-decision time shortening by default (-8 ms).

Primary behavioral estimands:
- RT difference-in-differences:
    (EMS_post - EMS_pre) - (Self_post - Self_pre) < 0
- Accuracy non-inferiority on the same change-score contrast:
    DeltaAcc_DiD > -margin

Optional HDDM estimands, when hddm is available:
- t EMS pre-post and t DiD posterior differences.
- a EMS pre-post and a DiD empirical-ROPE + HDI equivalence decisions.
"""

import argparse
import json
import os
import time
import warnings
from statistics import NormalDist

import numpy as np
import pandas as pd


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONDITIONS = ["self_pre", "self_post", "ems_pre", "ems_post"]
PARAMS = ["a", "v", "t"]
NORMAL = NormalDist()


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_testdata_params(summary_path):
    if not os.path.isabs(summary_path):
        summary_path = os.path.join(SCRIPT_DIR, summary_path)
    summary = load_json(summary_path)
    return {
        "base": {
            "a": summary["empirical_means"]["a"],
            "v": summary["empirical_means"]["v"],
            "t": summary["empirical_means"]["t"],
            "z": 0.5,
        },
        "var": summary["empirical_subj_var"],
        "source": summary_path,
    }


def hdi(samples, prob=0.95):
    samples = np.sort(np.asarray(samples, dtype=float))
    interval_size = int(np.floor(prob * len(samples)))
    if interval_size < 1:
        return float("nan"), float("nan")
    widths = samples[interval_size:] - samples[: len(samples) - interval_size]
    i = int(np.argmin(widths))
    return float(samples[i]), float(samples[i + interval_size])


def rope_decision(samples, rope_low, rope_high, prob=0.95):
    low, high = hdi(samples, prob=prob)
    if low >= rope_low and high <= rope_high:
        return "equivalent"
    if high < rope_low or low > rope_high:
        return "reject"
    return "undecided"


def empirical_rope_szul(samples_a, samples_b, prob=0.95):
    def internal_hdi(samples):
        n = len(samples) - (len(samples) % 2)
        even = samples[:n:2]
        odd = samples[1:n:2]
        return hdi(odd - even, prob=prob)

    a_low, a_high = internal_hdi(np.asarray(samples_a, dtype=float))
    b_low, b_high = internal_hdi(np.asarray(samples_b, dtype=float))
    return float(min(a_low, b_low)), float(max(a_high, b_high))


def p_pd_from_hdi_and_rope(hdi_low, hdi_high, rope_low, rope_high):
    width = hdi_high - hdi_low
    if width <= 0:
        return float("nan")
    overlap_low = max(hdi_low, rope_low)
    overlap_high = min(hdi_high, rope_high)
    return float(max(0.0, overlap_high - overlap_low) / width)


def normal_one_sample_test(values, null=0.0, alternative="less"):
    values = np.asarray(values, dtype=float)
    diff = float(values.mean())
    sd = float(values.std(ddof=1))
    n = len(values)
    se = sd / np.sqrt(n)
    z = (diff - null) / se if se > 0 else np.inf * np.sign(diff - null)
    if alternative == "less":
        p = NORMAL.cdf(z)
    elif alternative == "greater":
        p = 1.0 - NORMAL.cdf(z)
    else:
        p = 2.0 * min(NORMAL.cdf(z), 1.0 - NORMAL.cdf(z))
    ci = NORMAL.inv_cdf(0.975) * se
    return {
        "mean": diff,
        "sd": sd,
        "se": float(se),
        "z": float(z),
        "p": float(p),
        "ci95_low": float(diff - ci),
        "ci95_high": float(diff + ci),
    }


def sample_subject_params(rng, base, var):
    return {
        "a": max(0.3, rng.normal(base["a"], var["a_sd"])),
        "v": max(0.5, rng.normal(base["v"], var["v_sd"])),
        "t": max(0.05, rng.normal(base["t"], var["t_sd"])),
        "z": 0.5,
    }


def simulate_ddm_euler(params, n_trials, rng, dt=0.001, noise_var=2.23):
    """Fast local fallback approximating HDDM gen_rand_data behavior."""
    stims = rng.integers(0, 2, size=n_trials)
    x = np.zeros(n_trials, dtype=float)
    rt = np.zeros(n_trials, dtype=float)
    correct = np.zeros(n_trials, dtype=int)
    active = np.ones(n_trials, dtype=bool)
    bound = params["a"] / 2.0
    sigma = np.sqrt(noise_var)
    max_steps = int(np.ceil(5.0 / dt))

    for step in range(1, max_steps + 1):
        idx = np.flatnonzero(active)
        if len(idx) == 0:
            break
        x[idx] += params["v"] * dt + sigma * np.sqrt(dt) * rng.normal(size=len(idx))
        hit = np.abs(x[idx]) >= bound
        if not np.any(hit):
            continue
        hidx = idx[hit]
        active[hidx] = False
        rt[hidx] = step * dt + params["t"]
        correct[hidx] = (x[hidx] > 0).astype(int)

    if np.any(active):
        idx = np.flatnonzero(active)
        rt[idx] = max_steps * dt + params["t"]
        correct[idx] = (x[idx] > 0).astype(int)

    response = np.where(correct == 1, stims, 1 - stims)
    return pd.DataFrame(
        {
            "rt": rt,
            "response": response.astype(int),
            "stim": stims.astype(int),
        }
    )


def simulate_one_subject(params, n_trials, rng, generator="auto"):
    if generator in ("auto", "hddm"):
        try:
            import hddm

            stims = rng.integers(0, 2, size=n_trials)
            data, _ = hddm.generate.gen_rand_data(
                {"a": params["a"], "v": params["v"], "t": params["t"], "z": params["z"]},
                size=n_trials,
                subjs=1,
                subj_noise=0.0,
                seed=int(rng.integers(0, 1_000_000_000)),
            )
            correct = data["response"].astype(int).values
            response = np.where(correct == 1, stims, 1 - stims)
            return pd.DataFrame(
                {"rt": data["rt"].values, "response": response.astype(int), "stim": stims.astype(int)}
            )
        except ImportError:
            if generator == "hddm":
                raise

    return simulate_ddm_euler(params, n_trials, rng)


def simulate_within_subject(
    n_subj,
    n_trials,
    seed,
    base,
    var,
    ems_post_t_delta_ms=-8.0,
    self_post_t_delta_ms=0.0,
    pre_trials=None,
    post_trials=None,
    generator="auto",
):
    rng = np.random.default_rng(seed)
    pre_trials = n_trials if pre_trials is None else pre_trials
    post_trials = n_trials if post_trials is None else post_trials
    rows = []
    for subj_idx in range(n_subj):
        subj_params = sample_subject_params(rng, base, var)
        for training, post_delta_ms in (
            ("self", self_post_t_delta_ms),
            ("ems", ems_post_t_delta_ms),
        ):
            for phase, phase_delta_ms in (("pre", 0.0), ("post", post_delta_ms)):
                params = dict(subj_params)
                params["t"] = max(0.05, params["t"] + phase_delta_ms / 1000.0)
                phase_trials = pre_trials if phase == "pre" else post_trials
                df = simulate_one_subject(params, phase_trials, rng, generator=generator)
                df["subj_idx"] = subj_idx
                df["training"] = training
                df["phase"] = phase
                df["condition"] = f"{training}_{phase}"
                df["a_true"] = params["a"]
                df["v_true"] = params["v"]
                df["t_true"] = params["t"]
                rows.append(df)

    out = pd.concat(rows, ignore_index=True)
    out["correct"] = (out["response"] == out["stim"]).astype(int)
    return out


def filter_trials(df, rt_min_ms=None, rt_max_ms=None, drop_first_n_per_cell=0):
    out = df.copy()
    if drop_first_n_per_cell > 0:
        order = out.groupby(["subj_idx", "condition"]).cumcount()
        out = out[order >= drop_first_n_per_cell].copy()
    if rt_min_ms is not None:
        out = out[out["rt"] * 1000.0 >= rt_min_ms].copy()
    if rt_max_ms is not None:
        out = out[out["rt"] * 1000.0 <= rt_max_ms].copy()
    return out


def summarize_subjects(df, rt_summary="mean"):
    cell = (
        df.groupby(["training", "phase", "condition", "subj_idx"], as_index=False)
        .agg(
            mean_rt_ms=("rt", lambda x: x.mean() * 1000.0),
            median_rt_ms=("rt", lambda x: x.median() * 1000.0),
            accuracy=("correct", "mean"),
            n_trials=("rt", "count"),
        )
    )
    wide = cell.pivot(index="subj_idx", columns="condition")
    wide.columns = [f"{metric}_{condition}" for metric, condition in wide.columns]
    wide = wide.reset_index()
    rt_col = f"{rt_summary}_rt_ms"
    wide["self_delta_rt_ms"] = wide[f"{rt_col}_self_post"] - wide[f"{rt_col}_self_pre"]
    wide["ems_delta_rt_ms"] = wide[f"{rt_col}_ems_post"] - wide[f"{rt_col}_ems_pre"]
    wide["rt_did_ms"] = wide["ems_delta_rt_ms"] - wide["self_delta_rt_ms"]
    wide["self_gain_rt_ms"] = -wide["self_delta_rt_ms"]
    wide["ems_gain_rt_ms"] = -wide["ems_delta_rt_ms"]
    wide["gain_did_ms"] = -wide["rt_did_ms"]
    wide["self_delta_accuracy"] = wide["accuracy_self_post"] - wide["accuracy_self_pre"]
    wide["ems_delta_accuracy"] = wide["accuracy_ems_post"] - wide["accuracy_ems_pre"]
    wide["acc_did"] = wide["ems_delta_accuracy"] - wide["self_delta_accuracy"]
    return cell, wide


def analyze_behavior(
    df,
    acc_margin=0.03,
    alpha_rt=0.05,
    alpha_noninf=0.025,
    rt_summary="mean",
    rt_min_ms=None,
    rt_max_ms=None,
    drop_first_n_per_cell=0,
):
    df_used = filter_trials(
        df,
        rt_min_ms=rt_min_ms,
        rt_max_ms=rt_max_ms,
        drop_first_n_per_cell=drop_first_n_per_cell,
    )
    cell, wide = summarize_subjects(df_used, rt_summary=rt_summary)
    rt = normal_one_sample_test(wide["rt_did_ms"], null=0.0, alternative="less")
    ems_gain = normal_one_sample_test(wide["ems_gain_rt_ms"], null=0.0, alternative="greater")
    acc = normal_one_sample_test(wide["acc_did"], null=-acc_margin, alternative="greater")
    lower = acc["mean"] - NORMAL.inv_cdf(1.0 - alpha_noninf) * acc["se"]
    trial_summary = (
        df_used.groupby(["training", "phase", "condition"], as_index=False)
        .agg(
            mean_rt_ms=("rt", lambda x: x.mean() * 1000.0),
            median_rt_ms=("rt", lambda x: x.median() * 1000.0),
            accuracy=("correct", "mean"),
            n_trials=("rt", "count"),
            n_subj=("subj_idx", "nunique"),
        )
    )
    delta_summary = pd.DataFrame(
        [
            {
                "n_subj": wide["subj_idx"].nunique(),
                "rt_summary": rt_summary,
                "self_delta_rt_ms_mean": wide["self_delta_rt_ms"].mean(),
                "ems_delta_rt_ms_mean": wide["ems_delta_rt_ms"].mean(),
                "rt_did_ms_mean": wide["rt_did_ms"].mean(),
                "rt_did_ms_sd": wide["rt_did_ms"].std(ddof=1),
                "ems_gain_rt_ms_mean": wide["ems_gain_rt_ms"].mean(),
                "ems_gain_rt_ms_sd": wide["ems_gain_rt_ms"].std(ddof=1),
                "self_delta_accuracy_mean": wide["self_delta_accuracy"].mean(),
                "ems_delta_accuracy_mean": wide["ems_delta_accuracy"].mean(),
                "acc_did_mean": wide["acc_did"].mean(),
                "acc_did_sd": wide["acc_did"].std(ddof=1),
            }
        ]
    )
    result = {
        "rt_did_ms": rt["mean"],
        "rt_did_se": rt["se"],
        "rt_p_one_sided": rt["p"],
        "rt_ci95_low": rt["ci95_low"],
        "rt_ci95_high": rt["ci95_high"],
        "rt_success": bool(rt["p"] < alpha_rt),
        "ems_gain_rt_ms": ems_gain["mean"],
        "ems_gain_p_one_sided": ems_gain["p"],
        "ems_gain_success": bool(ems_gain["p"] < alpha_rt),
        "acc_did": acc["mean"],
        "acc_did_se": acc["se"],
        "acc_noninf_p": acc["p"],
        "acc_noninf_lower_bound": float(lower),
        "acc_noninf_success": bool(acc["p"] < alpha_noninf and lower > -acc_margin),
        "both_success": bool(rt["p"] < alpha_rt and acc["p"] < alpha_noninf and lower > -acc_margin),
    }
    return result, trial_summary, cell, wide, delta_summary


def run_behavioral_power(args, base, var):
    rows = []
    first_outputs = None
    for rep in range(args.n_reps):
        rep_id = args.seed_offset + rep
        df = simulate_within_subject(
            n_subj=args.n_subj,
            n_trials=args.n_trials,
            seed=rep_id,
            base=base,
            var=var,
            ems_post_t_delta_ms=args.ems_post_t_delta_ms,
            self_post_t_delta_ms=args.self_post_t_delta_ms,
            pre_trials=args.pre_trials,
            post_trials=args.post_trials,
            generator=args.generator,
        )
        result, trial_summary, cell, wide, delta_summary = analyze_behavior(
            df,
            acc_margin=args.acc_margin,
            alpha_rt=args.alpha_rt,
            alpha_noninf=args.alpha_noninf,
            rt_summary=args.rt_summary,
            rt_min_ms=args.rt_min_ms,
            rt_max_ms=args.rt_max_ms,
            drop_first_n_per_cell=args.drop_first_n_per_cell,
        )
        result.update(
            {
                "rep_id": rep_id,
                "n_subj": args.n_subj,
                "n_trials": args.n_trials,
                "pre_trials": args.pre_trials or args.n_trials,
                "post_trials": args.post_trials or args.n_trials,
                "rt_summary": args.rt_summary,
                "ems_post_t_delta_ms": args.ems_post_t_delta_ms,
                "self_post_t_delta_ms": args.self_post_t_delta_ms,
            }
        )
        rows.append(result)
        if rep == 0:
            first_outputs = (df, trial_summary, cell, wide, delta_summary)
        if (rep + 1) % 10 == 0 or rep + 1 == args.n_reps:
            print(f"Completed {rep + 1}/{args.n_reps} behavioral reps")

    results = pd.DataFrame(rows)
    summary = pd.DataFrame(
        [
            {
                "n_subj": args.n_subj,
                "n_trials": args.n_trials,
                "pre_trials": args.pre_trials or args.n_trials,
                "post_trials": args.post_trials or args.n_trials,
                "n_reps": args.n_reps,
                "rt_summary": args.rt_summary,
                "ems_post_t_delta_ms": args.ems_post_t_delta_ms,
                "self_post_t_delta_ms": args.self_post_t_delta_ms,
                "rt_did_mean_ms": results["rt_did_ms"].mean(),
                "rt_did_sd_ms": results["rt_did_ms"].std(ddof=1),
                "rt_direction_rate": (results["rt_did_ms"] < 0).mean(),
                "rt_success_rate": results["rt_success"].mean(),
                "ems_gain_mean_ms": results["ems_gain_rt_ms"].mean(),
                "ems_gain_success_rate": results["ems_gain_success"].mean(),
                "acc_did_mean": results["acc_did"].mean(),
                "acc_did_sd": results["acc_did"].std(ddof=1),
                "acc_noninf_success_rate": results["acc_noninf_success"].mean(),
                "both_success_rate": results["both_success"].mean(),
            }
        ]
    )

    os.makedirs(args.outdir, exist_ok=True)
    tag = f"n{args.n_subj}_t{args.n_trials}_reps{args.n_reps}"
    results_path = os.path.join(args.outdir, f"within_subject_behavior_results_{tag}.csv")
    summary_path = os.path.join(args.outdir, f"within_subject_behavior_summary_{tag}.csv")
    results.to_csv(results_path, index=False)
    summary.to_csv(summary_path, index=False)

    if first_outputs is not None:
        df, trial_summary, cell, wide, delta_summary = first_outputs
        trial_summary.to_csv(os.path.join(args.outdir, "rep0_trial_summary.csv"), index=False)
        cell.to_csv(os.path.join(args.outdir, "rep0_subject_cell_summary.csv"), index=False)
        wide.to_csv(os.path.join(args.outdir, "rep0_subject_change_scores.csv"), index=False)
        delta_summary.to_csv(os.path.join(args.outdir, "rep0_delta_summary.csv"), index=False)
        if args.save_first_trial_data:
            df.to_csv(os.path.join(args.outdir, "rep0_trial_data.csv"), index=False)

    print("\nBehavioral summary:")
    print(summary.round(4).to_string(index=False))
    print("\nFiles written:")
    print(f"  {results_path}")
    print(f"  {summary_path}")
    return results, summary


def trace(model, param, condition):
    return model.nodes_db.node[f"{param}({condition})"].trace()


def summarize_diff(prefix, diff_samples, rope=None):
    low, high = hdi(diff_samples)
    row = {
        f"{prefix}_mean": float(np.mean(diff_samples)),
        f"{prefix}_sd": float(np.std(diff_samples)),
        f"{prefix}_hdi_low": low,
        f"{prefix}_hdi_high": high,
    }
    if rope is not None:
        row[f"{prefix}_rope_low"] = float(rope[0])
        row[f"{prefix}_rope_high"] = float(rope[1])
        row[f"{prefix}_decision"] = rope_decision(diff_samples, *rope)
        row[f"{prefix}_p_pd"] = p_pd_from_hdi_and_rope(low, high, rope[0], rope[1])
    return row


def fit_hddm_one_rep(args, base, var, rep_id):
    import hddm

    df = simulate_within_subject(
        n_subj=args.n_subj,
        n_trials=args.n_trials,
        seed=rep_id,
        base=base,
        var=var,
        ems_post_t_delta_ms=args.ems_post_t_delta_ms,
        self_post_t_delta_ms=args.self_post_t_delta_ms,
        pre_trials=args.pre_trials,
        post_trials=args.post_trials,
        generator="hddm",
    )
    beh, trial_summary, cell, wide, delta_summary = analyze_behavior(
        df,
        acc_margin=args.acc_margin,
        rt_summary=args.rt_summary,
        rt_min_ms=args.rt_min_ms,
        rt_max_ms=args.rt_max_ms,
        drop_first_n_per_cell=args.drop_first_n_per_cell,
    )
    fit_df = df[["subj_idx", "rt", "response", "stim", "condition"]].copy()
    fit_df["response"] = fit_df["response"].astype(int)
    fit_df["stim"] = fit_df["stim"].astype(int)
    fit_df["condition"] = pd.Categorical(fit_df["condition"], categories=CONDITIONS)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = hddm.HDDMStimCoding(
            fit_df,
            include=["v", "a", "t"],
            stim_col="stim",
            split_param="v",
            depends_on={"a": "condition", "v": "condition", "t": "condition"},
        )
        model.find_starting_values()
        t0 = time.time()
        model.sample(args.samples, burn=args.burn, thin=args.thin, dbname=None, db="ram")
        elapsed = time.time() - t0

    samples = {p: {c: trace(model, p, c) for c in CONDITIONS} for p in PARAMS}
    row = {
        "rep_id": rep_id,
        "n_subj": args.n_subj,
        "n_trials": args.n_trials,
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

        row.update(summarize_diff(f"{param}_ems_prepost", ems_delta))
        row.update(summarize_diff(f"{param}_did", did))

        ems_rope = empirical_rope_szul(samples[param]["ems_pre"], samples[param]["ems_post"])
        did_rope = empirical_rope_szul(self_delta, ems_delta)
        row.update(summarize_diff(f"{param}_ems_prepost_emp", ems_delta, rope=ems_rope))
        row.update(summarize_diff(f"{param}_did_emp", did, rope=did_rope))

    if rep_id == args.seed_offset:
        trial_summary.to_csv(os.path.join(args.outdir, "hddm_rep0_trial_summary.csv"), index=False)
        cell.to_csv(os.path.join(args.outdir, "hddm_rep0_subject_cell_summary.csv"), index=False)
        wide.to_csv(os.path.join(args.outdir, "hddm_rep0_subject_change_scores.csv"), index=False)
        delta_summary.to_csv(os.path.join(args.outdir, "hddm_rep0_delta_summary.csv"), index=False)
        if args.save_first_trial_data:
            df.to_csv(os.path.join(args.outdir, "hddm_rep0_trial_data.csv"), index=False)

    return row


def run_hddm(args, base, var):
    try:
        import hddm  # noqa: F401
    except ImportError as exc:
        raise SystemExit(
            "HDDM is not available in this Python environment. "
            "Run this part in the HDDM environment, for example via "
            "`docker run --rm -v ${PWD}:/work -w /work/hddm_sim "
            "hcp4715/hddm:latest python 10_within_subject_prepost_check.py "
            "--run-hddm ...`."
        ) from exc

    os.makedirs(args.outdir, exist_ok=True)
    rows = []
    for i in range(args.hddm_reps):
        rep_id = args.seed_offset + i
        print(f"\n=== HDDM rep {i + 1}/{args.hddm_reps} (rep_id={rep_id}) ===")
        row = fit_hddm_one_rep(args, base, var, rep_id)
        rows.append(row)
        print(
            "HDDM: "
            f"t EMS pre-post={row['t_ems_prepost_mean'] * 1000:+.2f} ms, "
            f"t DiD={row['t_did_mean'] * 1000:+.2f} ms, "
            f"a DiD empirical={row['a_did_emp_decision']} "
            f"(P_P|D={row['a_did_emp_p_pd']:.3f})"
        )

    results = pd.DataFrame(rows)
    summary = pd.DataFrame(
        [
            {
                "n_subj": args.n_subj,
                "n_trials": args.n_trials,
                "n_reps": args.hddm_reps,
                "t_ems_prepost_mean_ms": results["t_ems_prepost_mean"].mean() * 1000.0,
                "t_did_mean_ms": results["t_did_mean"].mean() * 1000.0,
                "a_ems_emp_equiv_rate": (results["a_ems_prepost_emp_decision"] == "equivalent").mean(),
                "a_ems_emp_p_pd_mean": results["a_ems_prepost_emp_p_pd"].mean(),
                "a_did_emp_equiv_rate": (results["a_did_emp_decision"] == "equivalent").mean(),
                "a_did_emp_p_pd_mean": results["a_did_emp_p_pd"].mean(),
            }
        ]
    )
    tag = f"n{args.n_subj}_t{args.n_trials}_reps{args.hddm_reps}"
    results_path = os.path.join(args.outdir, f"within_subject_hddm_results_{tag}.csv")
    summary_path = os.path.join(args.outdir, f"within_subject_hddm_summary_{tag}.csv")
    results.to_csv(results_path, index=False)
    summary.to_csv(summary_path, index=False)
    print("\nHDDM summary:")
    print(summary.round(4).to_string(index=False))
    print("\nFiles written:")
    print(f"  {results_path}")
    print(f"  {summary_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", default="testdata_direct_ddm_summary.json")
    parser.add_argument("--n-subj", type=int, default=20)
    parser.add_argument("--n-trials", type=int, default=80)
    parser.add_argument("--pre-trials", type=int, default=None)
    parser.add_argument("--post-trials", type=int, default=None)
    parser.add_argument("--n-reps", type=int, default=100)
    parser.add_argument("--seed-offset", type=int, default=0)
    parser.add_argument("--ems-post-t-delta-ms", type=float, default=-8.0)
    parser.add_argument("--self-post-t-delta-ms", type=float, default=0.0)
    parser.add_argument("--acc-margin", type=float, default=0.03)
    parser.add_argument("--alpha-rt", type=float, default=0.05)
    parser.add_argument("--alpha-noninf", type=float, default=0.025)
    parser.add_argument("--rt-summary", choices=["mean", "median"], default="mean")
    parser.add_argument("--rt-min-ms", type=float, default=None)
    parser.add_argument("--rt-max-ms", type=float, default=None)
    parser.add_argument("--drop-first-n-per-cell", type=int, default=0)
    parser.add_argument("--generator", choices=["auto", "hddm", "euler"], default="auto")
    parser.add_argument("--outdir", default="results_within_subject_prepost")
    parser.add_argument("--save-first-trial-data", action="store_true")
    parser.add_argument("--run-hddm", action="store_true")
    parser.add_argument("--hddm-reps", type=int, default=1)
    parser.add_argument("--samples", type=int, default=2000)
    parser.add_argument("--burn", type=int, default=1000)
    parser.add_argument("--thin", type=int, default=2)
    args = parser.parse_args()

    source = load_testdata_params(args.summary)
    base = source["base"]
    var = source["var"]
    os.makedirs(args.outdir, exist_ok=True)
    with open(os.path.join(args.outdir, "parameter_source.json"), "w", encoding="utf-8") as f:
        json.dump(source, f, indent=2)

    print("=" * 72)
    print("Within-subject EMS pre/post check")
    print("=" * 72)
    print(f"Parameter source: {source['source']}")
    print(
        f"base: a={base['a']:.4f}, v={base['v']:.4f}, t={base['t']:.4f}; "
        f"sd: a={var['a_sd']:.4f}, v={var['v_sd']:.4f}, t={var['t_sd']:.4f}"
    )
    print(f"EMS post t delta: {args.ems_post_t_delta_ms:.1f} ms")

    run_behavioral_power(args, base, var)
    if args.run_hddm:
        run_hddm(args, base, var)


if __name__ == "__main__":
    main()
