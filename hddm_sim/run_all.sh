#!/bin/bash
# クイックスタート: 環境構築から全グリッド実行まで

set -e

echo "=== HDDM Power Simulation: Quick Start ==="
echo ""

# 1. 環境作成 (既にある場合はスキップ)
if ! conda env list | grep -q "hddm_sim"; then
    echo "Creating conda environment..."
    conda env create -f environment.yml
fi

# 2. 環境アクティベート
echo "Activating environment..."
eval "$(conda shell.bash hook)"
conda activate hddm_sim

# 3. 動作確認: 単一フィット
echo ""
echo "=== Step 1: Smoke test (1 fit, n=10, t=80) ==="
python 02_fit_hddm.py --n_subj 10 --n_trials 80 --rep_id 0 --n_samples 1000 --burn 500

# 4. 軽量グリッド (各セル3反復、まず傾向確認)
echo ""
echo "=== Step 2: Lightweight grid (3 reps per cell) ==="
read -p "Run lightweight grid? (estimated 30-60 min) [y/N] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    python 03_run_grid.py --n_jobs 4 --n_reps 3 --output_dir ./results_quick
    python 04_analyze_results.py --results_dir ./results_quick
fi

# 5. フルグリッド
echo ""
echo "=== Step 3: Full grid (30 reps per cell) ==="
read -p "Run full grid? (estimated 4-8 hours) [y/N] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    python 03_run_grid.py --n_jobs 8 --output_dir ./results
    python 04_analyze_results.py --results_dir ./results
fi

echo ""
echo "Done! See ./results/heatmap_decision_rates.png"
