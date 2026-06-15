"""
01_simulate_data.py

stim-coding形式のCRTタスクデータを生成。

データ構造:
  - 各試行で左右ランダムに刺激 (stim=0:Left, 1:Right)
  - 被験者は刺激方向にドリフトして反応
  - response=刺激と一致なら正答

stim-coding規約:
  - 内部DDM生成では、上境界=正答、下境界=誤答 として通常通り生成
  - その後、stim=Leftの試行は response 列を反転 (response = 1-response)
    → response=0/1 が「Left/Right」を意味するように
  - stim 列を保持してHDDMStimCodingで再認識させる
"""

import numpy as np
import pandas as pd
import hddm
from utils import generate_subject_params, TRUE_PARAMS


def simulate_one_subject(params, n_trials, seed=None):
    """
    1人分のstim-codingデータを生成
    Returns: DataFrame with columns [rt, response, stim]
      - response: 0=Left, 1=Right
      - stim: 0=Left, 1=Right
    """
    rng = np.random.default_rng(seed)

    # 試行ごとの刺激方向をランダム決定 (0=Left, 1=Right)
    stims = rng.integers(0, 2, size=n_trials)

    # まず正答コーディングでDDMから生成 (response=1=正答, 0=誤答)
    data, _ = hddm.generate.gen_rand_data(
        {'a': params['a'], 'v': params['v'], 't': params['t'], 'z': params['z']},
        size=n_trials,
        subjs=1,
        subj_noise=0.0,
    )
    correct = data['response'].astype(int).values
    rt = data['rt'].values

    # stim-coding形式に変換:
    # response = stim if correct else 1-stim
    response_lr = np.where(correct == 1, stims, 1 - stims)

    return pd.DataFrame({
        'rt': rt,
        'response': response_lr.astype(int),  # 0=Left, 1=Right
        'stim': stims.astype(int),             # 0=Left, 1=Right
    })


def simulate_one_group(group, n_subj, n_trials, seed=None):
    """
    1群のデータを生成
    """
    rng = np.random.default_rng(seed)
    subj_params_list = generate_subject_params(group, n_subj, seed=seed)

    all_data = []
    for subj_idx, params in enumerate(subj_params_list):
        subj_seed = rng.integers(0, 1_000_000)
        df_subj = simulate_one_subject(params, n_trials, seed=subj_seed)
        df_subj['subj_idx'] = subj_idx
        df_subj['group'] = group
        all_data.append(df_subj)

    return pd.concat(all_data, ignore_index=True)


def simulate_two_groups(n_subj_per_group, n_trials, seed=None):
    """
    Control + EMSの両群データを生成
    """
    rng = np.random.default_rng(seed)
    seed_ctrl = rng.integers(0, 1_000_000)
    seed_ems = rng.integers(0, 1_000_000)

    df_ctrl = simulate_one_group('control', n_subj_per_group, n_trials, seed=seed_ctrl)
    df_ems = simulate_one_group('ems', n_subj_per_group, n_trials, seed=seed_ems)

    # 被験者IDが群間で重複しないようにオフセット
    df_ems['subj_idx'] = df_ems['subj_idx'] + n_subj_per_group

    df = pd.concat([df_ctrl, df_ems], ignore_index=True)
    df = df.rename(columns={'group': 'condition'})
    return df


def compute_summary_stats(df):
    """
    各群の経験的な平均RT・正答率を計算
    正答 = response == stim
    """
    df = df.copy()
    df['correct'] = (df['response'] == df['stim']).astype(int)
    summary = df.groupby('condition').agg(
        mean_rt=('rt', 'mean'),
        median_rt=('rt', 'median'),
        accuracy=('correct', 'mean'),
        n_trials=('rt', 'count'),
        n_subj=('subj_idx', 'nunique'),
    ).round(3)
    return summary


if __name__ == '__main__':
    print("=" * 60)
    print("Smoke test: 15 subj × 80 trials, both groups")
    print("=" * 60)
    df = simulate_two_groups(n_subj_per_group=15, n_trials=80, seed=42)
    print(f"Total rows: {len(df)}")
    print(f"Columns: {df.columns.tolist()}")
    print(f"Conditions: {df['condition'].unique()}")
    print(f"Subjects per condition: {df.groupby('condition')['subj_idx'].nunique().to_dict()}")
    print()
    print("Stim/Response balance:")
    print(df.groupby(['condition', 'stim'])['response'].agg(['count', 'mean']).round(3))
    print()
    print("Group summary:")
    print(compute_summary_stats(df))
    print()
    print("First 5 rows:")
    print(df.head())
