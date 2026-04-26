"""
make_dummy_data.py — HDDM 解析パイプライン動作確認用の仮想データ生成

trial_log.csv と同じフォーマットの偽データを被験者数 × 群数分生成し、
Reaction_Test/ExperimentData/ 配下と同じディレクトリ構造で出力する。

== DDM パラメータプリセット ==

[realistic_crt] (デフォルト) — 実 CRT に近い高速反応
  Baseline:  v=3.10, a=0.55, t=0.180s  → RT≈245ms, accuracy≈0.97
  PostTest (AgencyEMS):  t=0.170s        → 10ms 短縮 (微小効果)
  PostTest (Voluntary):  変化なし

[strong_effect] — 検出しやすい大きな効果
  Baseline:  v=1.5, a=1.5, t=0.35s     → RT≈755ms
  PostTest (AgencyEMS):  t=0.30s        → 50ms 短縮
  PostTest (Voluntary):  変化なし

[custom] — CLI 引数で全パラメータ指定

使用例:
  # 実 CRT 相当 (デフォルト)、各群 18名、各フェーズ 200試行
  python make_dummy_data.py --outdir ../ExperimentData_dummy_realistic \\
    --n_per_group 18 --n_baseline 200 --n_posttest 200

  # 強い効果版 (パイプライン動作確認用)
  python make_dummy_data.py --outdir ../ExperimentData_dummy_strong \\
    --preset strong_effect --n_per_group 10
"""
import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
import numpy as np


# ============================================================
# プリセット定義
# ============================================================

PRESETS = {
    "realistic_crt": {
        "description": "Realistic CRT: RT~245ms, dt=-10ms (subtle EMS effect)",
        "v_base": 3.10,
        "a_base": 0.55,
        "t_base": 0.180,
        "delta_v_ems": 0.0,
        "delta_a_ems": 0.0,
        "delta_t_ems": -0.010,
    },
    "strong_effect": {
        "description": "Strong effect for pipeline verification: dt=-50ms",
        "v_base": 1.5,
        "a_base": 1.5,
        "t_base": 0.35,
        "delta_v_ems": 0.0,
        "delta_a_ems": 0.0,
        "delta_t_ems": -0.050,
    },
}


# ============================================================
# DDM シミュレータ
# ============================================================

def simulate_subject_phase_vec(subj_id: str, group: str, phase: str,
                               v: float, a: float, t: float,
                               n_trials: int, start_trial: int,
                               rng: np.random.Generator,
                               dt: float = 0.001,
                               max_time: float = 3.0) -> list:
    """1 被験者の 1 フェーズ分の試行をベクトル化シミュレート。

    全 n_trials 試行を同時に時間発展させて高速化。dt=0.001s (1ms 刻み)
    で精度を担保。
    """
    n_steps = int(max_time / dt)
    sqrt_dt = np.sqrt(dt)

    # 開始位置 (中立 z=0.5)
    x = np.full(n_trials, 0.5 * a)
    finished = np.zeros(n_trials, dtype=bool)
    rts_s = np.full(n_trials, max_time)
    correct = np.full(n_trials, -1, dtype=int)

    for step in range(n_steps):
        active = ~finished
        if not active.any():
            break
        noise = rng.standard_normal(int(active.sum()))
        x[active] += v * dt + sqrt_dt * noise

        hit_upper = active & (x >= a)
        rts_s[hit_upper] = step * dt + t
        correct[hit_upper] = 1
        finished |= hit_upper

        hit_lower = active & (x <= 0)
        rts_s[hit_lower] = step * dt + t
        correct[hit_lower] = 0
        finished |= hit_lower

    # バランスド・ターゲットリストの生成（Unity側と整合）
    left_count = n_trials // 2
    right_count = n_trials - left_count
    target_sides = np.array(["Left"] * left_count + ["Right"] * right_count)
    rng.shuffle(target_sides)

    timestamp = datetime.now(timezone.utc)

    records = []
    for i in range(n_trials):
        if correct[i] == -1:
            rt_ms = -1.0
            response_side = "None"
            is_correct = 0
        else:
            rt_ms = rts_s[i] * 1000.0
            response_side = (target_sides[i] if correct[i] == 1
                             else ("Right" if target_sides[i] == "Left" else "Left"))
            is_correct = int(correct[i] == 1)

        records.append({
            "SubjectID": subj_id,
            "Group": group,
            "Phase": phase,
            "TrialNumber": start_trial + i,
            "TargetSide": target_sides[i],
            "ResponseSide": response_side,
            "IsCorrect": is_correct,
            "ReactionTime_ms": round(rt_ms, 3),
            "EMSOffset_ms": 0.0,
            "EMSFireTiming_ms": 0.0,
            "AgencyYes": 0,
            "Timestamp": timestamp.isoformat(),
        })
    return records


# ============================================================
# I/O
# ============================================================

