"""
fit_pre_experiment.py

extract_pre_experiment.py が出力した pre_experiment_data.csv を
HDDM でフィットし、被験者ごとの a, v, t 推定値とその経験的SDを取得。
これを utils.py の SUBJ_VAR を更新する根拠にする。

実行: python fit_pre_experiment.py

出力:
  - pre_experiment_hddm_subjlevel.csv : 各被験者の a_i, v_i, t_i 事後平均
  - pre_experiment_subj_var.json : 群レベル平均 + SUBJ_VAR 推奨値

NOTE: HDDM 1.0系のkabukiでは depends_on を空dict {} で渡すとエラーになる
バグがあるため、ダミー condition 列を追加して depends_on={'v': 'condition'}
を明示する(全行 condition='all' なので意味のあるグループ分けはなし)。
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
    print(f"Fit HDDM on pre-experiment data")
    print("=" * 70)

    if not os.path.exists(DATA_PATH):
        print(f"ERROR: {DATA_PATH} not found. Run extract_pre_experiment.py first.")
        sys.exit(1)

    df = pd.read_csv(DATA_PATH)
    print(f"Loaded {len(df)} trials from {df['subj_idx'].nunique()} subjects")
    print(f"  Accuracy: {df['response'].mean():.4f}")
    print(f"  Mean RT: {df['rt'].mean()*1000:.1f} ms")
    print()

    # HDDM標準形式: subj_idx, rt, response (+ ダミーcondition)
    if 'stim' not in df.columns:
        print("ERROR: pre_experiment_data.csv has no 'stim' column.")
        print("Run extract_pre_experiment.py again to regenerate it.")
        sys.exit(1)

    # CRT data should use stimulus coding so Left/Right responses are modeled
    # symmetrically. Fitting correctness-only HDDM inflates a and v here.
    df_fit = df[['subj_idx', 'stim', 'rt', 'response']].copy()
    df_fit['response'] = df_fit['response'].astype(int)
    # kabukiバグ回避: depends_on が空だとエラーになるので、単一値のダミー条件を追加

    # ===========================================
    # HDDM フィット (階層、被験者効果あり)
    # ===========================================
    print(f"Fitting HDDM (samples={N_SAMPLES}, burn={N_BURN}, thin={N_THIN})...")
    print("This may take 5-15 minutes.")
    print()

    with warnings.catch_warnings():
        warnings.simplefilter('ignore')

        # ダミー condition で a, v, t すべて分割 (実質1グループなので分割なし)
        # これによりkabukiの depends 検証バグを回避
        model = hddm.HDDMStimCoding(
            df_fit,
            stim_col='stim',
            split_param='v',
            drift_criterion=False,
            include=['a', 'v', 't'],
            p_outlier=0.05,
        )
        model.find_starting_values()
        model.sample(N_SAMPLES, burn=N_BURN, thin=N_THIN, dbname=None, db='ram')

    # ===========================================
    # 群レベル事後分布
    # condition='all' で分割されたので、ノード名は 'a(all)' 形式になる
    # ===========================================
    a_group = model.nodes_db.node['a'].trace()
    v_group = model.nodes_db.node['v'].trace()
    t_group = model.nodes_db.node['t'].trace()

    a_group_std = model.nodes_db.node['a_std'].trace()
    v_group_std = model.nodes_db.node['v_std'].trace()
    t_group_std = model.nodes_db.node['t_std'].trace()

    # ===========================================
    # 被験者レベル事後分布 (各被験者の a_i, v_i, t_i)
    # ===========================================
    n_subj = df_fit['subj_idx'].nunique()
    subj_estimates = []

    # condition='all' の場合のノード名: 'a_subj(all).0', 'a_subj(all).1', ...
    def get_subj_node(param, i):
        candidates = [
            f'{param}_subj(all).{i}',
            f'{param}_subj.{i}',
            f'{param}(all)_subj.{i}',
            f'{param}_subj({i})',
        ]
        for fmt in candidates:
            try:
                return model.nodes_db.node[fmt].trace()
            except KeyError:
                continue
        # それでも見つからなければ全ノード名から探す
        for name in model.nodes_db.node.keys():
            if name.startswith(f'{param}_subj') and (
                name.endswith(f'.{i}') or f'({i})' in name or f'[{i}]' in name
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
        # ノード名一覧をデバッグ出力
        print("\nDEBUG: Available node names:")
        for name in sorted(model.nodes_db.node.keys()):
            print(f"  {name}")
        sys.exit(1)

    subj_df = pd.DataFrame(subj_estimates)

    # subject_id を結合
    id_map = df.groupby('subj_idx')['subject_id'].first().to_dict()
    subj_df['subject_id'] = subj_df['subj_idx'].map(id_map).astype(str).str.zfill(3)
    subj_df = subj_df[['subj_idx', 'subject_id', 'a', 'v', 't']]

    out_path = os.path.join(SCRIPT_DIR, 'pre_experiment_hddm_subjlevel.csv')
    subj_df.to_csv(out_path, index=False)

    # ===========================================
    # 経験的 SD (被験者間ばらつき)
    # ===========================================
    a_emp_sd = subj_df['a'].std(ddof=1)
    v_emp_sd = subj_df['v'].std(ddof=1)
    t_emp_sd = subj_df['t'].std(ddof=1)

    # 群レベル平均
    a_emp_mean = subj_df['a'].mean()
    v_emp_mean = subj_df['v'].mean()
    t_emp_mean = subj_df['t'].mean()

    # ===========================================
    # 結果表示
    # ===========================================
    print("\n" + "=" * 70)
    print("Group-level posterior (HDDM)")
    print("=" * 70)
    print(f"  a:       mean={a_group.mean():.4f}, post_sd={a_group.std():.4f}")
    print(f"  v:       mean={v_group.mean():.4f}, post_sd={v_group.std():.4f}")
    print(f"  t:       mean={t_group.mean():.4f}, post_sd={t_group.std():.4f}")
    print()
    print(f"  a_std (between-subj SD posterior): mean={a_group_std.mean():.4f}")
    print(f"  v_std (between-subj SD posterior): mean={v_group_std.mean():.4f}")
    print(f"  t_std (between-subj SD posterior): mean={t_group_std.mean():.4f}")

    print("\n" + "=" * 70)
    print("Subject-level estimates (posterior means)")
    print("=" * 70)
    print(subj_df.to_string(index=False))

    print("\n" + "=" * 70)
    print("Empirical between-subject SDs (sample SD of subject-level posterior means)")
    print("=" * 70)
    print(f"  a_emp_sd = {a_emp_sd:.4f}  (mean a = {a_emp_mean:.4f})")
    print(f"  v_emp_sd = {v_emp_sd:.4f}  (mean v = {v_emp_mean:.4f})")
    print(f"  t_emp_sd = {t_emp_sd:.4f}  (mean t = {t_emp_mean:.4f})")

    # ===========================================
    # SUBJ_VAR 推奨値 (現状の utils.py との比較)
    # ===========================================
    # Current simulator variability values in utils.py.
    current_subj_var = {
        'a_sd': 0.10,
        'v_sd': 0.30,
        't_sd': 0.04,
    }

    print("\n" + "=" * 70)
    print("Comparison with current utils.py SUBJ_VAR")
    print("=" * 70)
    print("NOTE: This fit uses HDDMStimCoding for the CRT task.")
    print("      The recovered v is a stimulus-coded left/right drift contrast,")
    print("      so do not use v_emp_sd directly as the simulator's generic v_sd.")
    print(f"  Parameter |  Current  |  Empirical  |  Ratio  | Recommendation")
    print(f"  ----------|-----------|-------------|---------|----------------")
    print(f"  a_sd      |  {current_subj_var['a_sd']:.4f}   |  {a_emp_sd:.4f}     |  {a_emp_sd/current_subj_var['a_sd']:.2f}x   | usable")
    print(f"  v_sd      |  {current_subj_var['v_sd']:.4f}   |  {v_emp_sd:.4f}     |  {v_emp_sd/current_subj_var['v_sd']:.2f}x   | keep current/theory")
    print(f"  t_sd      |  {current_subj_var['t_sd']:.4f}   |  {t_emp_sd:.4f}     |  {t_emp_sd/current_subj_var['t_sd']:.2f}x   | usable")

    # ===========================================
    # 結果保存
    # ===========================================
    results = {
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
        'recommended_subj_var': {
            'a_sd': float(a_emp_sd),
            'v_sd': current_subj_var['v_sd'],
            't_sd': float(t_emp_sd),
            'note': (
                "v_sd from HDDMStimCoding is a stimulus-coded left/right drift "
                "contrast and should not replace the simulator's generic v_sd."
            ),
        },
        'empirical_means': {
            'a': float(a_emp_mean),
            'v': float(v_emp_mean),
            't': float(t_emp_mean),
        },
        'n_subjects': int(n_subj),
        'n_trials_total': int(len(df_fit)),
    }

    out_json = os.path.join(SCRIPT_DIR, 'pre_experiment_subj_var.json')
    with open(out_json, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nSaved:")
    print(f"  {out_path}")
    print(f"  {out_json}")

    print("\n" + "=" * 70)
    print("Next step:")
    print("=" * 70)
    print("Use recommended_subj_var for a_sd and t_sd if you want the grid")
    print("to reflect pre-experiment variability; keep v_sd theory/current unless")
    print("you estimate a generic drift-rate SD with a separate recovery model.")


if __name__ == '__main__':
    main()
