#!/usr/bin/env python3
"""
analyze_session.py — 単一セッション（1被験者・1条件）の記述的解析。

既存の analyze_training_effect.py は「群レベル・条件間 RM ANOVA」用で、複数被験者×
EMS/Voluntary 両条件が前提。単一パイロット（例: 吉田2）や、Deadline モード特有の列
（Deadline_ms / ResponseBeforeDeadline / EmsScheduled / EmsCanceled / TouchAfterEms_ms /
Outcome）は解析していない。本スクリプトはその穴を埋める：

  - フェーズ別（Pre / Training1 / Post1 / Training2 / Post2）の n / 正答率 /
    正答RTの median・mean・試行間SD（左右別も）
  - Pre→Post 変化（median RT、左右別）と gain
  - Deadline モード指標（Training フェーズ）:
      * Outcome 内訳
      * deadline 突破率 ResponseBeforeDeadline（学習の主要 DV）を Train1 vs Train2 で比較
      * 左右 deadline_ms
      * EMS 機構: scheduled / fired / canceled、キャンセル率（=EMS前に反応）、
        TouchAfterEms_ms（EMS誘発運動の潜時）の median/SD
  - matplotlib があれば RT 軌跡図 (rt_trajectory.png) を保存（無くても動く）

出力: コンソール表 ＋ セッションフォルダに analysis_report.json / phase_summary.csv。
標準ライブラリのみで動作（pandas/scipy 不要）。

使い方:
  python Analysis/analyze_session.py                 # ExperimentData 配下の全セッション
  python Analysis/analyze_session.py --data_dir ExperimentData
  python Analysis/analyze_session.py --session "ExperimentData/吉田2/session_01_20260605_183659"
"""

import argparse
import csv
import json
import os
import statistics
import sys
from collections import Counter, defaultdict

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PHASES = ["Pre", "Training1", "Post1", "Training2", "Post2"]
TRAIN_PHASES = ["Training1", "Training2"]
SIDES = ["Left", "Right"]


def repo_root():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(here)


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def sample_sd(vals):
    return statistics.stdev(vals) if len(vals) >= 2 else None


def median(vals):
    return statistics.median(vals) if vals else None


def fmt(x, nd=1):
    return f"{x:.{nd}f}" if isinstance(x, (int, float)) else "-"


def find_sessions(data_dir, only_session):
    """解析対象の session ディレクトリ一覧（trial_log.csv を含むもの）を返す。"""
    if only_session:
        d = only_session
        if os.path.isfile(d):  # trial_log.csv を直接指定
            d = os.path.dirname(d)
        return [d] if os.path.isfile(os.path.join(d, "trial_log.csv")) else []
    sessions = []
    if not os.path.isdir(data_dir):
        return sessions
    for subj in sorted(os.listdir(data_dir)):
        subj_path = os.path.join(data_dir, subj)
        if not os.path.isdir(subj_path):
            continue
        for name in sorted(os.listdir(subj_path)):
            sess = os.path.join(subj_path, name)
            if os.path.isdir(sess) and os.path.isfile(os.path.join(sess, "trial_log.csv")):
                sessions.append(sess)
    return sessions


def correct_rts(rows, phase=None, side=None):
    """Normal・正答・RT>0 の反応時間(ms)リスト。phase/side でフィルタ可。"""
    out = []
    for r in rows:
        if phase and r["Phase"] != phase:
            continue
        if side and r.get("CorrectHand") != side:
            continue
        if r["IsCorrect"] != "1" or r.get("ExclusionFlag") != "Normal":
            continue
        rt = num(r["ReactionTime_ms"])
        if rt is not None and rt > 0:
            out.append(rt)
    return out


def phase_summary(rows):
    """フェーズ別の記述統計を dict のリストで返す。"""
    out = []
    for ph in PHASES:
        pr = [r for r in rows if r["Phase"] == ph]
        if not pr:
            continue
        n = len(pr)
        ncor = sum(1 for r in pr if r["IsCorrect"] == "1")
        n_timeout = sum(1 for r in pr if r.get("ResponseSide") == "None")
        c_all = correct_rts(pr)
        c_l = correct_rts(pr, side="Left")
        c_r = correct_rts(pr, side="Right")
        out.append({
            "phase": ph, "n": n, "n_correct": ncor, "n_timeout": n_timeout,
            "acc_pct": round(ncor / n * 100, 1) if n else None,
            "rt_median_ms": round(median(c_all), 1) if c_all else None,
            "rt_mean_ms": round(statistics.mean(c_all), 1) if c_all else None,
            "rt_sd_ms": round(sample_sd(c_all), 1) if sample_sd(c_all) else None,
            "rt_median_L": round(median(c_l), 1) if c_l else None,
            "rt_median_R": round(median(c_r), 1) if c_r else None,
            "rt_sd_L": round(sample_sd(c_l), 1) if sample_sd(c_l) else None,
            "rt_sd_R": round(sample_sd(c_r), 1) if sample_sd(c_r) else None,
        })
    return out


