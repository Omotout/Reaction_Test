"""
Verify the calibrated HDDM simulation parameters in utils.py.

This file keeps the old name for compatibility with previous notes, but it no
longer verifies a sqrt(2) correction. It checks whether the current calibrated
parameters generate roughly the intended behavior.
"""

import importlib.util
import os
import sys

import hddm
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import SUBJ_VAR, TRUE_PARAMS

spec = importlib.util.spec_from_file_location(
    "sim_data",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "01_simulate_data.py"),
)
sim_data = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sim_data)


def main():
    print("=" * 70)
    print("Verification of calibrated simulation parameters")
    print("=" * 70)
    print("\nTRUE_PARAMS:")
    for group, params in TRUE_PARAMS.items():
        print(
            f"  {group}: "
            f"a={params['a']:.4f}, v={params['v']:.4f}, "
            f"t={params['t']:.4f}, z={params['z']:.2f}"
        )
    print("\nSUBJ_VAR:")
    print(
        f"  a_sd={SUBJ_VAR['a_sd']:.4f}, "
        f"v_sd={SUBJ_VAR['v_sd']:.4f}, "
        f"t_sd={SUBJ_VAR['t_sd']:.4f}"
    )

    print("\n" + "=" * 70)
    print("Test 1: Single subject, no variability")
    print("=" * 70)
    p_ctrl = TRUE_PARAMS["control"]
    data1, _ = hddm.generate.gen_rand_data(
        {"a": p_ctrl["a"], "v": p_ctrl["v"], "t": p_ctrl["t"], "z": p_ctrl["z"]},
        size=4000,
        subjs=1,
        subj_noise=0.0,
    )
    acc1 = data1["response"].mean()
    rt1 = data1["rt"].mean()
    print(f"  Empirical: acc={acc1:.4f}, RT_mean={rt1 * 1000:.1f} ms")
    print("  Reference: direct TestData-recovered parameter check")

    print("\n" + "=" * 70)
    print("Test 2: Multi-subject with variability, averaged across seeds")
    print("=" * 70)
    rows = []
    for seed in range(60):
        df = sim_data.simulate_two_groups(n_subj_per_group=20, n_trials=80, seed=seed)
        summary = df.groupby("condition").agg(acc=("response", "mean"), rt=("rt", "mean"))
        rows.append(
            {
                "ctrl_acc": summary.loc["control", "acc"],
                "ems_acc": summary.loc["ems", "acc"],
                "acc_diff": summary.loc["ems", "acc"] - summary.loc["control", "acc"],
                "ctrl_rt_ms": summary.loc["control", "rt"] * 1000,
                "ems_rt_ms": summary.loc["ems", "rt"] * 1000,
                "rt_diff_ms": (summary.loc["ems", "rt"] - summary.loc["control", "rt"]) * 1000,
            }
        )

    multi = pd.DataFrame(rows)
    means = multi.mean()
    sds = multi.std()

    print(
        f"  Control: acc={means['ctrl_acc']:.4f} (SD={sds['ctrl_acc']:.4f}), "
        f"RT={means['ctrl_rt_ms']:.1f} ms (SD={sds['ctrl_rt_ms']:.1f})"
    )
    print(
        f"  EMS:     acc={means['ems_acc']:.4f} (SD={sds['ems_acc']:.4f}), "
        f"RT={means['ems_rt_ms']:.1f} ms (SD={sds['ems_rt_ms']:.1f})"
    )
    print(
        f"  Diff:    acc_diff={means['acc_diff']:+.4f} (SD={sds['acc_diff']:.4f}), "
        f"RT_diff={means['rt_diff_ms']:+.1f} ms (SD={sds['rt_diff_ms']:.1f})"
    )
    print("\nInterpretation:")
    print("  These are stochastic checks, not proof of exact calibration.")
    print("  Re-run the grid after changing TRUE_PARAMS, SUBJ_VAR, or ROPE.")


if __name__ == "__main__":
    main()
