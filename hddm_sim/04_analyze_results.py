"""
04_analyze_results.py

集計とプロット。固定ROPEとempirical ROPE (Szul流) の両方を比較。

評価項目:
  1. RT短縮率                       (rt_short_rate)
  2. 正答率非劣性率                 (acc_noninf_rate)
  3. a 同等性主張率 [固定ROPE]      (a_equiv_rate)
  3'. a 同等性主張率 [empirical]    (a_equiv_emp_rate)
  4. v 同等性主張率 [固定ROPE]      (v_equiv_rate)
  4'. v 同等性主張率 [empirical]    (v_equiv_emp_rate)
  5. t_er 短縮検出率                (t_super_rate)
  6. P_P|D (Szul) 平均              (a_p_pd_mean, v_p_pd_mean, t_p_pd_mean)
"""

import argparse
import glob
import os

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

from utils import summarize_grid_results, ROPE


def load_all_cells(results_dir):
    files = glob.glob(os.path.join(results_dir, 'cell_n*_t*.csv'))
    if not files:
        raise FileNotFoundError(f"No cell_*.csv found in {results_dir}")
    dfs = [pd.read_csv(f) for f in files]
    combined = pd.concat(dfs, ignore_index=True)
    if 'error' in combined.columns:
        n_errors = combined['error'].notna().sum()
        if n_errors > 0:
            print(f"WARNING: {n_errors} replications had errors and will be excluded")
            combined = combined[combined['error'].isna()]
    return combined


def plot_decision_heatmap(summary, output_dir):
    """6項目のヒートマップ (2x3 配置)"""
    metrics = [
        ('rt_short_rate', 'RT shortening rate', 'Reds'),
        ('acc_noninf_rate', 'Accuracy non-inferiority rate', 'Oranges'),
        ('a_equiv_rate', '$a$ equivalence rate (固定ROPE)', 'Greens'),
        ('v_equiv_rate', '$v$ equivalence rate (固定ROPE)', 'Blues'),
        ('t_super_rate', '$t_{er}$ shortening rate (HDI<0)', 'Purples'),
        ('a_p_pd_mean', 'Mean $P_{P|D}$ for $a$ (Szul, empirical ROPE)', 'YlGn'),
    ]

    fig, axes = plt.subplots(2, 3, figsize=(16, 9))
    for ax, (metric, title, cmap) in zip(axes.flat, metrics):
        if metric not in summary.columns:
            ax.set_visible(False)
            continue
        pivot = summary[metric].unstack('n_trials')
        sns.heatmap(
            pivot, annot=True, fmt='.2f', cmap=cmap,
            vmin=0, vmax=1, ax=ax,
            cbar_kws={'label': 'Rate / Probability'},
            annot_kws={'size': 11},
        )
        ax.set_title(title, fontsize=11)
        ax.set_xlabel('Trials per subject')
        ax.set_ylabel('Subjects per group')

    plt.suptitle("Power & evidence across (N, T) grid",
                 fontsize=13, y=1.00)
    plt.tight_layout()
    out_path = os.path.join(output_dir, 'heatmap_decision_rates.png')
    plt.savefig(out_path, dpi=150, bbox_inches='tight')
    print(f"Saved: {out_path}")
    plt.close()


def plot_rope_comparison(summary, output_dir):
    """固定ROPE vs empirical ROPE の比較ヒートマップ"""
    if 'a_equiv_emp_rate' not in summary.columns:
        print("Skipping ROPE comparison: empirical ROPE columns not present")
        return

    fig, axes = plt.subplots(2, 2, figsize=(12, 9))
    metrics = [
        ('a_equiv_rate', '$a$ equiv: 固定ROPE±0.10', 'Greens'),
        ('a_equiv_emp_rate', '$a$ equiv: empirical ROPE (Szul)', 'YlGn'),
        ('v_equiv_rate', '$v$ equiv: 固定ROPE±0.30', 'Blues'),
        ('v_equiv_emp_rate', '$v$ equiv: empirical ROPE (Szul)', 'PuBu'),
    ]
    for ax, (metric, title, cmap) in zip(axes.flat, metrics):
        if metric not in summary.columns:
            ax.set_visible(False)
            continue
        pivot = summary[metric].unstack('n_trials')
        sns.heatmap(
            pivot, annot=True, fmt='.2f', cmap=cmap,
            vmin=0, vmax=1, ax=ax,
            cbar_kws={'label': 'Equivalence rate'},
            annot_kws={'size': 11},
        )
        ax.set_title(title, fontsize=11)
        ax.set_xlabel('Trials per subject')
        ax.set_ylabel('Subjects per group')

    plt.suptitle("Fixed ROPE vs empirical ROPE (Szul et al. 2020)",
                 fontsize=13, y=1.00)
    plt.tight_layout()
    out_path = os.path.join(output_dir, 'rope_comparison.png')
    plt.savefig(out_path, dpi=150, bbox_inches='tight')
    print(f"Saved: {out_path}")
    plt.close()