def write_session(session_dir: Path, records: list, subject_id: str,
                  group: str) -> None:
    """trial_log.csv と session_info.json を書き出し。"""
    session_dir.mkdir(parents=True, exist_ok=True)
    csv_path = session_dir / "trial_log.csv"
    header = ["SubjectID", "Group", "Phase", "TrialNumber", "TargetSide",
              "ResponseSide", "IsCorrect", "ReactionTime_ms",
              "EMSOffset_ms", "EMSFireTiming_ms", "AgencyYes", "Timestamp"]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()
        writer.writerows(records)

    info = {
        "SubjectId": subject_id,
        "Group": group,
        "DatetimeStart": datetime.now(timezone.utc).isoformat(),
        "AppVersion": "dummy-0.0.2",
    }
    (session_dir / "session_info.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")


# ============================================================
# Main
# ============================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate dummy trial_log.csv data with realistic DDM params",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\n".join([f"Preset [{k}]: {v['description']}"
                          for k, v in PRESETS.items()]))
    parser.add_argument("--outdir", required=True, help="Output ExperimentData root")
    parser.add_argument("--preset", choices=list(PRESETS.keys()) + ["custom"],
                        default="realistic_crt",
                        help="Preset for true DDM params (default: realistic_crt)")
    parser.add_argument("--n_per_group", type=int, default=18)
    parser.add_argument("--n_baseline", type=int, default=200)
    parser.add_argument("--n_posttest", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--subj_var", type=float, default=0.15,
                        help="Per-subject variability (0.15 = +/- 15%)")

    # custom preset 用
    parser.add_argument("--v_base", type=float, default=None)
    parser.add_argument("--a_base", type=float, default=None)
    parser.add_argument("--t_base", type=float, default=None)
    parser.add_argument("--delta_v_ems", type=float, default=None)
    parser.add_argument("--delta_a_ems", type=float, default=None)
    parser.add_argument("--delta_t_ems", type=float, default=None)
    args = parser.parse_args()

    if args.preset == "custom":
        params = {k: getattr(args, k) for k in
                  ["v_base", "a_base", "t_base",
                   "delta_v_ems", "delta_a_ems", "delta_t_ems"]}
        if any(v is None for v in params.values()):
            parser.error("--preset custom requires all of v_base/a_base/t_base "
                         "and delta_v_ems/delta_a_ems/delta_t_ems")
    else:
        params = PRESETS[args.preset].copy()
        params.pop("description", None)

    out_dir = Path(args.outdir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Preset: {args.preset}")
    print(f"  Baseline:  v={params['v_base']:.2f}  a={params['a_base']:.2f}  "
          f"t={params['t_base']:.3f}s")
    print(f"  Delta (AgencyEMS PostTest):  dv={params['delta_v_ems']:+.2f}  "
          f"da={params['delta_a_ems']:+.2f}  dt={params['delta_t_ems']*1000:+.0f}ms")
    print(f"  N per group: {args.n_per_group}, "
          f"trials: {args.n_baseline} + {args.n_posttest}")
    print()

    rng = np.random.default_rng(args.seed)

    subject_counter = 1
    for group in ["AgencyEMS", "Voluntary"]:
        # Voluntary 群は PostTest で変化なし
        dv = params["delta_v_ems"] if group == "AgencyEMS" else 0.0
        da = params["delta_a_ems"] if group == "AgencyEMS" else 0.0
        dt_eff = params["delta_t_ems"] if group == "AgencyEMS" else 0.0

        for _ in range(args.n_per_group):
            subject_id = f"P{subject_counter:03d}"
            subject_counter += 1

            # 被験者個人差
            v_i = params["v_base"] * (1 + rng.standard_normal() * args.subj_var * 0.3)
            a_i = params["a_base"] * (1 + rng.standard_normal() * args.subj_var * 0.2)
            t_i = max(0.05, params["t_base"] +
                      rng.standard_normal() * args.subj_var * 0.03)

            records = []
            records += simulate_subject_phase_vec(
                subject_id, group, "Baseline", v_i, a_i, t_i,
                n_trials=args.n_baseline, start_trial=1, rng=rng)
            records += simulate_subject_phase_vec(
                subject_id, group, "PostTest",
                v_i + dv, a_i + da, t_i + dt_eff,
                n_trials=args.n_posttest,
                start_trial=args.n_baseline + 1, rng=rng)

            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            session_dir = out_dir / subject_id / f"session_01_{stamp}"
            write_session(session_dir, records, subject_id, group)

            base_rts = [r["ReactionTime_ms"] for r in records
                        if r["Phase"] == "Baseline" and r["ReactionTime_ms"] > 0]
            post_rts = [r["ReactionTime_ms"] for r in records
                        if r["Phase"] == "PostTest" and r["ReactionTime_ms"] > 0]
            base_acc = np.mean([r["IsCorrect"] for r in records
                                if r["Phase"] == "Baseline"])
            print(f"  {subject_id} [{group:9s}]  "
                  f"Base: RT={np.mean(base_rts):5.1f}ms acc={base_acc:.2f}  "
                  f"Post: RT={np.mean(post_rts):5.1f}ms")

    print(f"\nDone. Generated {subject_counter - 1} subjects under {out_dir}")


if __name__ == "__main__":
    main()
