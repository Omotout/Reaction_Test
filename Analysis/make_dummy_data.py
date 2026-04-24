"""
make_dummy_data.py — HDDM 解析パイプライン動作確認用の仮想データ生成

trial_log.csv と同じフォーマットの偽データを被験者数 × 群数分生成し、
Reaction_Test/ExperimentData/ 配下と同じディレクトリ構造で出力する。

DDM パラメータの仮説:
  Baseline:
    AgencyEMS, Voluntary 両群とも v=1.5, a=1.5, t=0.35 (典型的 2AFC)
  PostTest:
    AgencyEMS: v=1.5, a=1.5, t=0.30 (非決定時間 50ms 短縮 → 運動プライミング)
    Voluntary: v=1.5, a=1.5, t=0.35 (変化なし)

使用例:
  python make_dummy_data.py --outdir ./ExperimentData_dummy --n_per_group 10
"""
import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
import numpy as np


def simulate_ddm_trial(v: float, a: float, t: float, z: float = 0.5,
                       dt: float = 0.005, max_time: float = 4.0,
                       rng: np.random.Generator = None) -> tuple:
    """DDM の単試行シミュレート (ベクトル化されていない版、読みやすさ優先)。"""
    if rng is None:
        rng = np.random.default_rng()
    x = z * a
    sqrt_dt = np.sqrt(dt)
    n_steps = int(max_time / dt)
    for step in range(n_steps):
        x += v * dt + sqrt_dt * rng.standard_normal()
        if x >= a:
            return (step * dt + t, 1)  # 上界 = 正答
        if x <= 0:
            return (step * dt + t, 0)  # 下界 = 誤答
    return (max_time, -1)


def simulate_subject_phase(subj_id: str, group: str, phase: str,
                           v: float, a: float, t: float,
                           n_trials: int, start_trial: int,
                           subj_var: float = 0.15,
                           rng: np.random.Generator = None) -> list:
    """1 被験者の 1 フェーズ分の TrialRecord リストを返す。"""
    if rng is None:
        rng = np.random.default_rng()

    # 被験者個人差を v, a, t に加える
    v_i = v * (1 + rng.standard_normal() * subj_var * 0.3)
    a_i = a * (1 + rng.standard_normal() * subj_var * 0.2)
    t_i = max(0.15, t + rng.standard_normal() * subj_var * 0.05)

    records = []
    timestamp = datetime.now(timezone.utc)
    for trial_in_phase in range(n_trials):
        target_side = rng.choice(["Left", "Right"])
        # CRT では刺激側と同じ方に押すのが正解
        # DDM の上界=正答, 下界=誤答
        rt_s, correct = simulate_ddm_trial(v_i, a_i, t_i, rng=rng)
        if correct == -1:
            rt_ms = -1.0
            response_side = "None"
            is_correct = 0
        else:
            rt_ms = rt_s * 1000.0
            response_side = target_side if correct == 1 else (
                "Right" if target_side == "Left" else "Left")
            is_correct = int(correct == 1)

        records.append({
            "SubjectID": subj_id,
            "Group": group,
            "Phase": phase,
            "TrialNumber": start_trial + trial_in_phase,
            "TargetSide": target_side,
            "ResponseSide": response_side,
            "IsCorrect": is_correct,
            "ReactionTime_ms": round(rt_ms, 3),
            "EMSOffset_ms": 0.0,
            "EMSFireTiming_ms": 0.0,
            "AgencyYes": 0,
            "Timestamp": timestamp.isoformat(),
        })
    return records


def write_session(session_dir: Path, records: list, subject_id: str,
                  group: str) -> None:
    """trial_log.csv と session_info.json を書き出し。"""
    session_dir.mkdir(parents=True, exist_ok=True)

    # trial_log.csv
    csv_path = session_dir / "trial_log.csv"
    header = ["SubjectID", "Group", "Phase", "TrialNumber", "TargetSide",
              "ResponseSide", "IsCorrect", "ReactionTime_ms",
              "EMSOffset_ms", "EMSFireTiming_ms", "AgencyYes", "Timestamp"]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()
        writer.writerows(records)

    # session_info.json
    info = {
        "SubjectId": subject_id,
        "Group": group,
        "DatetimeStart": datetime.now(timezone.utc).isoformat(),
        "AppVersion": "dummy-0.0.1",
    }
    (session_dir / "session_info.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate dummy trial_log.csv data")
    parser.add_argument("--outdir", required=True, help="Output ExperimentData root")
    parser.add_argument("--n_per_group", type=int, default=10,
                        help="Subjects per group (default: 10)")
    parser.add_argument("--n_baseline", type=int, default=40,
                        help="Baseline trials per subject (default: 40)")
    parser.add_argument("--n_posttest", type=int, default=40,
                        help="PostTest trials per subject (default: 40)")
    parser.add_argument("--seed", type=int, default=42)
    # 真のパラメータ
    parser.add_argument("--v_base", type=float, default=1.5)
    parser.add_argument("--a_base", type=float, default=1.5)
    parser.add_argument("--t_base", type=float, default=0.35)
    parser.add_argument("--delta_t_ems", type=float, default=-0.05,
                        help="Δt for AgencyEMS group in PostTest (s, default: -0.05)")
    parser.add_argument("--delta_v_ems", type=float, default=0.0,
                        help="Δv for AgencyEMS group in PostTest (default: 0.0)")
    args = parser.parse_args()

    out_dir = Path(args.outdir)
    out_dir.mkdir(parents=True, exist_ok=True)

    rng = np.random.default_rng(args.seed)

    subject_counter = 1
    for group, (dv, dt) in [
        ("AgencyEMS", (args.delta_v_ems, args.delta_t_ems)),
        ("Voluntary", (0.0, 0.0)),
    ]:
        for _ in range(args.n_per_group):
            subject_id = f"P{subject_counter:03d}"
            subject_counter += 1

            records = []
            # Baseline
            records += simulate_subject_phase(
                subject_id, group, "Baseline",
                args.v_base, args.a_base, args.t_base,
                n_trials=args.n_baseline, start_trial=1, rng=rng)
            # PostTest (with effect)
            records += simulate_subject_phase(
                subject_id, group, "PostTest",
                args.v_base + dv, args.a_base, args.t_base + dt,
                n_trials=args.n_posttest,
                start_trial=args.n_baseline + 1, rng=rng)

            # ディレクトリ構造: <out>/P001/session_01_YYYYMMDD_HHMMSS/
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            session_dir = out_dir / subject_id / f"session_01_{stamp}"
            write_session(session_dir, records, subject_id, group)
            print(f"  Wrote {subject_id} ({group}): {len(records)} trials → {session_dir}")

    print(f"\nDone. Generated {subject_counter - 1} subjects under {out_dir}")


if __name__ == "__main__":
    main()