def plot_p_pd_distribution(combined, output_dir):
    """P_P|D の分布 (反復間ばらつき)"""
    if 'a_p_pd' not in combined.columns:
        print("Skipping P_P|D distribution: column not present")
        return

    cells = sorted(combined.groupby(['n_subj', 'n_trials']).groups.keys())

    fig, axes = plt.subplots(3, 1, figsize=(11, 10))
    params_info = [
        ('a_p_pd', '$P_{P|D}$ for $a$ (Szul, empirical ROPE)'),
        ('v_p_pd', '$P_{P|D}$ for $v$'),
        ('t_p_pd', '$P_{P|D}$ for $t_{er}$'),
    ]

    for ax, (metric, title) in zip(axes, params_info):
        if metric not in combined.columns:
            ax.set_visible(False)
            continue
        positions, labels, box_data = [], [], []
        for i, (n_s, n_t) in enumerate(cells):
            cell_df = combined[(combined['n_subj'] == n_s) & (combined['n_trials'] == n_t)]
            positions.append(i)
            labels.append(f"N={n_s}\nT={n_t}")
            box_data.append(cell_df[metric].values)

        bp = ax.boxplot(box_data, positions=positions, widths=0.6, patch_artist=True)
        for patch in bp['boxes']:
            patch.set_facecolor('lightyellow')

        ax.axhline(0.95, color='green', linestyle=':', alpha=0.7,
                   label='P_P|D ≥ 0.95 (strong equivalence)')
        ax.axhline(0.50, color='orange', linestyle=':', alpha=0.7,
                   label='P_P|D = 0.50 (ambiguous)')

        ax.set_xticks(positions)
        ax.set_xticklabels(labels, fontsize=9)
        ax.set_ylabel(title)
        ax.set_ylim(-0.05, 1.05)
        ax.legend(loc='lower right', fontsize=9)
        ax.grid(alpha=0.3)

    plt.suptitle('$P_{P|D}$ distribution across replications (Szul et al. 2020)',
                 fontsize=13, y=1.00)
    plt.tight_layout()
    out_path = os.path.join(output_dir, 'p_pd_distribution.png')
    plt.savefig(out_path, dpi=150, bbox_inches='tight')
    print(f"Saved: {out_path}")
    plt.close()


def plot_diff_distributions(combined, output_dir):
    """a, v, t 群差の分布"""
    cells = sorted(combined.groupby(['n_subj', 'n_trials']).groups.keys())

    fig, axes = plt.subplots(3, 1, figsize=(11, 10))
    params_info = [
        ('a_diff_mean', '$a_{EMS} - a_{Ctrl}$', ROPE['a']),
        ('v_diff_mean', '$v_{EMS} - v_{Ctrl}$', ROPE['v']),
        ('t_diff_mean', '$t_{er,EMS} - t_{er,Ctrl}$', ROPE['t']),
    ]

    for ax, (metric, title, rope_range) in zip(axes, params_info):
        positions, labels, box_data = [], [], []
        for i, (n_s, n_t) in enumerate(cells):
            cell_df = combined[(combined['n_subj'] == n_s) & (combined['n_trials'] == n_t)]
            positions.append(i)
            labels.append(f"N={n_s}\nT={n_t}")
            box_data.append(cell_df[metric].values)

        bp = ax.boxplot(box_data, positions=positions, widths=0.6, patch_artist=True)
        for patch in bp['boxes']:
            patch.set_facecolor('lightblue')

        ax.axhspan(*rope_range, alpha=0.2, color='green',
                   label=f'固定ROPE: ({rope_range[0]:.3f}, {rope_range[1]:.3f})')
        ax.axhline(0, color='black', linestyle='--', alpha=0.5, label='True diff = 0')

        if metric == 't_diff_mean':
            ax.axhline(-0.008, color='red', linestyle='--', alpha=0.5,
                       label='True diff = -0.008')

        ax.set_xticks(positions)
        ax.set_xticklabels(labels, fontsize=9)
        ax.set_ylabel(title)
        ax.legend(loc='best', fontsize=9)
        ax.grid(alpha=0.3)

    plt.suptitle('Posterior mean of group differences across replications',
                 fontsize=13, y=1.00)
    plt.tight_layout()
    out_path = os.path.join(output_dir, 'diff_distributions.png')
    plt.savefig(out_path, dpi=150, bbox_inches='tight')
    print(f"Saved: {out_path}")
    plt.close()


