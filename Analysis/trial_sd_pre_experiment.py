#!/usr/bin/env python3
"""
事前実験データ（10人）の「試行間SD」＝被験者ごとの反応時間(RT)の試行をまたいだ
標準偏差を一覧表示するスクリプト。標準ライブラリのみ（pandas等の追加インストール不要）。

入力（既定）: hddm_sim/pre_experiment_data.csv
    列: subj_idx, subject_id, stim(Left/Right), rt(秒), response(1=正答/0=誤答)
    被験者 001..010 × 各80試行（事前実験 TestData の整形版）。
    別のCSVを使う場合は第1引数でパスを渡す（同じ列名を想定）。

出力:
    - コンソールに被験者ごとの表（n, 平均, 試行間SD, CV, 左右別SD）
    - Analysis/results_pre_experiment_trial_sd/trial_sd_per_subject.csv

「試行間SD」= その被験者のRT系列の標本標準偏差（ddof=1）。
既定では正答試行(response==1)のRTで算出（RTばらつきの慣例）。
比較用に全試行（正誤込み）のSDも併記する。

使い方:
    python Analysis/trial_sd_pre_experiment.py
    python Analysis/trial_sd_pre_experiment.py path/to/other.csv
"""

import argparse
import csv
import os
import sys
import statistics
from collections import defaultdict

# Windowsコンソール(cp932)で日本語/記号を出力してもクラッシュしないようにする。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DEFAULT_INPUT = os.path.join("hddm_sim", "pre_experiment_data.csv")
OUTPUT_DIR = os.path.join("Analysis", "results_pre_experiment_trial_sd")
OUTPUT_CSV = os.path.join(OUTPUT_DIR, "trial_sd_per_subject.csv")


def repo_root():
    """このスクリプトはリポジトリ直下からの相対パスを想定。スクリプト位置から推定。"""
    here = os.path.dirname(os.path.abspath(__file__))   # .../Analysis
    return os.path.dirname(here)                          # repo root


def sd_ms(values_ms):
    """標本標準偏差(ddof=1)。2件未満は None。"""
    return statistics.stdev(values_ms) if len(values_ms) >= 2 else None


def fmt(x, nd=1):
    return f"{x:.{nd}f}" if x is not None else "-"