def deadline_section(rows, has_deadline_cols):
    """Deadline モード指標。列が無い/Fastest セッションでは None を返す。"""
    if not has_deadline_cols:
        return None
    # Deadline が実効（!= -1）のフェーズだけ対象
    info = {"per_training_phase": [], "ems": {}, "deadline_ms": {}}

    for ph in TRAIN_PHASES:
        pr = [r for r in rows if r["Phase"] == ph]
        if not pr:
            continue
        n = len(pr)
        before = sum(1 for r in pr if r.get("ResponseBeforeDeadline") == "1")
        outcomes = dict(Counter(r["Outcome"] for r in pr))
        info["per_training_phase"].append({
            "phase": ph, "n": n,
            "response_before_deadline": before,
            "before_deadline_pct": round(before / n * 100, 1) if n else None,
            "outcomes": outcomes,
        })

    # deadline_ms（左右別、Training の代表値）
    for side in SIDES:
        vals = sorted({r["Deadline_ms"] for r in rows
                       if r["Phase"] in TRAIN_PHASES and r.get("CorrectHand") == side
                       and num(r["Deadline_ms"]) not in (None, -1.0)})
        info["deadline_ms"][side] = [round(num(v), 1) for v in vals]

    # EMS 機構（Training 全体）
    tr = [r for r in rows if r["Phase"] in TRAIN_PHASES]
    scheduled = sum(1 for r in tr if r.get("EmsScheduled") == "1")
    fired = sum(1 for r in tr if r.get("EmsFired") == "1")
    canceled = sum(1 for r in tr if r.get("EmsCanceled") == "1")
    tae = [num(r["TouchAfterEms_ms"]) for r in tr
           if num(r["TouchAfterEms_ms"]) is not None and num(r["TouchAfterEms_ms"]) > 0]
    info["ems"] = {
        "scheduled": scheduled, "fired": fired, "canceled": canceled,
        "cancel_rate_pct": round(canceled / scheduled * 100, 1) if scheduled else None,
        "touch_after_ems_median_ms": round(median(tae), 1) if tae else None,
        "touch_after_ems_sd_ms": round(sample_sd(tae), 1) if sample_sd(tae) else None,
        "touch_after_ems_n": len(tae),
    }
    return info


def maybe_plot(rows, session_dir):
    """matplotlib があれば RT 軌跡図を保存。無ければ静かにスキップ。"""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return None
    xs, ys, cols = [], [], []
    palette = {"Pre": "#888", "Training1": "#d62728", "Post1": "#1f77b4",
               "Training2": "#ff7f0e", "Post2": "#2ca02c"}
    for i, r in enumerate(rows, 1):
        rt = num(r["ReactionTime_ms"])
        if rt is None or rt <= 0:
            continue
        xs.append(i); ys.append(rt); cols.append(palette.get(r["Phase"], "#000"))
    if not xs:
        return None
    plt.figure(figsize=(11, 4))
    plt.scatter(xs, ys, c=cols, s=14)
    for ph, c in palette.items():
        plt.scatter([], [], c=c, label=ph)
    plt.xlabel("trial (session order)"); plt.ylabel("RT (ms)")
    plt.title("RT trajectory"); plt.legend(fontsize=8, ncol=5)
    out = os.path.join(session_dir, "rt_trajectory.png")
    plt.tight_layout(); plt.savefig(out, dpi=110); plt.close()
    return out