def plot_rope_widths(combined, output_dir):
    """empirical ROPE幅の分布"""
    if 'a_rope_emp_width' not in combined.columns:
        return

    cells = sorted(combined.groupby(['n_subj', 'n_trials']).groups.keys())

    fig, axes = plt.subplots(1, 3, figsize=(16, 5))
    params_info = [
        ('a_rope_emp_width', 'empirical ROPE width: $a$', ROPE['a'][1] - ROPE['a'][0]),
        ('v_rope_emp_width', 'empirical ROPE width: $v$', ROPE['v'][1] - ROPE['v'][0]),
        ('t_rope_emp_width', 'empirical ROPE width: $t_{er}$', ROPE['t'][1] - ROPE['t'][0]),
    ]

    for ax, (metric, title, fixed_width) in zip(axes, params_info):
        if metric not in combined.columns:
            ax.set_visible(False)
            continue
        positions, labels, box_data = [], [], []
        for i, (n_s, n_t) in enumerate(cells):
            cell_df = combined[(combined['n_subj'] == n_s) & (combined['n_trials'] == n_t)]
            positions.append(i)
            labels.append(f"N={n_s}\nT={n_t}")
            box_data.append(cell_df[metric].values)

        bp = ax.boxplot(box_data, positions=positions, widths=0.6, patch_artist=True)
        for patch in bp['boxes']:
            patch.set_facecolor('lightcoral')

        ax.axhline(fixed_width, color='blue', linestyle='--', alpha=0.7,
                   label=f'Fixed ROPE width = {fixed_width:.3f}')
        ax.set_xticks(positions)
        ax.set_xticklabels(labels, fontsize=8, rotation=0)
        ax.set_ylabel(title)
        ax.legend(loc='best', fontsize=8)
        ax.grid(alpha=0.3)

    plt.suptitle('Empirical ROPE widths across replications', fontsize=13, y=1.00)
    plt.tight_layout()
    out_path = os.path.join(output_dir, 'rope_widths.png')
    plt.savefig(out_path, dpi=150, bbox_inches='tight')
    print(f"Saved: {out_path}")
    plt.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--results_dir', type=str, default='./results')
    parser.add_argument('--output_dir', type=str, default=None)
    args = parser.parse_args()

    output_dir = args.output_dir or args.results_dir
    os.makedirs(output_dir, exist_ok=True)

    print(f"Loading results from: {args.results_dir}")
    combined = load_all_cells(args.results_dir)
    print(f"Total replications loaded: {len(combined)}")
    print()

    summary = summarize_grid_results(combined)
    print("=" * 80)
    print("Summary Table")
    print("=" * 80)
    print(summary)

    summary_path = os.path.join(output_dir, 'summary.csv')
    summary.to_csv(summary_path)
    print(f"\nSaved: {summary_path}")

    # 80%閾値分析
    print("\n" + "=" * 80)
    print("Cells achieving ≥80% rate (Tomoaki's 6 evaluation goals)")
    print("=" * 80)
    metrics_for_80 = [
        ('rt_short_rate', '(1) RT shortening'),
        ('acc_noninf_rate', '(2) Acc non-inferiority'),
        ('a_equiv_rate', '(3) a equivalence (固定ROPE)'),
        ('a_equiv_emp_rate', '(3) a equivalence (empirical)'),
        ('v_equiv_rate', '(4) v equivalence (固定ROPE)'),
        ('v_equiv_emp_rate', '(4) v equivalence (empirical)'),
        ('t_super_rate', '(5) t_er shortening'),
    ]
    for col, name in metrics_for_80:
        if col not in summary.columns:
            continue
        cells_80 = summary[summary[col] >= 0.80].index.tolist()
        if cells_80:
            min_cell = min(cells_80, key=lambda x: x[0] * x[1])
            print(f"  {name}: minimum N×T = N={min_cell[0]}, T={min_cell[1]} "
                  f"(rate={summary.loc[min_cell, col]:.2f})")
        else:
            max_rate = summary[col].max()
            max_cell = summary[col].idxmax()
            print(f"  {name}: NO cell ≥80%. Best: N={max_cell[0]}, T={max_cell[1]} ({max_rate:.2f})")

    # P_P|D サマリー
    if 'a_p_pd_mean' in summary.columns:
        print("\n" + "=" * 80)
        print("P_P|D (Szul) means — closer to 1.0 = stronger equivalence claim")
        print("=" * 80)
        print(summary[['a_p_pd_mean', 'v_p_pd_mean', 't_p_pd_mean']].round(3))

    # プロット
    print()
    plot_decision_heatmap(summary, output_dir)
    plot_rope_comparison(summary, output_dir)
    plot_p_pd_distribution(combined, output_dir)
    plot_diff_distributions(combined, output_dir)
    plot_rope_widths(combined, output_dir)

    print("\nDone.")


if __name__ == '__main__':
    main()
