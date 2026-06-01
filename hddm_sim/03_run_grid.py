"""
03_run_grid.py

被験者数 × 試行数 × 反復回数 のフルグリッドでHDDMフィットを並列実行。

使い方:
    # 8コア並列で全条件実行
    python 03_run_grid.py --n_jobs 8 --output_dir ./results

    # テスト走行 (各セル3反復のみ)
    python 03_run_grid.py --n_jobs 4 --n_reps 3 --output_dir ./results_test

    # 特定セルだけ実行 (チェックポイント再開用)
    python 03_run_grid.py --n_subj 15 --n_trials 120 --n_jobs 8

途中で止まっても、出力ディレクトリ内のCSVに各セル単位で保存されるので、
完了済みセルはスキップして再開可能。
"""

import argparse
import os
import sys
import time
from itertools import product

import pandas as pd
from joblib import Parallel, delayed
from tqdm import tqdm

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import GRID
import importlib.util
spec = importlib.util.spec_from_file_location(
    "fit_hddm", os.path.join(os.path.dirname(os.path.abspath(__file__)), "02_fit_hddm.py")
)
fit_hddm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fit_hddm)


def cell_filename(output_dir, n_subj, n_trials):
    return os.path.join(output_dir, f"cell_n{n_subj}_t{n_trials}.csv")


def run_cell(n_subj, n_trials, n_reps, n_jobs, output_dir,
             n_samples=2000, burn=1000, resume=True):
    """
    1セル(n_subj × n_trials)について n_reps 回反復実行
    並列はセル内反復の並列化(joblib)
    """
    output_path = cell_filename(output_dir, n_subj, n_trials)

    # 再開: 既に保存済みの反復を確認
    completed_rep_ids = set()
    if resume and os.path.exists(output_path):
        existing = pd.read_csv(output_path)
        completed_rep_ids = set(existing['rep_id'].tolist())
        print(f"  Resume: {len(completed_rep_ids)} reps already completed")

    rep_ids_to_run = [r for r in range(n_reps) if r not in completed_rep_ids]
    if not rep_ids_to_run:
        print(f"  Skip: all {n_reps} reps completed for n_subj={n_subj}, n_trials={n_trials}")
        return

    print(f"\n=== Cell: n_subj={n_subj}, n_trials={n_trials}, reps to run={len(rep_ids_to_run)} ===")

    def _fit_wrapper(rep_id):
        try:
            return fit_hddm.fit_one_replication(
                n_subj_per_group=n_subj,
                n_trials=n_trials,
                rep_id=rep_id,
                n_samples=n_samples,
                burn=burn,
                verbose=False,
            )
        except Exception as e:
            return {
                'rep_id': rep_id,
                'n_subj': n_subj,
                'n_trials': n_trials,
                'error': str(e),
            }

    t_start = time.time()
    results = Parallel(n_jobs=n_jobs, backend='loky', verbose=5)(
        delayed(_fit_wrapper)(r) for r in rep_ids_to_run
    )
    elapsed = time.time() - t_start
    print(f"  Cell completed in {elapsed/60:.1f} min "
          f"({elapsed/len(rep_ids_to_run):.1f} sec/rep, {n_jobs} parallel)")

    # マージして保存 (再開時は既存に追記)
    df_new = pd.DataFrame(results)
    if os.path.exists(output_path) and resume:
        df_existing = pd.read_csv(output_path)
        df_combined = pd.concat([df_existing, df_new], ignore_index=True)
        df_combined = df_combined.drop_duplicates(subset=['rep_id'], keep='last')
    else:
        df_combined = df_new

    df_combined.to_csv(output_path, index=False)
    print(f"  Saved: {output_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--n_jobs', type=int, default=4,
                        help='joblibの並列ジョブ数(物理コア数推奨)')
    parser.add_argument('--n_reps', type=int, default=GRID['n_reps'],
                        help='各セルの反復回数')
    parser.add_argument('--n_subj', type=int, nargs='+', default=GRID['n_subj'],
                        help='被験者数のリスト')
    parser.add_argument('--n_trials', type=int, nargs='+', default=GRID['n_trials'],
                        help='試行数のリスト')
    parser.add_argument('--output_dir', type=str, default='./results')
    parser.add_argument('--n_samples', type=int, default=2000)
    parser.add_argument('--burn', type=int, default=1000)
    parser.add_argument('--no_resume', action='store_true',
                        help='既存結果を無視して全反復を再実行')
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    print("=" * 70)
    print("HDDM Power Simulation Grid")
    print("=" * 70)
    print(f"  n_subj grid:  {args.n_subj}")
    print(f"  n_trials grid: {args.n_trials}")
    print(f"  n_reps per cell: {args.n_reps}")
    print(f"  total cells: {len(args.n_subj) * len(args.n_trials)}")
    print(f"  total fits:  {len(args.n_subj) * len(args.n_trials) * args.n_reps}")
    print(f"  parallel jobs: {args.n_jobs}")
    print(f"  output: {args.output_dir}")
    print(f"  resume: {not args.no_resume}")
    print()

    grand_t_start = time.time()
    cells = list(product(args.n_subj, args.n_trials))

    for n_subj, n_trials in cells:
        run_cell(
            n_subj=n_subj,
            n_trials=n_trials,
            n_reps=args.n_reps,
            n_jobs=args.n_jobs,
            output_dir=args.output_dir,
            n_samples=args.n_samples,
            burn=args.burn,
            resume=not args.no_resume,
        )

    grand_elapsed = time.time() - grand_t_start
    print("\n" + "=" * 70)
    print(f"All cells completed in {grand_elapsed/60:.1f} min ({grand_elapsed/3600:.2f} h)")
    print("=" * 70)
    print("\nNext step: python 04_analyze_results.py --results_dir " + args.output_dir)


if __name__ == '__main__':
    main()
