"""
diagnose_scale_v2.py

スケール問題を切り分ける詳細診断。
複数のデータ生成方式を試して、どれが理論値と一致するかを特定。

実行: python diagnose_scale_v2.py
"""

import math
import warnings
import sys
import os
import json

import numpy as np
import pandas as pd
import hddm

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def theoretical_acc(a, v, s=1.0):
    return 1.0 / (1.0 + math.exp(-2 * a * v / s**2))


def theoretical_rt(a, v, t, s=1.0):
    av = a * v / s**2
    DT = (a / (2 * v)) * math.tanh(av)
    return DT + t


def empirical_stats(data):
    """生成データから経験的acc, RTを計算"""
    return {
        'acc': float(data['response'].mean()),
        'rt_mean': float(data['rt'].mean()),
        'rt_median': float(data['rt'].median()),
        'n': len(data),
    }


def main():
    print("=" * 80)
    print("DIAGNOSTIC v2: Scale issue isolation")
    print("=" * 80)

    a_true, v_true, t_true = 0.676, 1.625, 0.204
    p_th = theoretical_acc(a_true, v_true)
    rt_th = theoretical_rt(a_true, v_true, t_true)
    print(f"\nTrue: a={a_true}, v={v_true}, t={t_true}")
    print(f"Theoretical: acc={p_th:.4f}, RT={rt_th*1000:.1f}ms\n")

    results = {}

    # ===========================================
    # Method 1: gen_rand_data flat dict (現状の方法)
    # ===========================================
    print("=" * 80)
    print("Method 1: hddm.generate.gen_rand_data with flat dict")
    print("=" * 80)
    params1 = {'a': a_true, 'v': v_true, 't': t_true, 'z': 0.5}
    data1, p1 = hddm.generate.gen_rand_data(
        params1, size=5000, subjs=1, subj_noise=0.0
    )
    print(f"  Returned params: {p1}")
    stats1 = empirical_stats(data1)
    print(f"  Empirical: acc={stats1['acc']:.4f}, RT_mean={stats1['rt_mean']*1000:.1f}ms")
    print(f"  acc diff from theory: {stats1['acc']-p_th:+.4f}")
    results['method1_flat'] = {'stats': stats1, 'returned_params': str(p1)}

    # ===========================================
    # Method 2: gen_rand_data with condition wrapper
    # ===========================================
    print("\n" + "=" * 80)
    print("Method 2: gen_rand_data with single condition wrapper")
    print("=" * 80)
    params2 = {'cond1': {'a': a_true, 'v': v_true, 't': t_true, 'z': 0.5}}
    data2, p2 = hddm.generate.gen_rand_data(
        params2, size=5000, subjs=1, subj_noise=0.0
    )
    print(f"  Returned params: {p2}")
    stats2 = empirical_stats(data2)
    print(f"  Empirical: acc={stats2['acc']:.4f}, RT_mean={stats2['rt_mean']*1000:.1f}ms")
    print(f"  acc diff from theory: {stats2['acc']-p_th:+.4f}")
    results['method2_cond'] = {'stats': stats2, 'returned_params': str(p2)}

    # ===========================================
    # Method 3: hddm.generate.gen_rts (low-level API)
    # ===========================================
    print("\n" + "=" * 80)
    print("Method 3: hddm.generate.gen_rts (low-level)")
    print("=" * 80)
    rts = hddm.generate.gen_rts(
        size=5000,
        a=a_true, v=v_true, t=t_true, z=0.5,
        intra_sv=1.0,
        method='cdf',
    )
    # gen_rtsはRTのみを返す(符号で正誤を示す)
    if isinstance(rts, np.ndarray):
        df3 = pd.DataFrame({'rt_signed': rts})
    else:
        df3 = pd.DataFrame(rts)
    if 'rt' in df3.columns and 'response' in df3.columns:
        stats3 = empirical_stats(df3)
    else:
        # 符号でresponse判定: rt > 0 → 正答(upper boundary)
        rts_arr = df3['rt_signed'].values if 'rt_signed' in df3.columns else df3.iloc[:, 0].values
        df3 = pd.DataFrame({
            'rt': np.abs(rts_arr),
            'response': (rts_arr > 0).astype(int),
        })
        stats3 = empirical_stats(df3)
    print(f"  Empirical: acc={stats3['acc']:.4f}, RT_mean={stats3['rt_mean']*1000:.1f}ms")
    print(f"  acc diff from theory: {stats3['acc']-p_th:+.4f}")
    results['method3_gen_rts'] = {'stats': stats3}

    # ===========================================
    # Method 4: HDDM標準テスト値で生成 (a=2.0, v=1.0, t=0.3)
    # ===========================================
    print("\n" + "=" * 80)
    print("Method 4: Reference test with HDDM standard values (a=2.0, v=1.0, t=0.3)")
    print("=" * 80)
    a_ref, v_ref, t_ref = 2.0, 1.0, 0.3
    p_ref = theoretical_acc(a_ref, v_ref)
    rt_ref = theoretical_rt(a_ref, v_ref, t_ref)
    print(f"  True: a={a_ref}, v={v_ref}, t={t_ref}")
    print(f"  Theoretical: acc={p_ref:.4f}, RT={rt_ref*1000:.1f}ms")

    params4 = {'a': a_ref, 'v': v_ref, 't': t_ref, 'z': 0.5}
    data4, _ = hddm.generate.gen_rand_data(
        params4, size=5000, subjs=1, subj_noise=0.0
    )
    stats4 = empirical_stats(data4)
    print(f"  Empirical: acc={stats4['acc']:.4f}, RT_mean={stats4['rt_mean']*1000:.1f}ms")
    print(f"  acc diff from theory: {stats4['acc']-p_ref:+.4f}")
    results['method4_reference'] = {
        'stats': stats4,
        'theory': {'acc': p_ref, 'rt': rt_ref}
    }

    # ===========================================
    # Method 5: low a, high v (small a counter-test)
    # 別のスケール領域で試す: a=0.3, v=3.0
    # ===========================================
    print("\n" + "=" * 80)
    print("Method 5: Small-a test (a=0.3, v=3.0) - similar product to original")
    print("=" * 80)
    a_s, v_s, t_s = 0.3, 3.0, 0.2
    p_s = theoretical_acc(a_s, v_s)
    rt_s = theoretical_rt(a_s, v_s, t_s)
    print(f"  True: a={a_s}, v={v_s}, t={t_s}")
    print(f"  Theoretical: acc={p_s:.4f}, RT={rt_s*1000:.1f}ms")

    data5, _ = hddm.generate.gen_rand_data(
        {'a': a_s, 'v': v_s, 't': t_s, 'z': 0.5}, size=5000, subjs=1, subj_noise=0.0
    )
    stats5 = empirical_stats(data5)
    print(f"  Empirical: acc={stats5['acc']:.4f}, RT_mean={stats5['rt_mean']*1000:.1f}ms")
    print(f"  acc diff from theory: {stats5['acc']-p_s:+.4f}")
    results['method5_small_a'] = {
        'stats': stats5,
        'theory': {'acc': p_s, 'rt': rt_s}
    }

    # ===========================================
    # Method 6: a を 2倍にして生成
    # ===========================================
    print("\n" + "=" * 80)
    print("Method 6: Original v with 2*a (test scaling hypothesis)")
    print("=" * 80)
    a_double = a_true * 2
    p_double_th = theoretical_acc(a_double, v_true)
    rt_double_th = theoretical_rt(a_double, v_true, t_true)
    print(f"  True (interpreted): a={a_double}, v={v_true}, t={t_true}")
    print(f"  Theoretical: acc={p_double_th:.4f}, RT={rt_double_th*1000:.1f}ms")

    data6, _ = hddm.generate.gen_rand_data(
        {'a': a_double, 'v': v_true, 't': t_true, 'z': 0.5}, size=5000, subjs=1, subj_noise=0.0
    )
    stats6 = empirical_stats(data6)
    print(f"  Empirical: acc={stats6['acc']:.4f}, RT_mean={stats6['rt_mean']*1000:.1f}ms")
    print(f"  acc diff from theory (with 2a): {stats6['acc']-p_double_th:+.4f}")
    print(f"  acc diff from original theory: {stats6['acc']-p_th:+.4f}")
    results['method6_double_a'] = {
        'stats': stats6,
        'theory_with_2a': {'acc': p_double_th, 'rt': rt_double_th}
    }

    # ===========================================
    # Summary diagnosis
    # ===========================================
    print("\n" + "=" * 80)
    print("DIAGNOSIS")
    print("=" * 80)

    deltas = {
        'method1_flat': stats1['acc'] - p_th,
        'method2_cond': stats2['acc'] - p_th,
        'method4_reference': stats4['acc'] - p_ref,
        'method5_small_a': stats5['acc'] - p_s,
    }

    print("Empirical accuracy vs theoretical (closer to 0 is better):")
    for k, v in deltas.items():
        print(f"  {k}: {v:+.4f}")

    if abs(deltas['method4_reference']) < 0.02:
        print("\n✓ Method 4 (a=2.0, v=1.0) matches theory → HDDM works fine for standard values")
        print("  → Issue is specific to small-a values like a=0.676")
    if abs(deltas['method5_small_a']) > 0.05:
        print("\n✗ Method 5 also fails → Bug affects ALL small-a values, not just our case")

    # 比較テスト: HDDM gen_rand_dataのバージョン情報
    print("\nHDDM version:", hddm.__version__)

    # 結果保存
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'diagnose_v2_results.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nSaved: {out_path}")


if __name__ == '__main__':
    main()
