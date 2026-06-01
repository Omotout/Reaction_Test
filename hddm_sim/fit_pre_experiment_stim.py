"""
fit_pre_experiment_stim.py

プレ実験データを HDDMStimCoding でフィットし、被験者ごとの a, v, t を抽出。
左右ランダム刺激 (CRT task) に対して理論的に正しい方式。

stim-coding の特徴:
  - response 列は左右(0=Left, 1=Right)を意味する
  - stim_col で各試行の刺激方向を指定
  - 正答方向にドリフトが向くように内部で v の符号を反転
  - 結果として v は「刺激方向への意思決定の強さ」を意味する
  - a, t は accuracy-coding と同じ意味

実行 (Docker):
    docker run --rm \
      -v "C:\\Users\\tomoa\\Unity\\Projects\\Reaction_Test:/work" \
      -w /work/hddm_sim \
      hcp4715/hddm:latest \
      python fit_pre_experiment_stim.py

出力:
  - pre_experiment_stim_subjlevel.csv
  - pre_experiment_stim_subj_var.json
"""

import json
import os
import sys
import warnings

import numpy as np
import pandas as pd
import hddm


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(SCRIPT_DIR, 'pre_experiment_data.csv')

N_SAMPLES = 5000
N_BURN = 2000
N_THIN = 2


