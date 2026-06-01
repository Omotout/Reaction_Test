"""
02_fit_hddm.py

stim-coding版のCRTタスクシミュレーションでHDDMStimCodingフィットを実行。

ROPE設定の二本立て:
  1. 固定ROPE (utils.ROPEに事前定義)        — サンプルサイズ計画用
  2. empirical ROPE (Szul流、各反復で計算)  — 論文化での主解析と整合

評価項目 (Tomoaki さん整理に対応):
  1. RT短縮         : 経験的RT差 (ms単位)
  2. 正答率非劣性   : Wald型Z検定 (片側 -3%)
  3. a 同等性       : 固定ROPE+HDI / empirical ROPE+HDI
  4. v 同等性       : 固定ROPE+HDI / empirical ROPE+HDI
  5. t_er 短縮      : HDIが負側 (固定ROPE基準)
  6. P_P|D          : Szul流 (HDIのうちROPE内割合)
"""

import argparse
import os
import sys
import time
import warnings

import numpy as np
import pandas as pd
import hddm

from utils import (
    ROPE,
    rope_decision,
    superiority_decision,
    accuracy_noninferiority,
    empirical_rope_szul,
    p_pd_szul,
    hdi,
)


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib.util
spec = importlib.util.spec_from_file_location(
    "sim_data", os.path.join(os.path.dirname(os.path.abspath(__file__)), "01_simulate_data.py")
)
sim_data = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sim_data)