def analyze(session_dir):
    trial_path = os.path.join(session_dir, "trial_log.csv")
    rows = list(csv.DictReader(open(trial_path, newline="", encoding="utf-8-sig")))
    if not rows:
        print(f"(empty) {trial_path}")
        return

    # 新FastestBaselineスキーマ以外（旧agency/test形式など）はスキップ
    required = {"Phase", "IsCorrect", "ReactionTime_ms", "CorrectHand"}
    if not required.issubset(rows[0].keys()):
        print(f"(skip: not FastestBaseline schema) {session_dir}")
        return

    summary = {}
    sp = os.path.join(session_dir, "summary.json")
    if os.path.isfile(sp):
        try:
            summary = json.load(open(sp, encoding="utf-8-sig"))
        except Exception:
            pass

    subj = rows[0].get("SubjectID", "?")
    cond = rows[0].get("Condition", "?")
    mode = rows[0].get("InterventionMode", "Fastest")
    has_dl = "Deadline_ms" in rows[0]

    print("=" * 72)
    print(f"Session: {session_dir}")
    print(f"Subject={subj}  Condition={cond}  InterventionMode={mode}  trials={len(rows)}")
    if summary:
        print(f"  Baseline L/R = {fmt(summary.get('BaselineLeft'))}/{fmt(summary.get('BaselineRight'))} ms"
              f"  | EMS_to_Touch L/R = {fmt(summary.get('EmsToTouchLeft'))}/{fmt(summary.get('EmsToTouchRight'))} ms")
        print(f"  median Pre/Post1/Post2 = {fmt(summary.get('MedianPre'))}/{fmt(summary.get('MedianPost1'))}/"
              f"{fmt(summary.get('MedianPost2'))} ms  | gain = {fmt(summary.get('Gain'))} ms")

    # ---- per-phase ----
    psum = phase_summary(rows)
    print("\n[Per-phase RT summary] (correct, Normal, RT>0; SD = trial-to-trial sample SD, ms)")
    hdr = f"{'phase':>10} {'n':>3} {'nCor':>4} {'TO':>3} {'acc%':>5} {'med':>6} {'mean':>6} {'SD':>6} {'medL':>6} {'medR':>6} {'sdL':>5} {'sdR':>5}"
    print(hdr); print("-" * len(hdr))
    for s in psum:
        print(f"{s['phase']:>10} {s['n']:>3} {s['n_correct']:>4} {s['n_timeout']:>3} "
              f"{fmt(s['acc_pct']):>5} {fmt(s['rt_median_ms']):>6} {fmt(s['rt_mean_ms']):>6} {fmt(s['rt_sd_ms']):>6} "
              f"{fmt(s['rt_median_L']):>6} {fmt(s['rt_median_R']):>6} {fmt(s['rt_sd_L']):>5} {fmt(s['rt_sd_R']):>5}")

    # ---- Pre -> Post change ----
    by = {s["phase"]: s for s in psum}
    if "Pre" in by:
        pre = by["Pre"]["rt_median_ms"]
        for ph in ("Post1", "Post2"):
            if ph in by and pre is not None and by[ph]["rt_median_ms"] is not None:
                d = by[ph]["rt_median_ms"] - pre
                print(f"  change median RT  Pre->{ph}: {d:+.1f} ms")

    # ---- Deadline section ----
    dl = deadline_section(rows, has_dl and mode == "Deadline")
    if dl:
        print("\n[Deadline-mode metrics]")
        print(f"  deadline_ms  Left={dl['deadline_ms'].get('Left')}  Right={dl['deadline_ms'].get('Right')}")
        print("  beat-deadline rate (ResponseBeforeDeadline) by training block:")
        for t in dl["per_training_phase"]:
            print(f"    {t['phase']:>10}: {t['response_before_deadline']}/{t['n']} "
                  f"({fmt(t['before_deadline_pct'])}%)   outcomes={t['outcomes']}")
        e = dl["ems"]
        print(f"  EMS: scheduled={e['scheduled']} fired={e['fired']} canceled={e['canceled']} "
              f"(cancel/responded-first={fmt(e['cancel_rate_pct'])}%)")
        print(f"  TouchAfterEms_ms: n={e['touch_after_ems_n']} median={fmt(e['touch_after_ems_median_ms'])} "
              f"SD={fmt(e['touch_after_ems_sd_ms'])}")

    # ---- outputs ----
    png = maybe_plot(rows, session_dir)
    if png:
        print(f"\n  plot saved: {png}")

    report = {
        "session_dir": session_dir, "subject": subj, "condition": cond,
        "intervention_mode": mode, "n_trials": len(rows),
        "summary_json": summary, "phase_summary": psum, "deadline": dl,
    }
    json.dump(report, open(os.path.join(session_dir, "analysis_report.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    with open(os.path.join(session_dir, "phase_summary.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(psum[0].keys()))
        w.writeheader(); w.writerows(psum)
    print(f"  saved: analysis_report.json, phase_summary.csv (in session folder)")


def main():
    root = repo_root()
    ap = argparse.ArgumentParser(description="Single-session descriptive + Deadline-mode analysis.")
    ap.add_argument("--data_dir", default=os.path.join(root, "ExperimentData"),
                    help="被験者フォルダを含むデータ根（既定: ExperimentData）")
    ap.add_argument("--session", default=None,
                    help="単一の session フォルダ（または trial_log.csv）を直接指定")
    args = ap.parse_args()

    sessions = find_sessions(args.data_dir, args.session)
    if not sessions:
        sys.exit(f"trial_log.csv を含む session が見つかりません（data_dir={args.data_dir}, session={args.session}）")
    for s in sessions:
        analyze(s)


if __name__ == "__main__":
    main()
