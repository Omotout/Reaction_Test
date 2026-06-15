"""
共通ユーティリティ関数 (stim-coding版、実測ベース)

真値とSUBJ_VARはプレ実験 (10人×80試行) のHDDMStimCoding推定値ベース:
  - a = 1.736, v = 5.205, t = 0.217 (Control 群レベル)
  - 経験的SD: a_sd=0.871, v_sd=1.387, t_sd=0.005

EMS仮説: a, v は変えない、t_er を 8ms 短縮する
  → RT短縮の機序を「慎重さの低下」ではなく「非決定時間の短縮」と説明

評価項目 (Tomoaki さん整理):
  1. RT短縮 (経験的差のHDI)
  2. 正答率非劣性 (Wald型Z検定、片側)
  3. a 同等性 (ROPE + 95% HDI)
  4. v 同等性 (ROPE + 95% HDI)
  5. t_er 短縮 (HDIが負側)
  6. P_P|D (Szul et al. 2020): HDIのうちROPE内に含まれる割合

ROPE設定の二本立て:
  - 固定ROPE: 事前計画用 (サンプルサイズ感度分析)
  - empirical ROPE (Szul流): 各反復のMCMCチェーンから自動計算
"""
import math
import numpy as np
import pandas as pd
from scipy import stats


# =====================================================
# 真値設定 (プレ実験HDDMStimCoding推定値ベース)
# =====================================================
TRUE_PARAMS = {
    'control': {
        'a': 1.736,
        'v': 5.205,
        't': 0.217,
        'z': 0.5,
    },
    'ems': {
        'a': 1.736,        # 同等を仮定
        'v': 5.205,        # 同等を仮定
        't': 0.209,        # 8ms短縮
        'z': 0.5,
    }
}

SUBJ_VAR = {
    'a_sd': 0.871,
    'v_sd': 1.387,
    't_sd': 0.005,
}

PARAM_LOWER = {
    'a': 0.3,
    'v': 0.5,
    't': 0.05,
}

# =====================================================
# 固定ROPE (事前計画用)
# =====================================================
ROPE = {
    'a': (-0.10, 0.10),
    'v': (-0.30, 0.30),
    't': (-0.005, 0.005),
    'acc_diff': (-0.03, np.inf),
    'rt_diff_ms': (-np.inf, 5),
}

GRID = {
    'n_subj': [15, 20, 25],
    'n_trials': [80, 120],
    'n_reps': 30,
}


def generate_subject_params(group, n_subj, seed=None):
    rng = np.random.default_rng(seed)
    base = TRUE_PARAMS[group]
    subj_params = []
    for i in range(n_subj):
        a = max(PARAM_LOWER['a'], rng.normal(base['a'], SUBJ_VAR['a_sd']))
        v = max(PARAM_LOWER['v'], rng.normal(base['v'], SUBJ_VAR['v_sd']))
        t = max(PARAM_LOWER['t'], rng.normal(base['t'], SUBJ_VAR['t_sd']))
        subj_params.append({'a': a, 'v': v, 't': t, 'z': base['z']})
    return subj_params


# =====================================================
# 基本関数
# =====================================================
def hdi(samples, prob=0.95):
    """Highest Density Interval (HDI)"""
    sorted_samples = np.sort(samples)
    n = len(sorted_samples)
    interval_size = int(np.floor(prob * n))
    n_intervals = n - interval_size
    interval_widths = sorted_samples[interval_size:] - sorted_samples[:n_intervals]
    min_idx = np.argmin(interval_widths)
    return sorted_samples[min_idx], sorted_samples[min_idx + interval_size]


# =====================================================
# Szul et al. (2020) 流のempirical ROPE
# =====================================================
def empirical_rope_szul(samples_ctrl, samples_ems, prob=0.95):
    """
    Szul et al. (2020, Behav Res Methods) の方法でROPEを計算。

    各条件のMCMCチェーンから odd vs even サンプルの差分分布を作り、
    その95% HDIを「無視できる値」とみなす。
    両条件の95% HDIのうち、より広い方をROPE境界とする。

    Parameters
    ----------
    samples_ctrl, samples_ems : np.ndarray
        各条件の事後MCMCサンプル

    Returns
    -------
    rope_low, rope_high : float
        empirical ROPEの境界
    """
    def chain_internal_hdi(samples, prob):
        """同じチェーンのodd/evenサンプル差から内部ノイズHDIを計算"""
        odd = samples[1::2]
        even = samples[0::2]
        # 長さを揃える
        n = min(len(odd), len(even))
        # ランダムペアリング(順序によるartifactを避ける)
        rng = np.random.default_rng(seed=0)
        even_shuffled = rng.permutation(even[:n])
        diff = odd[:n] - even_shuffled
        return hdi(diff, prob=prob)

    ctrl_lo, ctrl_hi = chain_internal_hdi(samples_ctrl, prob)
    ems_lo, ems_hi = chain_internal_hdi(samples_ems, prob)

    # 両方の95% HDIのうち、より広い方を採用
    rope_low = min(ctrl_lo, ems_lo)
    rope_high = max(ctrl_hi, ems_hi)

    return rope_low, rope_high


