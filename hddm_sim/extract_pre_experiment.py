"""
extract_pre_experiment.py

プレ実験データ (TestData/) から各被験者の最新セッションを取得し、
Test フェーズの試行を統合した HDDM 入力 CSV を生成する。

実行 (ローカル):
    python extract_pre_experiment.py

実行 (Docker):
    docker run --rm \
      -v "C:\\Users\\tomoa\\Unity\\Projects\\Reaction_Test:/work" \
      -w /work/hddm_sim \
      hcp4715/hddm:latest \
      python extract_pre_experiment.py

出力: pre_experiment_data.csv
  - subj_idx: 0-indexed の被験者ID (HDDM用)
  - subject_id: 元のID (001, 002, ...)
  - rt: 反応時間 (秒)
  - response: 0=incorrect, 1=correct
"""

import json
import os
import re
import sys

import pandas as pd


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# TestData は hddm_sim の親ディレクトリ (Reaction_Test) の下にある想定
# ローカルでもDockerでも動くように相対パスで解決
TESTDATA_DIR = os.path.normpath(os.path.join(SCRIPT_DIR, '..', 'TestData'))

TARGET_PHASE = "Test"
RT_MIN = 0.15   # 秒。短すぎる試行(早すぎ反応)を除外
RT_MAX = 2.0    # 秒。長すぎる試行(注意散漫)を除外


def find_latest_session(subj_dir):
    """test_NN_YYYYMMDD_HHMMSS フォルダの中から最新を返す"""
    pattern = re.compile(r'^test_\d+_\d{8}_\d{6}$')
    sessions = [d for d in os.listdir(subj_dir)
                if os.path.isdir(os.path.join(subj_dir, d)) and pattern.match(d)]
    if not sessions:
        return None
    sessions.sort()  # 文字列ソートで時系列になる
    return sessions[-1]


def load_subject(subj_id, base_dir=TESTDATA_DIR):
    """1被験者の最新セッションを読み込み、Phase=Test のみを返す"""
    subj_dir = os.path.join(base_dir, subj_id)
    if not os.path.isdir(subj_dir):
        return None, f"Directory not found: {subj_dir}"

    session_name = find_latest_session(subj_dir)
    if session_name is None:
        return None, f"No session folder in {subj_dir}"

    csv_path = os.path.join(subj_dir, session_name, 'trial_log.csv')
    json_path = os.path.join(subj_dir, session_name, 'session_info.json')
    if not os.path.exists(csv_path):
        return None, f"trial_log.csv not found in {session_name}"

    df = pd.read_csv(csv_path, encoding='utf-8-sig')

    # Phase=Test のみ
    df = df[df['Phase'] == TARGET_PHASE].copy()
    if len(df) == 0:
        return None, f"No '{TARGET_PHASE}' phase trials in {session_name}"

    # session info読み込み(参照用)
    session_meta = {}
    if os.path.exists(json_path):
        try:
            with open(json_path, 'r', encoding='utf-8-sig') as f:
                session_meta = json.load(f)
        except Exception:
            pass

    info = {
        'session_name': session_name,
        'group': session_meta.get('Group', 'unknown'),
        'datetime_start': session_meta.get('DatetimeStart', 'unknown'),
        'n_trials_raw': len(df),
    }
    return df, info


def main():
    print("=" * 70)
    print(f"Extracting pre-experiment data (Phase = '{TARGET_PHASE}')")
    print(f"Source: {TESTDATA_DIR}")
    print("=" * 70)

    if not os.path.isdir(TESTDATA_DIR):
        print(f"\nERROR: TestData directory not found at {TESTDATA_DIR}")
        print("If running in Docker, mount the Reaction_Test directory:")
        print('  -v "C:\\Users\\tomoa\\Unity\\Projects\\Reaction_Test:/work"')
        print('  -w /work/hddm_sim')
        sys.exit(1)

    subjects = [f"{i:03d}" for i in range(1, 11)]  # 001-010

    all_data = []
    summary_rows = []

    for subj_id in subjects:
        df, info = load_subject(subj_id)
        if df is None:
            print(f"  {subj_id}: SKIP ({info})")
            continue

        # HDDM形式に整形
        df_hddm = pd.DataFrame({
            'subject_id': df['SubjectID'].astype(str).str.zfill(3),
            'stim': df['TargetSide'].astype(str),
            'rt': df['ReactionTime_ms'].astype(float) / 1000.0,
            'response': df['IsCorrect'].astype(int),
        })

        # 外れ値除外
        n_before = len(df_hddm)
        df_hddm = df_hddm[(df_hddm['rt'] >= RT_MIN) & (df_hddm['rt'] <= RT_MAX)]
        n_after = len(df_hddm)
        n_excluded = n_before - n_after

        all_data.append(df_hddm)

        acc = df_hddm['response'].mean()
        rt_mean = df_hddm['rt'].mean()
        summary_rows.append({
            'subject_id': subj_id,
            'session': info['session_name'],
            'group': info['group'],
            'n_trials_raw': n_before,
            'n_trials_used': n_after,
            'n_excluded': n_excluded,
            'acc': round(acc, 4),
            'rt_mean_ms': round(rt_mean * 1000, 1),
        })
        print(f"  {subj_id}: session={info['session_name']}, "
              f"trials={n_after}/{n_before} (excluded {n_excluded}), "
              f"acc={acc:.3f}, RT={rt_mean*1000:.0f}ms")

    if not all_data:
        print("\nERROR: No data loaded.")
        sys.exit(1)

    # 統合
    combined = pd.concat(all_data, ignore_index=True)

    # subj_idx (HDDM用 0-indexed) を割り当て
    subj_id_map = {sid: i for i, sid in enumerate(sorted(combined['subject_id'].unique()))}
    combined['subj_idx'] = combined['subject_id'].map(subj_id_map)

    # 列順整理
    combined = combined[['subj_idx', 'subject_id', 'stim', 'rt', 'response']]

    # 保存
    out_path = os.path.join(SCRIPT_DIR, 'pre_experiment_data.csv')
    combined.to_csv(out_path, index=False)

    summary_df = pd.DataFrame(summary_rows)
    summary_path = os.path.join(SCRIPT_DIR, 'pre_experiment_summary.csv')
    summary_df.to_csv(summary_path, index=False)

    # サマリー表示
    print("\n" + "=" * 70)
    print("Summary")
    print("=" * 70)
    print(summary_df.to_string(index=False))
    print()
    print(f"Total subjects: {combined['subj_idx'].nunique()}")
    print(f"Total trials: {len(combined)}")
    print(f"Trials per subject: mean={combined.groupby('subj_idx').size().mean():.0f}, "
          f"min={combined.groupby('subj_idx').size().min()}, "
          f"max={combined.groupby('subj_idx').size().max()}")
    print(f"Overall accuracy: {combined['response'].mean():.4f}")
    print(f"Overall RT (ms): mean={combined['rt'].mean()*1000:.1f}, "
          f"median={combined['rt'].median()*1000:.1f}")
    print()
    print(f"Saved: {out_path}")
    print(f"Saved: {summary_path}")
    print()
    print("Next step: python fit_pre_experiment.py")


if __name__ == '__main__':
    main()
