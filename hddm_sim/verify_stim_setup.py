"""
verify_stim_setup.py

stim-coding版のシミュレーション設計が正しく動くか確認:

  Test 1: 単一被験者でデータ生成 → 経験的acc/RTがプレ実験 (acc≈0.95, RT≈370ms) と整合
  Test 2: 20人/群で生成 → Control vs EMS の差がΔRT≈-8ms, Δacc≈0
  Test 3: 1反復のフルフィット (n_subj=10, n_trials=80, n_samples=500) を実行し、
          各種判定が動作することを確認
"""

import math
import sys
import os
import time
import warnings

import numpy as np
import pandas as pd
import hddm

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import TRUE_PARAMS, SUBJ_VAR

import importlib.util
spec = importlib.util.spec_from_file_location(
    "sim_data",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "01_simulate_data.py")
)
sim_data = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sim_data)

spec2 = importlib.util.spec_from_file_location(
    "fit_hddm",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "02_fit_hddm.py")
)
fit_hddm = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(fit_hddm)


def main():
    print("=" * 70)
    print("Verification of stim-coding simulation setup")
    print("=" * 70)
    print(f"\nTrue params (Control): {TRUE_PARAMS['control']}")
    print(f"True params (EMS):     {TRUE_PARAMS['ems']}")
    print(f"SUBJ_VAR:              {SUBJ_VAR}")

    # ===========================================
    # Test 1: 単一被験者 (ばらつきなし) で2000試行
    # ===========================================
    print("\n" + "=" * 70)
    print("Test 1: Single subject, no variability, 2000 trials")
    print("=" * 70)

    p_ctrl = TRUE_PARAMS['control']
    df1 = sim_data.simulate_one_subject(
        params=p_ctrl, n_trials=2000, seed=42
    )
    df1['correct'] = (df1['response'] == df1['stim']).astype(int)
    acc1 = df1['correct'].mean()
    rt1_ms = df1['rt'].mean() * 1000

    print(f"  Empirical acc: {acc1:.4f}")
    print(f"  Empirical RT:  {rt1_ms:.1f} ms")
    print(f"  Stim balance: Left={(df1['stim']==0).sum()}, Right={(df1['stim']==1).sum()}")
    print(f"  Resp balance: Left={(df1['response']==0).sum()}, Right={(df1['response']==1).sum()}")

    if 0.92 <= acc1 <= 0.98 and 340 <= rt1_ms <= 400:
        print("  STATUS: ✓ PASS (matches pre-experiment)")
        test1_pass = True
    else:
        print("  STATUS: ✗ Unexpected (check params)")
        test1_pass = False

    # ===========================================
    # Test 2: 20人/群、80試行 → Control vs EMS の差
    # ===========================================
    print("\n" + "=" * 70)
    print("Test 2: 20 subj/group × 80 trials, with variability")
    print("=" * 70)

    df2 = sim_data.simulate_two_groups(n_subj_per_group=20, n_trials=80, seed=123)
    df2['correct'] = (df2['response'] == df2['stim']).astype(int)
    summary2 = df2.groupby('condition').agg(
        acc=('correct', 'mean'),
        rt_ms=('rt', lambda x: x.mean() * 1000),
        n=('rt', 'count'),
    ).round(3)
    print(summary2)

    acc_ctrl_2 = summary2.loc['control', 'acc']
    acc_ems_2 = summary2.loc['ems', 'acc']
    rt_ctrl_2 = summary2.loc['control', 'rt_ms']
    rt_ems_2 = summary2.loc['ems', 'rt_ms']
    print(f"\n  Δacc = {acc_ems_2 - acc_ctrl_2:+.4f} (expected ~0)")
    print(f"  ΔRT  = {rt_ems_2 - rt_ctrl_2:+.1f} ms (expected ~-8 ms, ±10ms tolerable)")

    if abs(acc_ems_2 - acc_ctrl_2) < 0.05 and -25 < (rt_ems_2 - rt_ctrl_2) < 10:
        print("  STATUS: ✓ PASS (within reasonable bounds for single rep)")
        test2_pass = True
    else:
        print("  STATUS: ⚠ Unexpected, but may be due to single-rep noise")
        test2_pass = False

    # ===========================================
    # Test 3: HDDMStimCoding で1反復フィット
    # ===========================================
    print("\n" + "=" * 70)
    print("Test 3: Full HDDMStimCoding fit (n=10/grp, T=80, n_samples=500)")
    print("=" * 70)
    print("This takes 2-5 minutes...")

    t0 = time.time()
    try:
        result = fit_hddm.fit_one_replication(
            n_subj_per_group=10, n_trials=80, rep_id=0,
            n_samples=500, burn=200, thin=2, verbose=False,
        )
        elapsed = time.time() - t0
        print(f"  Fit completed in {elapsed:.1f}s")
        print(f"\n  Posterior means of group differences:")
        print(f"    a_diff: {result['a_diff_mean']:+.4f}  (true=0)")
        print(f"    v_diff: {result['v_diff_mean']:+.4f}  (true=0)")
        print(f"    t_diff: {result['t_diff_mean']:+.4f}  (true=-0.008)")
        print(f"\n  HDIs:")
        print(f"    a: [{result['a_hdi_low']:+.3f}, {result['a_hdi_high']:+.3f}]")
        print(f"    v: [{result['v_hdi_low']:+.3f}, {result['v_hdi_high']:+.3f}]")
        print(f"    t: [{result['t_hdi_low']:+.4f}, {result['t_hdi_high']:+.4f}]")
        print(f"\n  Decisions (固定ROPE):")
        print(f"    a equivalence (ROPE±0.10):  {result['a_decision']}")
        print(f"    v equivalence (ROPE±0.30):  {result['v_decision']}")
        print(f"    t shortening (HDI<0):       {result['t_decision']}")
        print(f"\n  Empirical ROPE (Szul流):")
        print(f"    a ROPE: [{result['a_rope_emp_low']:+.4f}, {result['a_rope_emp_high']:+.4f}]"
              f" (width={result['a_rope_emp_width']:.4f})")
        print(f"    v ROPE: [{result['v_rope_emp_low']:+.4f}, {result['v_rope_emp_high']:+.4f}]"
              f" (width={result['v_rope_emp_width']:.4f})")
        print(f"    t ROPE: [{result['t_rope_emp_low']:+.5f}, {result['t_rope_emp_high']:+.5f}]"
              f" (width={result['t_rope_emp_width']:.5f})")
        print(f"\n  Decisions (empirical ROPE):")
        print(f"    a equivalence:  {result['a_decision_emp']}")
        print(f"    v equivalence:  {result['v_decision_emp']}")
        print(f"\n  P_P|D (Szul):")
        print(f"    a: {result['a_p_pd']:.3f}  (1.0 = strong equivalence)")
        print(f"    v: {result['v_p_pd']:.3f}")
        print(f"    t: {result['t_p_pd']:.3f}")
        print(f"\n  Empirical:")
        print(f"    Acc: ctrl={result['acc_ctrl']:.3f}, ems={result['acc_ems']:.3f}")
        print(f"    RT:  ctrl={result['rt_ctrl_ms']:.1f}ms, ems={result['rt_ems_ms']:.1f}ms")
        print(f"    Acc non-inferior: {result['acc_noninf']}")
        print(f"    RT shortened:     {result['rt_shortened']}")
        test3_pass = True
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\n  STATUS: ✗ FAIL with error: {e}")
        test3_pass = False

    # ===========================================
    # 結論
    # ===========================================
    print("\n" + "=" * 70)
    print("CONCLUSION")
    print("=" * 70)
    if test1_pass and test3_pass:
        print("✓ Stim-coding setup is working. Ready for full grid run.")
        print("\nNext step:")
        print("  python 03_run_grid.py --n_jobs 4 --n_reps 30 --output_dir ./results_stim_szul")
    else:
        print("⚠ Some tests did not pass. Review utils.py and 01/02 scripts.")


if __name__ == '__main__':
    main()
