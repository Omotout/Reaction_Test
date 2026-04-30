"""
Analyze TestGame pilot data.

Default behavior:
  - Read TestData/<numeric subject>/test_*/trial_log.csv
  - Use only the latest test session per subject
  - Write CSV summaries, a Markdown report, and basic figures

Examples:
  python Analysis/analyze_pilot_test.py
  python Analysis/analyze_pilot_test.py --data-dir TestData --out-dir Analysis/results_pilot_test
  python Analysis/analyze_pilot_test.py --all-sessions
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


REQUIRED_COLUMNS = {
    "SubjectID",
    "Phase",
    "TrialNumber",
    "TargetSide",
    "ResponseSide",
    "IsCorrect",
    "ReactionTime_ms",
}


@dataclass(frozen=True)
class LoadedFile:
    subject_id: str
    session: str
    path: Path
    n_trials: int


def find_trial_logs(data_dir: Path, all_sessions: bool) -> list[Path]:
    subject_dirs = sorted(
        p for p in data_dir.iterdir()
        if p.is_dir() and p.name.isdigit()
    )

    logs: list[Path] = []
    for subject_dir in subject_dirs:
        subject_logs = sorted(subject_dir.glob("test_*/trial_log.csv"))
        if not subject_logs:
            continue
        if all_sessions:
            logs.extend(subject_logs)
        else:
            logs.append(subject_logs[-1])

    return logs


def load_logs(paths: Iterable[Path]) -> tuple[pd.DataFrame, pd.DataFrame]:
    frames: list[pd.DataFrame] = []
    loaded: list[LoadedFile] = []

    for path in paths:
        df = pd.read_csv(path, encoding="utf-8-sig")
        missing = REQUIRED_COLUMNS - set(df.columns)
        if missing:
            raise ValueError(f"{path} is missing columns: {sorted(missing)}")

        subject_id = str(df["SubjectID"].iloc[0]).zfill(3)
        session = path.parent.name
        df = df.copy()
        df["SubjectID"] = subject_id
        df["Session"] = session
        df["SourceFile"] = str(path)
        frames.append(df)
        loaded.append(LoadedFile(subject_id, session, path, len(df)))

    if not frames:
        raise ValueError("No trial_log.csv files found.")

    data = pd.concat(frames, ignore_index=True)
    files = pd.DataFrame([item.__dict__ for item in loaded])
    return data, files


def preprocess(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["IsCorrect"] = pd.to_numeric(out["IsCorrect"], errors="coerce").fillna(0).astype(int)
    out["ReactionTime_ms"] = pd.to_numeric(out["ReactionTime_ms"], errors="coerce")
    out["TrialNumber"] = pd.to_numeric(out["TrialNumber"], errors="coerce")
    out["HasResponse"] = out["ResponseSide"].ne("None") & out["ReactionTime_ms"].gt(0)
    out["IsError"] = out["HasResponse"] & out["IsCorrect"].eq(0)
    out["IsOmission"] = ~out["HasResponse"]
    out["IsCorrectResponse"] = out["HasResponse"] & out["IsCorrect"].eq(1)
    out = out.sort_values(["SubjectID", "Session", "TrialNumber"], kind="stable").copy()
    out["SessionTrialIndex"] = out.groupby(["SubjectID", "Session"]).cumcount() + 1
    out["SessionTrialCount"] = out.groupby(["SubjectID", "Session"])["SessionTrialIndex"].transform("max")
    out["TrialHalf"] = np.where(
        out["SessionTrialIndex"] <= out["SessionTrialCount"] / 2,
        "FirstHalf",
        "SecondHalf",
    )
    out["TrialHalfOrder"] = np.where(out["TrialHalf"].eq("FirstHalf"), 1, 2)
    return out


def accuracy_label(acc_pct: float) -> str:
    if acc_pct >= 99:
        return "99-100%: very easy"
    if acc_pct >= 95:
        return "95-98%: high accuracy with a few errors"
    if acc_pct >= 90:
        return "90-95%: likely useful for DDM"
    return "<90%: may be too difficult"


def summarize_rt(series: pd.Series) -> dict[str, float | int]:
    x = pd.to_numeric(series, errors="coerce").dropna()
    x = x[x > 0]
    if len(x) == 0:
        return {
            "n": 0,
            "mean_ms": np.nan,
            "median_ms": np.nan,
            "sd_ms": np.nan,
            "min_ms": np.nan,
            "q1_ms": np.nan,
            "q3_ms": np.nan,
            "max_ms": np.nan,
            "iqr_outlier_count": 0,
            "iqr_lower_ms": np.nan,
            "iqr_upper_ms": np.nan,
        }

    q1 = x.quantile(0.25)
    q3 = x.quantile(0.75)
    iqr = q3 - q1
    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr
    return {
        "n": int(len(x)),
        "mean_ms": float(x.mean()),
        "median_ms": float(x.median()),
        "sd_ms": float(x.std(ddof=1)) if len(x) > 1 else 0.0,
        "min_ms": float(x.min()),
        "q1_ms": float(q1),
        "q3_ms": float(q3),
        "max_ms": float(x.max()),
        "iqr_outlier_count": int(((x < lower) | (x > upper)).sum()),
        "iqr_lower_ms": float(lower),
        "iqr_upper_ms": float(upper),
    }


def make_subject_summary(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for subject_id, g in df.groupby("SubjectID", sort=True):
        row = {
            "SubjectID": subject_id,
            "n_trials": len(g),
            "n_correct": int(g["IsCorrect"].sum()),
            "accuracy": g["IsCorrect"].mean(),
            "accuracy_pct": g["IsCorrect"].mean() * 100,
            "n_omission": int(g["IsOmission"].sum()),
            "n_error": int(g["IsError"].sum()),
            "left_trials": int(g["TargetSide"].eq("Left").sum()),
            "right_trials": int(g["TargetSide"].eq("Right").sum()),
        }
        row.update({f"correct_rt_{k}": v for k, v in summarize_rt(g.loc[g["IsCorrectResponse"], "ReactionTime_ms"]).items()})
        row.update({f"error_rt_{k}": v for k, v in summarize_rt(g.loc[g["IsError"], "ReactionTime_ms"]).items()})
        rows.append(row)
    return pd.DataFrame(rows)


def make_side_summary(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    rows = []
    for keys, g in df.groupby(group_cols, sort=True):
        if not isinstance(keys, tuple):
            keys = (keys,)
        row = dict(zip(group_cols, keys))
        row.update({
            "n_trials": len(g),
            "n_correct": int(g["IsCorrect"].sum()),
            "accuracy": g["IsCorrect"].mean(),
            "accuracy_pct": g["IsCorrect"].mean() * 100,
            "n_omission": int(g["IsOmission"].sum()),
            "n_error": int(g["IsError"].sum()),
        })
        row.update({f"correct_rt_{k}": v for k, v in summarize_rt(g.loc[g["IsCorrectResponse"], "ReactionTime_ms"]).items()})
        row.update({f"error_rt_{k}": v for k, v in summarize_rt(g.loc[g["IsError"], "ReactionTime_ms"]).items()})
        rows.append(row)
    return pd.DataFrame(rows)


def make_rt_summary(df: pd.DataFrame) -> pd.DataFrame:
    specs = [
        ("all_valid_responses", df["HasResponse"]),
        ("correct_responses", df["IsCorrectResponse"]),
        ("error_responses", df["IsError"]),
        ("left_correct", df["IsCorrectResponse"] & df["TargetSide"].eq("Left")),
        ("right_correct", df["IsCorrectResponse"] & df["TargetSide"].eq("Right")),
    ]
    rows = []
    for label, mask in specs:
        row = {"subset": label}
        row.update(summarize_rt(df.loc[mask, "ReactionTime_ms"]))
        rows.append(row)
    return pd.DataFrame(rows)


def make_half_change_summary(subject_half_summary: pd.DataFrame) -> pd.DataFrame:
    metric_cols = ["accuracy_pct", "correct_rt_mean_ms", "correct_rt_median_ms", "n_trials", "n_correct"]
    wide = subject_half_summary.pivot(index="SubjectID", columns="TrialHalf", values=metric_cols)
    rows = []
    for subject_id in wide.index:
        row = {"SubjectID": subject_id}
        for metric in metric_cols:
            row[f"first_{metric}"] = wide.loc[subject_id, (metric, "FirstHalf")]
            row[f"second_{metric}"] = wide.loc[subject_id, (metric, "SecondHalf")]
        row["delta_accuracy_pct_points"] = row["second_accuracy_pct"] - row["first_accuracy_pct"]
        row["delta_correct_rt_mean_ms"] = row["second_correct_rt_mean_ms"] - row["first_correct_rt_mean_ms"]
        row["delta_correct_rt_median_ms"] = row["second_correct_rt_median_ms"] - row["first_correct_rt_median_ms"]
        rows.append(row)
    return pd.DataFrame(rows)


def make_overall_summary(df: pd.DataFrame, subject_summary: pd.DataFrame, side_summary: pd.DataFrame) -> pd.DataFrame:
    overall_acc = df["IsCorrect"].mean() * 100
    left_acc = side_summary.loc[side_summary["TargetSide"].eq("Left"), "accuracy_pct"].iloc[0]
    right_acc = side_summary.loc[side_summary["TargetSide"].eq("Right"), "accuracy_pct"].iloc[0]
    return pd.DataFrame([{
        "n_subjects": int(df["SubjectID"].nunique()),
        "n_trials": int(len(df)),
        "n_correct": int(df["IsCorrect"].sum()),
        "accuracy": float(df["IsCorrect"].mean()),
        "accuracy_pct": float(overall_acc),
        "accuracy_interpretation": accuracy_label(overall_acc),
        "subject_accuracy_mean_pct": float(subject_summary["accuracy_pct"].mean()),
        "subject_accuracy_min_pct": float(subject_summary["accuracy_pct"].min()),
        "subject_accuracy_max_pct": float(subject_summary["accuracy_pct"].max()),
        "left_accuracy_pct": float(left_acc),
        "right_accuracy_pct": float(right_acc),
        "left_right_accuracy_diff_pct": float(left_acc - right_acc),
        "n_omission": int(df["IsOmission"].sum()),
        "n_error": int(df["IsError"].sum()),
    }])


def write_report(
    out_dir: Path,
    overall: pd.DataFrame,
    subject_summary: pd.DataFrame,
    side_summary: pd.DataFrame,
    rt_summary: pd.DataFrame,
    half_summary: pd.DataFrame,
    half_change_summary: pd.DataFrame,
    fast_errors: pd.DataFrame,
    expected_trials_per_subject: int,
    expected_trials_per_side: int,
) -> None:
    o = overall.iloc[0]
    subject_flags = subject_summary[
        (subject_summary["n_trials"] != expected_trials_per_subject)
        | (subject_summary["left_trials"] != expected_trials_per_side)
        | (subject_summary["right_trials"] != expected_trials_per_side)
        | (subject_summary["accuracy_pct"] < 90)
    ]
    side_lines = [
        f"- {row.TargetSide}: {row.accuracy_pct:.2f}% ({int(row.n_correct)}/{int(row.n_trials)})"
        for row in side_summary.itertuples()
    ]
    rt_lines = [
        f"- {row.subset}: mean={row.mean_ms:.1f} ms, median={row.median_ms:.1f} ms, "
        f"SD={row.sd_ms:.1f} ms, IQR outliers={int(row.iqr_outlier_count)}"
        for row in rt_summary.itertuples()
    ]
    half_lines = [
        f"- {row.TrialHalf}: accuracy={row.accuracy_pct:.2f}% "
        f"({int(row.n_correct)}/{int(row.n_trials)}), "
        f"correct RT mean={row.correct_rt_mean_ms:.1f} ms, "
        f"median={row.correct_rt_median_ms:.1f} ms"
        for row in half_summary.sort_values("TrialHalfOrder").itertuples()
    ]
    half_acc_delta = (
        half_summary.loc[half_summary["TrialHalf"].eq("SecondHalf"), "accuracy_pct"].iloc[0]
        - half_summary.loc[half_summary["TrialHalf"].eq("FirstHalf"), "accuracy_pct"].iloc[0]
    )
    half_rt_delta = (
        half_summary.loc[half_summary["TrialHalf"].eq("SecondHalf"), "correct_rt_mean_ms"].iloc[0]
        - half_summary.loc[half_summary["TrialHalf"].eq("FirstHalf"), "correct_rt_mean_ms"].iloc[0]
    )
    paired_acc_delta = half_change_summary["delta_accuracy_pct_points"].mean()
    paired_rt_delta = half_change_summary["delta_correct_rt_mean_ms"].mean()

    lines = [
        "# Pilot Test Summary",
        "",
        "## Overall Accuracy",
        f"- Subjects: {int(o.n_subjects)}",
        f"- Trials: {int(o.n_trials)}",
        f"- Accuracy: {o.accuracy_pct:.2f}% ({int(o.n_correct)}/{int(o.n_trials)})",
        f"- Interpretation: {o.accuracy_interpretation}",
        "",
        "## Subject Accuracy",
        f"- Mean: {o.subject_accuracy_mean_pct:.2f}%",
        f"- Min: {o.subject_accuracy_min_pct:.2f}%",
        f"- Max: {o.subject_accuracy_max_pct:.2f}%",
        "",
        "## Left/Right Accuracy",
        *side_lines,
        f"- Left - Right difference: {o.left_right_accuracy_diff_pct:.2f} percentage points",
        "",
        "## RT Distribution",
        *rt_lines,
        "",
        "## First/Second Half Change",
        *half_lines,
        f"- Overall delta, Second - First: accuracy={half_acc_delta:+.2f} percentage points, "
        f"correct RT mean={half_rt_delta:+.1f} ms",
        f"- Subject-paired mean delta, Second - First: accuracy={paired_acc_delta:+.2f} percentage points, "
        f"correct RT mean={paired_rt_delta:+.1f} ms",
        "",
        "## Fast Error Check",
        f"- Fast error rows: {len(fast_errors)}",
        "",
    ]

    if len(subject_flags) > 0:
        lines.extend([
            "## Flags",
            "Subjects below 90% accuracy or with unexpected trial counts:",
        ])
        for row in subject_flags.itertuples():
            lines.append(
                f"- {row.SubjectID}: acc={row.accuracy_pct:.2f}%, "
                f"trials={int(row.n_trials)}, left={int(row.left_trials)}, right={int(row.right_trials)}"
            )
        lines.append("")

    (out_dir / "pilot_report.md").write_text("\n".join(lines), encoding="utf-8")


def save_plots(
    df: pd.DataFrame,
    subject_summary: pd.DataFrame,
    side_summary: pd.DataFrame,
    half_summary: pd.DataFrame,
    half_change_summary: pd.DataFrame,
    out_dir: Path,
) -> None:
    plt.figure(figsize=(8, 4))
    plt.bar(subject_summary["SubjectID"], subject_summary["accuracy_pct"])
    plt.axhline(90, color="tab:red", linestyle="--", linewidth=1)
    plt.axhline(95, color="tab:orange", linestyle="--", linewidth=1)
    plt.ylim(0, 105)
    plt.xlabel("Subject")
    plt.ylabel("Accuracy (%)")
    plt.title("Accuracy by Subject")
    plt.tight_layout()
    plt.savefig(out_dir / "subject_accuracy.png", dpi=200)
    plt.close()

    plt.figure(figsize=(4.5, 4))
    plt.bar(side_summary["TargetSide"], side_summary["accuracy_pct"], color=["tab:green", "tab:red"])
    plt.ylim(0, 105)
    plt.xlabel("Target side")
    plt.ylabel("Accuracy (%)")
    plt.title("Accuracy by Side")
    plt.tight_layout()
    plt.savefig(out_dir / "side_accuracy.png", dpi=200)
    plt.close()

    correct = df.loc[df["IsCorrectResponse"], "ReactionTime_ms"]
    errors = df.loc[df["IsError"], "ReactionTime_ms"]
    plt.figure(figsize=(8, 4.5))
    bins = np.linspace(
        max(0, df.loc[df["HasResponse"], "ReactionTime_ms"].min() - 25),
        df.loc[df["HasResponse"], "ReactionTime_ms"].max() + 25,
        30,
    )
    plt.hist(correct, bins=bins, alpha=0.65, label="Correct", density=True)
    if len(errors) > 0:
        plt.hist(errors, bins=bins, alpha=0.65, label="Error", density=True)
    plt.xlabel("Reaction time (ms)")
    plt.ylabel("Density")
    plt.title("RT Distribution")
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_dir / "rt_distribution.png", dpi=200)
    plt.close()

    plot_df = df.loc[df["IsCorrectResponse"], ["SubjectID", "TargetSide", "ReactionTime_ms"]]
    if len(plot_df) > 0:
        labels = sorted(plot_df["SubjectID"].unique())
        data = [plot_df.loc[plot_df["SubjectID"].eq(s), "ReactionTime_ms"].to_numpy() for s in labels]
        plt.figure(figsize=(9, 4.5))
        plt.boxplot(data, tick_labels=labels, showfliers=True)
        plt.xlabel("Subject")
        plt.ylabel("Correct RT (ms)")
        plt.title("Correct RT by Subject")
        plt.tight_layout()
        plt.savefig(out_dir / "rt_by_subject.png", dpi=200)
        plt.close()

    half_summary = half_summary.sort_values("TrialHalfOrder")
    x = np.arange(len(half_summary))
    plt.figure(figsize=(5, 4))
    plt.bar(x, half_summary["accuracy_pct"], color=["tab:blue", "tab:purple"])
    plt.xticks(x, half_summary["TrialHalf"])
    plt.ylim(0, 105)
    plt.xlabel("Trial half")
    plt.ylabel("Accuracy (%)")
    plt.title("Accuracy by Trial Half")
    plt.tight_layout()
    plt.savefig(out_dir / "half_accuracy.png", dpi=200)
    plt.close()

    plt.figure(figsize=(5, 4))
    plt.bar(x, half_summary["correct_rt_mean_ms"], color=["tab:blue", "tab:purple"])
    plt.xticks(x, half_summary["TrialHalf"])
    plt.xlabel("Trial half")
    plt.ylabel("Correct RT mean (ms)")
    plt.title("Correct RT by Trial Half")
    plt.tight_layout()
    plt.savefig(out_dir / "half_correct_rt.png", dpi=200)
    plt.close()

    plt.figure(figsize=(9, 4.5))
    for row in half_change_summary.itertuples():
        plt.plot(
            [0, 1],
            [row.first_correct_rt_mean_ms, row.second_correct_rt_mean_ms],
            marker="o",
            linewidth=1,
            alpha=0.75,
        )
    plt.xticks([0, 1], ["FirstHalf", "SecondHalf"])
    plt.ylabel("Correct RT mean (ms)")
    plt.title("Subject-Paired Correct RT Change")
    plt.tight_layout()
    plt.savefig(out_dir / "subject_half_rt_change.png", dpi=200)
    plt.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze TestGame pilot trial_log.csv files.")
    parser.add_argument("--data-dir", type=Path, default=Path("TestData"))
    parser.add_argument("--out-dir", type=Path, default=Path("Analysis/results_pilot_test"))
    parser.add_argument("--all-sessions", action="store_true", help="Use all test sessions per subject instead of latest only.")
    parser.add_argument("--fast-error-ms", type=float, default=150.0, help="Threshold for suspiciously fast error RTs.")
    parser.add_argument("--expected-trials-per-subject", type=int, default=80)
    parser.add_argument("--expected-trials-per-side", type=int, default=40)
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)

    paths = find_trial_logs(args.data_dir, all_sessions=args.all_sessions)
    df, loaded_files = load_logs(paths)
    df = preprocess(df)

    subject_summary = make_subject_summary(df)
    side_summary = make_side_summary(df, ["TargetSide"])
    subject_side_summary = make_side_summary(df, ["SubjectID", "TargetSide"])
    rt_summary = make_rt_summary(df)
    half_summary = make_side_summary(df, ["TrialHalfOrder", "TrialHalf"])
    subject_half_summary = make_side_summary(df, ["SubjectID", "TrialHalfOrder", "TrialHalf"])
    half_change_summary = make_half_change_summary(subject_half_summary)
    overall = make_overall_summary(df, subject_summary, side_summary)
    fast_errors = df.loc[
        df["IsError"] & df["ReactionTime_ms"].lt(args.fast_error_ms),
        ["SubjectID", "Session", "TrialNumber", "TargetSide", "ResponseSide", "ReactionTime_ms", "SourceFile"],
    ].copy()

    loaded_files.to_csv(args.out_dir / "included_files.csv", index=False, encoding="utf-8-sig")
    overall.to_csv(args.out_dir / "overall_summary.csv", index=False, encoding="utf-8-sig")
    subject_summary.to_csv(args.out_dir / "subject_summary.csv", index=False, encoding="utf-8-sig")
    side_summary.to_csv(args.out_dir / "side_summary.csv", index=False, encoding="utf-8-sig")
    subject_side_summary.to_csv(args.out_dir / "subject_side_summary.csv", index=False, encoding="utf-8-sig")
    rt_summary.to_csv(args.out_dir / "rt_summary.csv", index=False, encoding="utf-8-sig")
    half_summary.to_csv(args.out_dir / "half_summary.csv", index=False, encoding="utf-8-sig")
    subject_half_summary.to_csv(args.out_dir / "subject_half_summary.csv", index=False, encoding="utf-8-sig")
    half_change_summary.to_csv(args.out_dir / "subject_half_change.csv", index=False, encoding="utf-8-sig")
    fast_errors.to_csv(args.out_dir / "fast_errors.csv", index=False, encoding="utf-8-sig")

    write_report(
        args.out_dir,
        overall,
        subject_summary,
        side_summary,
        rt_summary,
        half_summary,
        half_change_summary,
        fast_errors,
        args.expected_trials_per_subject,
        args.expected_trials_per_side,
    )
    save_plots(df, subject_summary, side_summary, half_summary, half_change_summary, args.out_dir)

    o = overall.iloc[0]
    first_half = half_summary.loc[half_summary["TrialHalf"].eq("FirstHalf")].iloc[0]
    second_half = half_summary.loc[half_summary["TrialHalf"].eq("SecondHalf")].iloc[0]
    print(f"Loaded {int(o.n_subjects)} subjects, {int(o.n_trials)} trials.")
    print(f"Overall accuracy: {o.accuracy_pct:.2f}% ({int(o.n_correct)}/{int(o.n_trials)})")
    print(f"Interpretation: {o.accuracy_interpretation}")
    print(f"Left accuracy: {o.left_accuracy_pct:.2f}%")
    print(f"Right accuracy: {o.right_accuracy_pct:.2f}%")
    print(
        "Half change (Second - First): "
        f"accuracy={second_half.accuracy_pct - first_half.accuracy_pct:+.2f} points, "
        f"correct RT={second_half.correct_rt_mean_ms - first_half.correct_rt_mean_ms:+.1f} ms"
    )
    print(f"Fast errors (<{args.fast_error_ms:g} ms): {len(fast_errors)}")
    print(f"Results written to: {args.out_dir}")


if __name__ == "__main__":
    main()