def p_pd_szul(diff_samples, rope_low, rope_high, prob=0.95):
    """
    Szul et al. (2020) の P_P|D を計算。

      = HDIのうちROPE内に含まれる割合
      = 1: HDI全体がROPEに包含 (帰無仮説を受け入れ)
      = 0: HDIがROPEと完全に分離 (帰無仮説を棄却)

    Parameters
    ----------
    diff_samples : np.ndarray
        群差の事後サンプル
    rope_low, rope_high : float
        ROPE境界
    prob : float
        HDIの確率(デフォルト0.95)
    """
    hdi_low, hdi_high = hdi(diff_samples, prob=prob)
    hdi_width = hdi_high - hdi_low
    if hdi_width <= 0:
        return float('nan')

    # HDIとROPEの重なり区間を計算
    overlap_lo = max(hdi_low, rope_low)
    overlap_hi = min(hdi_high, rope_high)
    overlap_width = max(0, overlap_hi - overlap_lo)

    return float(overlap_width / hdi_width)


# =====================================================
# 判定関数
# =====================================================
def rope_decision(diff_samples, rope_low, rope_high, prob=0.95):
    """
    ROPE+HDI判定 (Kruschke式)
      'equivalent': HDI完全包含
      'reject':     HDI完全分離
      'undecided':  部分重複
    """
    hdi_low, hdi_high = hdi(diff_samples, prob=prob)
    if hdi_low >= rope_low and hdi_high <= rope_high:
        return 'equivalent'
    elif hdi_high < rope_low or hdi_low > rope_high:
        return 'reject'
    else:
        return 'undecided'


def superiority_decision(diff_samples, rope_low, rope_high, direction='positive', prob=0.95):
    """優越性判定 (HDIが片側でROPEを完全に超えるか)"""
    hdi_low, hdi_high = hdi(diff_samples, prob=prob)
    if direction == 'positive':
        if hdi_low > rope_high:
            return 'superior'
        elif hdi_high < rope_low:
            return 'inferior'
    elif direction == 'negative':
        if hdi_high < rope_low:
            return 'superior'
        elif hdi_low > rope_high:
            return 'inferior'
    return 'undecided'


def p_in_rope_posterior(samples, rope_low, rope_high):
    """事後分布のうちROPE内にある確率質量(参考用、Szul P_P|Dとは別物)"""
    in_rope = (samples >= rope_low) & (samples <= rope_high)
    return float(in_rope.mean())


def accuracy_noninferiority(acc_ems, acc_ctrl, n_ems, n_ctrl, margin=0.03, alpha=0.025):
    """正答率の非劣性検定 (Wald型 Z検定, 片側)"""
    diff = acc_ems - acc_ctrl
    se = np.sqrt(acc_ems * (1 - acc_ems) / n_ems + acc_ctrl * (1 - acc_ctrl) / n_ctrl)
    if se == 0:
        return {'diff': diff, 'se': 0, 'z': np.inf, 'p_value': 0,
                'noninferior': diff > -margin, 'ci_lower': diff}
    z = (diff + margin) / se
    p = 1 - stats.norm.cdf(z)
    return {
        'diff': diff, 'se': se, 'z': z, 'p_value': p,
        'noninferior': p < alpha,
        'ci_lower': diff - 1.96 * se,
    }


def summarize_grid_results(results_df):
    """グリッド結果から各セルの判定確率を集計"""
    agg_dict = {
        'a_equiv_rate':      ('a_decision', lambda x: (x == 'equivalent').mean()),
        'v_equiv_rate':      ('v_decision', lambda x: (x == 'equivalent').mean()),
        't_super_rate':      ('t_decision', lambda x: (x == 'superior').mean()),
        'acc_noninf_rate':   ('acc_noninf', 'mean'),
        'rt_short_rate':     ('rt_shortened', 'mean'),
        'a_post_sd_mean':    ('a_post_sd', 'mean'),
        'a_diff_mean':       ('a_diff_mean', 'mean'),
        'n_reps':            ('rep_id', 'count'),
    }
    # P_P|D系列とempirical ROPE系列が存在すれば追加
    optional_cols = {
        'a_p_pd_mean':       ('a_p_pd', 'mean'),
        'v_p_pd_mean':       ('v_p_pd', 'mean'),
        't_p_pd_mean':       ('t_p_pd', 'mean'),
        'a_equiv_emp_rate':  ('a_decision_emp', lambda x: (x == 'equivalent').mean()),
        'v_equiv_emp_rate':  ('v_decision_emp', lambda x: (x == 'equivalent').mean()),
        'a_rope_emp_width':  ('a_rope_emp_width', 'mean'),
        'v_rope_emp_width':  ('v_rope_emp_width', 'mean'),
        't_rope_emp_width':  ('t_rope_emp_width', 'mean'),
    }
    for k, v in optional_cols.items():
        if v[0] in results_df.columns:
            agg_dict[k] = v
    summary = results_df.groupby(['n_subj', 'n_trials']).agg(**agg_dict).round(4)
    return summary
