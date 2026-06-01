"""
diagnose_scale.py

データ生成と推定のスケール整合性を診断する。

実行内容:
1. 真値 a=0.676, v=1.625 でデータ生成
2. 生データの正答率と平均RTを実測 (理論値と比較)
3. HDDMでフィット → 推定 a, v が真値に戻るか確認
4. もし真値の半分くらいで推定されていれば、データ生成段階のスケール問題
   もし真値通りなら、別要因(stimcoding等)

実行: python diagnose_scale.py
出力: diagnose_results.json + コンソール出力
"""

import json
import math
import warnings
import sys
import os

import numpy as np
import pandas as pd
import hddm

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import TRUE_PARAMS, generate_subject_params

import importlib.util
spec = importlib.util.spec_from_file_location(
    "sim_data",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "01_simulate_data.py")
)
sim_data = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sim_data)


def theoretical_acc(a, v, s=1.0, z=0.5):
    """DDMの理論正答率 (z=0.5の場合)"""
    return 1.0 / (1.0 + math.exp(-2 * a * v / s**2))


def theoretical_mean_rt(a, v, t, s=1.0):
    """DDMの理論平均RT (z=0.5の場合)"""
    av = a * v / s**2
    DT = (a / (2 * v)) * math.tanh(av)
    return DT + t


