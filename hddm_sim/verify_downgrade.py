"""
verify_downgrade.py

HDDM 0.9.8にダウングレード後、シミュレータが理論値と合うかを再確認。
diagnose_scale_v2.py の Method 1 と Method 4 だけを再実行する短いスクリプト。

実行: python verify_downgrade.py
"""

import math
import sys
import os
import json

import numpy as np
import pandas as pd
import hddm


def theoretical_acc(a, v, s=1.0):
    return 1.0 / (1.0 + math.exp(-2 * a * v / s**2))


def theoretical_rt(a, v, t, s=1.0):
    av = a * v / s**2
    DT = (a / (2 * v)) * math.tanh(av)
    return DT + t


def empirical_stats(data):
    return {
        'acc': float(data['response'].mean()),
        'rt_mean': float(data['rt'].mean()),
        'rt_median': float(data['rt'].median()),
    }


def main():
    print("=" * 70)
    print(f"HDDM version: {hddm.__version__}")
    print("=" * 70)

    results = {'hddm_version': hddm.__version__}

    # Test A: a=0.676, v=1.625, t=0.204
    print("\nTest A: a=0.676, v=1.625, t=0.204 (research target)")
    a, v, t = 0.676, 1.625, 0.204
    p_th = theoretical_acc(a, v)
    rt_th = theoretical_rt(a, v, t)
    print(f"  Theoretical: acc={p_th:.4f}, RT={rt_th*1000:.1f}ms")

    data, _ = hddm.generate.gen_rand_data(
        {'a': a, 'v': v, 't': t, 'z': 0.5},
        size=5000, subjs=1, subj_noise=0.0
    )
    stats = empirical_stats(data)
    diff = stats['acc'] - p_th
    print(f"  Empirical: acc={stats['acc']:.4f}, RT_mean={stats['rt_mean']*1000:.1f}ms")
    print(f"  Diff from theory: {diff:+.4f}")
    if abs(diff) < 0.02:
        print("  STATUS: ✓ PASS (theoretical match)")
    elif abs(diff) < 0.05:
        print("  STATUS: ~ MARGINAL")
    else:
        print("  STATUS: ✗ FAIL (still mismatched)")
    results['test_a'] = {'theory_acc': p_th, 'empirical_acc': stats['acc'], 'diff': diff}

    # Test B: a=2.0, v=1.0, t=0.3 (HDDM standard reference)
    print("\nTest B: a=2.0, v=1.0, t=0.3 (HDDM standard reference)")
    a, v, t = 2.0, 1.0, 0.3
    p_th = theoretical_acc(a, v)
    rt_th = theoretical_rt(a, v, t)
    print(f"  Theoretical: acc={p_th:.4f}, RT={rt_th*1000:.1f}ms")

    data, _ = hddm.generate.gen_rand_data(
        {'a': a, 'v': v, 't': t, 'z': 0.5},
        size=5000, subjs=1, subj_noise=0.0
    )
    stats = empirical_stats(data)
    diff = stats['acc'] - p_th
    print(f"  Empirical: acc={stats['acc']:.4f}, RT_mean={stats['rt_mean']*1000:.1f}ms")
    print(f"  Diff from theory: {diff:+.4f}")
    if abs(diff) < 0.02:
        print("  STATUS: ✓ PASS")
    else:
        print("  STATUS: ✗ FAIL")
    results['test_b'] = {'theory_acc': p_th, 'empirical_acc': stats['acc'], 'diff': diff}

    # Conclusion
    print("\n" + "=" * 70)
    if abs(results['test_a']['diff']) < 0.02 and abs(results['test_b']['diff']) < 0.02:
        print("CONCLUSION: ✓ Downgrade successful. Proceed with full grid.")
    else:
        print("CONCLUSION: ✗ Downgrade did not fix the issue.")
        print("  → Try Option 2 (rebuild Docker image with pinned dependencies)")
    print("=" * 70)

    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'verify_downgrade_results.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nSaved: {out_path}")


if __name__ == '__main__':
    main()