def fit_one_replication(n_subj_per_group, n_trials, rep_id, seed_offset=0,
                         n_samples=2000, burn=1000, thin=2, verbose=False):
    """1反復のシミュレーション+フィットを実行"""
    seed = rep_id * 1000 + seed_offset

    # ================================
    # 1. データ生成
    # ================================
    df = sim_data.simulate_two_groups(
        n_subj_per_group=n_subj_per_group,
        n_trials=n_trials,
        seed=seed,
    )

    df['correct'] = (df['response'] == df['stim']).astype(int)
    ctrl = df[df['condition'] == 'control']
    ems = df[df['condition'] == 'ems']

    acc_ctrl = ctrl['correct'].mean()
    acc_ems = ems['correct'].mean()
    rt_ctrl = ctrl['rt'].mean()
    rt_ems = ems['rt'].mean()

    n_ctrl_trials = len(ctrl)
    n_ems_trials = len(ems)

    # ================================
    # 2. HDDMStimCoding フィット
    # ================================
    df_fit = df[['subj_idx', 'rt', 'response', 'stim', 'condition']].copy()
    df_fit['response'] = df_fit['response'].astype(int)
    df_fit['stim'] = df_fit['stim'].astype(int)

    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        model = hddm.HDDMStimCoding(
            df_fit,
            include=['v', 'a', 't'],
            stim_col='stim',
            split_param='v',
            depends_on={'a': 'condition', 'v': 'condition', 't': 'condition'},
        )
        model.find_starting_values()
        t0 = time.time()
        model.sample(n_samples, burn=burn, thin=thin, dbname=None, db='ram')
        elapsed = time.time() - t0

    if verbose:
        print(f"  HDDM fit took {elapsed:.1f}s")

    # ================================
    # 3. 事後分布の取得
    # ================================
    a_ctrl_post = model.nodes_db.node['a(control)'].trace()
    a_ems_post = model.nodes_db.node['a(ems)'].trace()
    v_ctrl_post = model.nodes_db.node['v(control)'].trace()
    v_ems_post = model.nodes_db.node['v(ems)'].trace()
    t_ctrl_post = model.nodes_db.node['t(control)'].trace()
    t_ems_post = model.nodes_db.node['t(ems)'].trace()

    a_diff = a_ems_post - a_ctrl_post
    v_diff = v_ems_post - v_ctrl_post
    t_diff = t_ems_post - t_ctrl_post

    # ================================
    # 4a. 固定ROPEでの判定
    # ================================
    a_decision = rope_decision(a_diff, *ROPE['a'])
    v_decision = rope_decision(v_diff, *ROPE['v'])
    t_decision = superiority_decision(t_diff, *ROPE['t'], direction='negative')

    # ================================
    # 4b. empirical ROPE (Szul流) の計算と判定
    # ================================
    a_rope_emp = empirical_rope_szul(a_ctrl_post, a_ems_post)
    v_rope_emp = empirical_rope_szul(v_ctrl_post, v_ems_post)
    t_rope_emp = empirical_rope_szul(t_ctrl_post, t_ems_post)

    a_decision_emp = rope_decision(a_diff, *a_rope_emp)
    v_decision_emp = rope_decision(v_diff, *v_rope_emp)

    # ================================
    # 4c. P_P|D (Szul流) — empirical ROPE使用
    # ================================
    a_p_pd = p_pd_szul(a_diff, *a_rope_emp)
    v_p_pd = p_pd_szul(v_diff, *v_rope_emp)
    t_p_pd = p_pd_szul(t_diff, *t_rope_emp)

    # ================================
    # 5. 経験的指標
    # ================================
    acc_result = accuracy_noninferiority(
        acc_ems, acc_ctrl, n_ems_trials, n_ctrl_trials,
        margin=0.03, alpha=0.025
    )
    rt_diff_ms = (rt_ems - rt_ctrl) * 1000
    rt_shortened = rt_diff_ms < 0

    # ================================
    # 6. 結果dict
    # ================================
    a_hdi_low, a_hdi_high = hdi(a_diff, prob=0.95)
    v_hdi_low, v_hdi_high = hdi(v_diff, prob=0.95)
    t_hdi_low, t_hdi_high = hdi(t_diff, prob=0.95)

    result = {
        'rep_id': rep_id,
        'n_subj': n_subj_per_group,
        'n_trials': n_trials,
        # 群差事後統計
        'a_diff_mean': float(a_diff.mean()),
        'a_diff_sd': float(a_diff.std()),
        'a_post_sd': float(a_ctrl_post.std()),
        'a_hdi_low': float(a_hdi_low),
        'a_hdi_high': float(a_hdi_high),
        'v_diff_mean': float(v_diff.mean()),
        'v_diff_sd': float(v_diff.std()),
        'v_hdi_low': float(v_hdi_low),
        'v_hdi_high': float(v_hdi_high),
        't_diff_mean': float(t_diff.mean()),
        't_diff_sd': float(t_diff.std()),
        't_hdi_low': float(t_hdi_low),
        't_hdi_high': float(t_hdi_high),
        # 固定ROPEでの判定
        'a_decision': a_decision,
        'v_decision': v_decision,
        't_decision': t_decision,
        # empirical ROPE
        'a_rope_emp_low': float(a_rope_emp[0]),
        'a_rope_emp_high': float(a_rope_emp[1]),
        'a_rope_emp_width': float(a_rope_emp[1] - a_rope_emp[0]),
        'v_rope_emp_low': float(v_rope_emp[0]),
        'v_rope_emp_high': float(v_rope_emp[1]),
        'v_rope_emp_width': float(v_rope_emp[1] - v_rope_emp[0]),
        't_rope_emp_low': float(t_rope_emp[0]),
        't_rope_emp_high': float(t_rope_emp[1]),
        't_rope_emp_width': float(t_rope_emp[1] - t_rope_emp[0]),
        # empirical ROPEでの判定
        'a_decision_emp': a_decision_emp,
        'v_decision_emp': v_decision_emp,
        # P_P|D (Szul流、empirical ROPE使用)
        'a_p_pd': float(a_p_pd),
        'v_p_pd': float(v_p_pd),
        't_p_pd': float(t_p_pd),
        # 経験的指標
        'acc_ctrl': float(acc_ctrl),
        'acc_ems': float(acc_ems),
        'acc_diff': float(acc_ems - acc_ctrl),
        'acc_noninf': bool(acc_result['noninferior']),
        'rt_ctrl_ms': float(rt_ctrl * 1000),
        'rt_ems_ms': float(rt_ems * 1000),
        'rt_diff_ms': float(rt_diff_ms),
        'rt_shortened': bool(rt_shortened),
        # メタ
        'fit_time_sec': elapsed,
    }

    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--n_subj', type=int, default=15)
    parser.add_argument('--n_trials', type=int, default=80)
    parser.add_argument('--rep_id', type=int, default=0)
    parser.add_argument('--n_samples', type=int, default=2000)
    parser.add_argument('--burn', type=int, default=1000)
    args = parser.parse_args()

    print(f"Running single fit: n_subj={args.n_subj}, n_trials={args.n_trials}, rep={args.rep_id}")
    result = fit_one_replication(
        n_subj_per_group=args.n_subj,
        n_trials=args.n_trials,
        rep_id=args.rep_id,
        n_samples=args.n_samples,
        burn=args.burn,
        verbose=True,
    )

    print("\n" + "=" * 60)
    print("Result")
    print("=" * 60)
    for k, v in result.items():
        if isinstance(v, float):
            print(f"  {k}: {v:.4f}")
        else:
            print(f"  {k}: {v}")