def main():
    root = repo_root()
    parser = argparse.ArgumentParser(description="Per-subject trial-to-trial RT SD report.")
    parser.add_argument("input", nargs="?", default=os.path.join(root, DEFAULT_INPUT),
                        help="入力CSV（既定: hddm_sim/pre_experiment_data.csv）")
    parser.add_argument("--exclude", default="",
                        help="除外する subject_id をカンマ区切りで指定（例: --exclude 007,004）")
    args = parser.parse_args()

    in_path = args.input
    exclude = {s.strip() for s in args.exclude.split(",") if s.strip()}
    if not os.path.isfile(in_path):
        sys.exit(f"入力CSVが見つかりません: {in_path}")

    # subject_id -> list of (rt_ms, response, stim)
    by_subj = defaultdict(list)
    with open(in_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        required = {"subject_id", "rt", "response", "stim"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            sys.exit(f"必要な列がありません: {sorted(missing)} （あるのは {reader.fieldnames}）")
        for row in reader:
            rt_ms = float(row["rt"]) * 1000.0  # 秒 -> ms
            resp = row["response"].strip()
            stim = row["stim"].strip()
            by_subj[row["subject_id"]].append((rt_ms, resp, stim))

    subjects = [s for s in sorted(by_subj.keys()) if s not in exclude]
    if exclude:
        print(f"excluded: {sorted(exclude)}")

    rows_out = []
    for sid in subjects:
        trials = by_subj[sid]
        correct = [rt for rt, resp, _ in trials if resp == "1"]
        all_rt = [rt for rt, _, _ in trials]
        left = [rt for rt, resp, st in trials if resp == "1" and st == "Left"]
        right = [rt for rt, resp, st in trials if resp == "1" and st == "Right"]

        acc = (len(correct) / len(trials) * 100.0) if trials else 0.0
        mean_c = statistics.mean(correct) if correct else None
        sd_c = sd_ms(correct)
        cv = (sd_c / mean_c) if (sd_c is not None and mean_c) else None

        rows_out.append({
            "subject_id": sid,
            "n_trials": len(trials),
            "n_correct": len(correct),
            "acc_pct": round(acc, 1),
            "rt_mean_ms": round(mean_c, 1) if mean_c is not None else "",
            "rt_sd_ms": round(sd_c, 1) if sd_c is not None else "",          # ★ 試行間SD（正答）
            "rt_cv": round(cv, 3) if cv is not None else "",
            "rt_sd_ms_all": round(sd_ms(all_rt), 1) if sd_ms(all_rt) is not None else "",
            "rt_sd_ms_left": round(sd_ms(left), 1) if sd_ms(left) is not None else "",
            "rt_sd_ms_right": round(sd_ms(right), 1) if sd_ms(right) is not None else "",
        })

    # ---- コンソール表示（ASCIIのみ：Windows cp932でも安全） ----
    print(f"input: {in_path}")
    print(f"subjects: {len(subjects)}   (trial-to-trial SD = sample SD of correct RTs, ddof=1, ms)\n")
    header = f"{'subj':>5} {'n':>4} {'nCor':>5} {'acc%':>6} {'mean':>7} {'SD':>7} {'CV':>6} {'SD(all)':>8} {'SD(L)':>7} {'SD(R)':>7}"
    print(header)
    print("-" * len(header))
    for r in rows_out:
        print(f"{r['subject_id']:>5} {r['n_trials']:>4} {r['n_correct']:>5} "
              f"{fmt(r['acc_pct']):>6} {fmt(r['rt_mean_ms']):>7} {fmt(r['rt_sd_ms']):>7} "
              f"{fmt(r['rt_cv'],3):>6} {fmt(r['rt_sd_ms_all']):>8} "
              f"{fmt(r['rt_sd_ms_left']):>7} {fmt(r['rt_sd_ms_right']):>7}")

    # 全体サマリ（被験者ごと試行間SDの平均・範囲）
    print("-" * len(header))

    def msd(vals):
        """(mean, sd, min, max) for a list of numbers; sd is None if <2."""
        if not vals:
            return None, None, None, None
        m = statistics.mean(vals)
        s = statistics.stdev(vals) if len(vals) >= 2 else None
        return m, s, min(vals), max(vals)

    means = [r["rt_mean_ms"] for r in rows_out if isinstance(r["rt_mean_ms"], (int, float))]
    sds   = [r["rt_sd_ms"]   for r in rows_out if isinstance(r["rt_sd_ms"],   (int, float))]
    accs  = [r["acc_pct"]    for r in rows_out if isinstance(r["acc_pct"],    (int, float))]

    print("Between-subject summary (N={}):".format(len(rows_out)))
    m, s, lo, hi = msd(means)
    if m is not None:
        print(f"  mean RT      : grand mean {m:.1f}ms, BETWEEN-SUBJECT SD {fmt(s)}ms, range {lo:.1f}-{hi:.1f}ms")
    m, s, lo, hi = msd(sds)
    if m is not None:
        print(f"  trial SD     : mean {m:.1f}ms, between-subject SD {fmt(s)}ms, range {lo:.1f}-{hi:.1f}ms")
    m, s, lo, hi = msd(accs)
    if m is not None:
        print(f"  accuracy %   : mean {m:.1f}, between-subject SD {fmt(s)}, range {lo:.1f}-{hi:.1f}")

    # ---- CSV 保存 ----
    out_dir = os.path.join(root, OUTPUT_DIR)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(root, OUTPUT_CSV)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows_out[0].keys()))
        writer.writeheader()
        writer.writerows(rows_out)
    print(f"\nsaved: {out_path}")


if __name__ == "__main__":
    main()