def main():
    print("=" * 70)
    print("Fit HDDMStimCoding on pre-experiment data (CRT task)")
    print("=" * 70)

    if not os.path.exists(DATA_PATH):
        print(f"ERROR: {DATA_PATH} not found.")
        sys.exit(1)

    df = pd.read_csv(DATA_PATH)
    print(f"Loaded {len(df)} trials from {df['subj_idx'].nunique()} subjects")
    print(f"  Accuracy: {df['response'].mean():.4f}")
    print(f"  Mean RT: {df['rt'].mean()*1000:.1f} ms")
    print()

    # ===========================================
    # Stim-coding用にデータ整形
    # response列: ResponseSide(Left=0, Right=1)
    # ===========================================
    stim_to_int = {'Left': 0, 'Right': 1}
    df['stim_int'] = df['stim'].map(stim_to_int)

    # ResponseSide を復元: IsCorrect=1 → stim と同じ、IsCorrect=0 → 反対
    df['response_lr'] = np.where(
        df['response'] == 1,
        df['stim_int'],
        1 - df['stim_int']
    )

    # HDDMStimCoding 形式: stim 列を 0/1 (int) に
    df_fit = df[['subj_idx', 'rt']].copy()
    df_fit['response'] = df['response_lr'].astype(int)
    df_fit['stim'] = df['stim_int'].astype(int)  # 0=Left, 1=Right (intのほうが安全)

    print(f"Sanity check (stim-coded):")
    print(f"  Response 'Left' (0):  {(df_fit['response']==0).sum()} trials")
    print(f"  Response 'Right' (1): {(df_fit['response']==1).sum()} trials")
    print(f"  Stim 'Left' (0):  {(df_fit['stim']==0).sum()} trials")
    print(f"  Stim 'Right' (1): {(df_fit['stim']==1).sum()} trials")
    print(f"  Implied accuracy: {(df_fit['response']==df_fit['stim']).mean():.4f}")
    print()

    # ===========================================
    # HDDMStimCoding でフィット
    # ===========================================
    print(f"Fitting HDDMStimCoding (samples={N_SAMPLES}, burn={N_BURN}, thin={N_THIN})...")
    print("This may take 5-15 minutes.")
    print()

    with warnings.catch_warnings():
        warnings.simplefilter('ignore')

        # 公式ドキュメントの推奨パターン
        # include で a,v,t を明示。z は推定しない(無バイアス想定)
        # drift_criterion はデフォルト False のまま (dc 推定しない)
        model = hddm.HDDMStimCoding(
            df_fit,
            include=['v', 'a', 't'],
            stim_col='stim',
            split_param='v',
        )
        model.find_starting_values()
        model.sample(N_SAMPLES, burn=N_BURN, thin=N_THIN, dbname=None, db='ram')

    # ===========================================
    # 群レベル事後分布
    # ===========================================
    a_group = model.nodes_db.node['a'].trace()
    v_group = model.nodes_db.node['v'].trace()
    t_group = model.nodes_db.node['t'].trace()

    a_group_std = model.nodes_db.node['a_std'].trace()
    v_group_std = model.nodes_db.node['v_std'].trace()
    t_group_std = model.nodes_db.node['t_std'].trace()

    # ===========================================
    # 被験者レベル事後分布
    # ===========================================
    n_subj = df_fit['subj_idx'].nunique()
    subj_estimates = []

    def get_subj_node(param, i):
        candidates = [
            f'{param}_subj.{i}',
            f'{param}_subj({i})',
        ]
        for fmt in candidates:
            try:
                return model.nodes_db.node[fmt].trace()
            except KeyError:
                continue
        for name in model.nodes_db.node.keys():
            if name.startswith(f'{param}_subj') and (
                name.endswith(f'.{i}') or f'({i})' in name
            ):
                return model.nodes_db.node[name].trace()
        raise KeyError(f"Could not find {param}_subj for index {i}")

    for i in range(n_subj):
        try:
            a_i = get_subj_node('a', i).mean()
            v_i = get_subj_node('v', i).mean()
            t_i = get_subj_node('t', i).mean()
            subj_estimates.append({
                'subj_idx': i,
                'a': float(a_i),
                'v': float(v_i),
                't': float(t_i),
            })
        except KeyError as e:
            print(f"  Could not extract subj.{i}: {e}")

    if not subj_estimates:
        print("\nDEBUG: Available node names:")
        for name in sorted(model.nodes_db.node.keys()):
            print(f"  {name}")
        sys.exit(1)

    subj_df = pd.DataFrame(subj_estimates)

    id_map = df.groupby('subj_idx')['subject_id'].first().to_dict()
    subj_df['subject_id'] = subj_df['subj_idx'].map(id_map).astype(str).str.zfill(3)
    subj_df = subj_df[['subj_idx', 'subject_id', 'a', 'v', 't']]

    out_path = os.path.join(SCRIPT_DIR, 'pre_experiment_stim_subjlevel.csv')
    subj_df.to_csv(out_path, index=False)

    # ===========================================
    # 経験的 SD
    # ===========================================
    a_emp_sd = subj_df['a'].std(ddof=1)
    v_emp_sd = subj_df['v'].std(ddof=1)
    t_emp_sd = subj_df['t'].std(ddof=1)

    a_emp_mean = subj_df['a'].mean()
    v_emp_mean = subj_df['v'].mean()
    t_emp_mean = subj_df['t'].mean()

    # ===========================================
    # 結果表示
    # ===========================================
    print("\n" + "=" * 70)
    print("Group-level posterior (HDDMStimCoding)")
    print("=" * 70)
    print(f"  a:  mean={a_group.mean():.4f}, post_sd={a_group.std():.4f}")
    print(f"  v:  mean={v_group.mean():.4f}, post_sd={v_group.std():.4f}  (drift toward stimulus)")
    print(f"  t:  mean={t_group.mean():.4f}, post_sd={t_group.std():.4f}")
    print()
    print(f"  Between-subj SD posteriors:")
    print(f"    a_std={a_group_std.mean():.4f}, v_std={v_group_std.mean():.4f}, t_std={t_group_std.mean():.4f}")

    print("\n" + "=" * 70)
    print("Subject-level estimates")
    print("=" * 70)
    print(subj_df.to_string(index=False))

    print("\n" + "=" * 70)
    print("Empirical between-subject SDs (sample SD across subjects)")
    print("=" * 70)
    print(f"  a_emp_sd = {a_emp_sd:.4f}  (mean a = {a_emp_mean:.4f})")
    print(f"  v_emp_sd = {v_emp_sd:.4f}  (mean v = {v_emp_mean:.4f})  ← drift toward stim")
    print(f"  t_emp_sd = {t_emp_sd:.4f}  (mean t = {t_emp_mean:.4f})")

    # ===========================================
    # 結果保存
    # ===========================================
    results = {
        'method': 'HDDMStimCoding',
        'group_level': {
            'a_mean': float(a_group.mean()), 'a_post_sd': float(a_group.std()),
            'v_mean': float(v_group.mean()), 'v_post_sd': float(v_group.std()),
            't_mean': float(t_group.mean()), 't_post_sd': float(t_group.std()),
        },
        'between_subj_sd_posterior': {
            'a_std': float(a_group_std.mean()),
            'v_std': float(v_group_std.mean()),
            't_std': float(t_group_std.mean()),
        },
        'empirical_subj_var': {
            'a_sd': float(a_emp_sd),
            'v_sd': float(v_emp_sd),
            't_sd': float(t_emp_sd),
        },
        'empirical_means': {
            'a': float(a_emp_mean),
            'v': float(v_emp_mean),
            't': float(t_emp_mean),
        },
        'n_subjects': int(n_subj),
        'n_trials_total': int(len(df_fit)),
    }

    out_json = os.path.join(SCRIPT_DIR, 'pre_experiment_stim_subj_var.json')
    with open(out_json, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nSaved:")
    print(f"  {out_path}")
    print(f"  {out_json}")


if __name__ == '__main__':
    main()