def main():
    print("=" * 70)
    print("DIAGNOSTIC: Data generation & HDDM scale consistency check")
    print("=" * 70)

    # ===========================================
    # 1. 真値の確認
    # ===========================================
    a_true = TRUE_PARAMS['control']['a']
    v_true = TRUE_PARAMS['control']['v']
    t_true = TRUE_PARAMS['control']['t']

    p_theory = theoretical_acc(a_true, v_true)
    rt_theory = theoretical_mean_rt(a_true, v_true, t_true)

    print(f"\nTrue parameters (Control):")
    print(f"  a = {a_true}")
    print(f"  v = {v_true}")
    print(f"  t = {t_true}")
    print(f"\nTheoretical values (s=1, z=0.5):")
    print(f"  acc = {p_theory:.4f}")
    print(f"  mean RT = {rt_theory*1000:.1f} ms")

    # ===========================================
    # 2. 単一被験者・被験者間ばらつきなしでデータ生成
    # ===========================================
    print("\n" + "=" * 70)
    print("Test 1: Single subject, no variability (params used directly)")
    print("=" * 70)

    params_single = {'a': a_true, 'v': v_true, 't': t_true, 'z': 0.5}
    data1, _ = hddm.generate.gen_rand_data(
        params_single, size=2000, subjs=1, subj_noise=0.0
    )
    p_emp1 = data1['response'].mean()
    rt_emp1 = data1['rt'].mean()
    print(f"  Empirical acc: {p_emp1:.4f} (theory: {p_theory:.4f}, diff: {p_emp1-p_theory:+.4f})")
    print(f"  Empirical RT:  {rt_emp1*1000:.1f} ms (theory: {rt_theory*1000:.1f} ms)")

    diagnosis_t1 = "OK" if abs(p_emp1 - p_theory) < 0.02 else "MISMATCH"
    print(f"  Status: {diagnosis_t1}")

    # ===========================================
    # 3. 被験者間ばらつき有りでデータ生成 (実シミュと同じ条件)
    # ===========================================
    print("\n" + "=" * 70)
    print("Test 2: Multi-subject with between-subject variability (actual sim setup)")
    print("=" * 70)

    df_multi = sim_data.simulate_one_group('control', n_subj=20, n_trials=200, seed=42)
    p_emp2 = df_multi['response'].mean()
    rt_emp2 = df_multi['rt'].mean()
    p_per_subj = df_multi.groupby('subj_idx')['response'].mean()
    print(f"  Empirical acc (overall): {p_emp2:.4f}")
    print(f"  Empirical acc (per-subj range): [{p_per_subj.min():.3f}, {p_per_subj.max():.3f}]")
    print(f"  Empirical acc (per-subj SD): {p_per_subj.std():.4f}")
    print(f"  Empirical RT (overall): {rt_emp2*1000:.1f} ms")

    diagnosis_t2 = "OK" if abs(p_emp2 - p_theory) < 0.05 else "MISMATCH"
    print(f"  Status: {diagnosis_t2}")

    # ===========================================
    # 4. HDDMフィット → 推定値が真値に戻るか
    # ===========================================
    print("\n" + "=" * 70)
    print("Test 3: HDDM fit on multi-subject data → recovery of true a, v, t")
    print("=" * 70)

    df_fit = df_multi.copy()
    df_fit['response'] = df_fit['response'].astype(int)

    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        m = hddm.HDDM(df_fit, p_outlier=0.05)
        m.find_starting_values()
        print("  Sampling MCMC (500 samples, takes 1-2 min)...")
        m.sample(500, burn=200, dbname=None, db='ram')

    a_est = m.nodes_db.node['a'].trace().mean()
    v_est = m.nodes_db.node['v'].trace().mean()
    t_est = m.nodes_db.node['t'].trace().mean()

    print(f"\n  Estimated (group-level mean):")
    print(f"    a = {a_est:.3f} (true: {a_true:.3f}, ratio: {a_est/a_true:.3f})")
    print(f"    v = {v_est:.3f} (true: {v_true:.3f}, ratio: {v_est/v_true:.3f})")
    print(f"    t = {t_est:.3f} (true: {t_true:.3f}, ratio: {t_est/t_true:.3f})")

    a_recovery = abs(a_est - a_true) / a_true
    v_recovery = abs(v_est - v_true) / v_true
    t_recovery = abs(t_est - t_true) / t_true

    if a_recovery > 0.20 or v_recovery > 0.20:
        print(f"\n  STATUS: RECOVERY FAILURE (>20% deviation in a or v)")
        print(f"  -> Scale mismatch between data generation and HDDM fitting")
    else:
        print(f"\n  STATUS: RECOVERY OK (<20% deviation)")
        print(f"  -> Scale is consistent. Low empirical accuracy must come from elsewhere.")

    # ===========================================
    # 5. 結論
    # ===========================================
    print("\n" + "=" * 70)
    print("DIAGNOSIS SUMMARY")
    print("=" * 70)

    results = {
        'true_params': {'a': a_true, 'v': v_true, 't': t_true},
        'theoretical_acc': p_theory,
        'theoretical_rt_ms': rt_theory * 1000,
        'test1_single_subj': {
            'empirical_acc': float(p_emp1),
            'empirical_rt_ms': float(rt_emp1 * 1000),
            'status': diagnosis_t1,
        },
        'test2_multi_subj': {
            'empirical_acc': float(p_emp2),
            'empirical_rt_ms': float(rt_emp2 * 1000),
            'per_subj_acc_range': [float(p_per_subj.min()), float(p_per_subj.max())],
            'status': diagnosis_t2,
        },
        'test3_hddm_recovery': {
            'a_est': float(a_est),
            'v_est': float(v_est),
            't_est': float(t_est),
            'a_ratio': float(a_est / a_true),
            'v_ratio': float(v_est / v_true),
            'recovery_ok': a_recovery <= 0.20 and v_recovery <= 0.20,
        },
    }

    # ロジック分岐
    if diagnosis_t1 == "OK" and diagnosis_t2 == "MISMATCH":
        conclusion = ("CONCLUSION: 単一被験者は理論通り、複数被験者で正答率が下がる。\n"
                     "原因: 被験者間ばらつき (SUBJ_VAR['v_sd']=0.30) が大きすぎて、\n"
                     "vが小さい被験者の正答率が大きく下がっている。\n"
                     "対処: SUBJ_VAR['v_sd'] を 0.15 程度に縮小するか、\n"
                     "      v を負にしないため truncated normal を使う。")
    elif diagnosis_t1 == "MISMATCH":
        conclusion = ("CONCLUSION: 単一被験者でも理論値と合わない。\n"
                     "原因: HDDM内部のスケーリングか、gen_rand_dataの引数解釈に問題。\n"
                     "対処: HDDM側のintra_sv パラメータを確認、もしくは a,v を2倍に。")
    elif results['test3_hddm_recovery']['recovery_ok']:
        conclusion = ("CONCLUSION: データ生成は理論通り、HDDM推定もOK。\n"
                     "$a$同等性検定として現状の結果は信頼できる。\n"
                     "$p~0.76$は被験者間ばらつきによる平均化効果。問題なし。")
    else:
        conclusion = ("CONCLUSION: HDDM推定が真値を復元できていない。\n"
                     "対処: バーンインやサンプル数を増やす、もしくは事前分布を確認。")

    print(conclusion)
    results['conclusion'] = conclusion

    # JSON保存
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'diagnose_results.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nSaved: {out_path}")


if __name__ == '__main__':
    main()
