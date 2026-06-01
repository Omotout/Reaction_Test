"""
Visualize reaction-time distributions for each subject.

Input defaults to pre_experiment_data.csv produced by extract_pre_experiment.py.
Outputs a self-contained HTML file with SVG histograms and a CSV summary.
"""

import argparse
import html
import os

import numpy as np
import pandas as pd


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def fmt_ms(value, digits=1):
    if pd.isna(value):
        return ""
    return f"{value:.{digits}f}"


def load_data(path, correct_only=True):
    df = pd.read_csv(path)
    required = {"subject_id", "rt", "response"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    df = df.copy()
    df["subject_id"] = df["subject_id"].astype(str).str.zfill(3)
    df["rt_ms"] = pd.to_numeric(df["rt"], errors="coerce") * 1000.0
    df["correct"] = pd.to_numeric(df["response"], errors="coerce")
    df = df.dropna(subset=["subject_id", "rt_ms"])
    if correct_only:
        df = df[df["correct"] == 1].copy()
    return df


def subject_summary(df):
    return (
        df.groupby("subject_id", as_index=False)
        .agg(
            n_trials=("rt_ms", "count"),
            accuracy=("correct", "mean"),
            mean_rt_ms=("rt_ms", "mean"),
            median_rt_ms=("rt_ms", "median"),
            sd_rt_ms=("rt_ms", "std"),
            min_rt_ms=("rt_ms", "min"),
            p10_rt_ms=("rt_ms", lambda x: np.percentile(x, 10)),
            p25_rt_ms=("rt_ms", lambda x: np.percentile(x, 25)),
            p75_rt_ms=("rt_ms", lambda x: np.percentile(x, 75)),
            p90_rt_ms=("rt_ms", lambda x: np.percentile(x, 90)),
            max_rt_ms=("rt_ms", "max"),
        )
        .sort_values("subject_id")
    )


def scale(value, domain_min, domain_max, range_min, range_max):
    if domain_max == domain_min:
        return (range_min + range_max) / 2.0
    frac = (value - domain_min) / (domain_max - domain_min)
    return range_min + frac * (range_max - range_min)


def histogram_panel(subject_id, values, summary_row, bins, x_min, x_max, width, height):
    margin_left = 44
    margin_right = 16
    margin_top = 34
    margin_bottom = 36
    plot_w = width - margin_left - margin_right
    plot_h = height - margin_top - margin_bottom
    baseline = margin_top + plot_h

    counts, edges = np.histogram(values, bins=bins, range=(x_min, x_max))
    max_count = max(int(counts.max()), 1)
    bar_gap = 1.0
    rects = []
    for count, left, right in zip(counts, edges[:-1], edges[1:]):
        x0 = scale(left, x_min, x_max, margin_left, margin_left + plot_w)
        x1 = scale(right, x_min, x_max, margin_left, margin_left + plot_w)
        bar_h = (count / max_count) * plot_h
        rects.append(
            f'<rect x="{x0 + bar_gap / 2:.2f}" y="{baseline - bar_h:.2f}" '
            f'width="{max(0, x1 - x0 - bar_gap):.2f}" height="{bar_h:.2f}" '
            'fill="#6f8f72" opacity="0.82" />'
        )

    mean_x = scale(summary_row["mean_rt_ms"], x_min, x_max, margin_left, margin_left + plot_w)
    median_x = scale(summary_row["median_rt_ms"], x_min, x_max, margin_left, margin_left + plot_w)
    p25_x = scale(summary_row["p25_rt_ms"], x_min, x_max, margin_left, margin_left + plot_w)
    p75_x = scale(summary_row["p75_rt_ms"], x_min, x_max, margin_left, margin_left + plot_w)
    box_y = baseline + 14

    tick_values = np.linspace(x_min, x_max, 5)
    ticks = []
    for tick in tick_values:
        x = scale(tick, x_min, x_max, margin_left, margin_left + plot_w)
        ticks.append(
            f'<line x1="{x:.2f}" y1="{baseline:.2f}" x2="{x:.2f}" y2="{baseline + 4:.2f}" '
            'stroke="#697066" stroke-width="1" />'
        )
        ticks.append(
            f'<text x="{x:.2f}" y="{baseline + 20:.2f}" text-anchor="middle" '
            'class="axis-label">'
            f"{tick:.0f}</text>"
        )

    title = (
        f"P{subject_id}  n={int(summary_row['n_trials'])}  "
        f"mean={fmt_ms(summary_row['mean_rt_ms'])} ms  "
        f"median={fmt_ms(summary_row['median_rt_ms'])} ms  "
        f"acc={summary_row['accuracy'] * 100:.1f}%"
    )

    return f"""
    <svg class="panel" viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(title)}">
      <rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff" />
      <text x="{margin_left}" y="20" class="panel-title">{html.escape(title)}</text>
      <line x1="{margin_left}" y1="{baseline}" x2="{margin_left + plot_w}" y2="{baseline}" stroke="#697066" />
      <line x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{baseline}" stroke="#d5d9d0" />
      {''.join(rects)}
      <rect x="{p25_x:.2f}" y="{box_y - 4:.2f}" width="{max(1, p75_x - p25_x):.2f}" height="8" fill="#d4a84f" opacity="0.65" />
      <line x1="{median_x:.2f}" y1="{margin_top}" x2="{median_x:.2f}" y2="{baseline + 12}" stroke="#b84435" stroke-width="2" />
      <line x1="{mean_x:.2f}" y1="{margin_top}" x2="{mean_x:.2f}" y2="{baseline}" stroke="#2f6f9f" stroke-width="2" stroke-dasharray="4 3" />
      {''.join(ticks)}
      <text x="{margin_left - 8}" y="{margin_top + 4}" text-anchor="end" class="axis-label">{max_count}</text>
      <text x="{margin_left - 8}" y="{baseline + 4}" text-anchor="end" class="axis-label">0</text>
    </svg>
    """


def render_html(df, summary, title, bins, out_path, correct_only=True):
    x_min = max(0.0, np.floor(df["rt_ms"].min() / 25.0) * 25.0)
    x_max = np.ceil(df["rt_ms"].max() / 25.0) * 25.0
    panels = []
    for row in summary.itertuples(index=False):
        subject_id = row.subject_id
        values = df.loc[df["subject_id"] == subject_id, "rt_ms"].to_numpy()
        panels.append(
            histogram_panel(
                subject_id,
                values,
                row._asdict(),
                bins=bins,
                x_min=x_min,
                x_max=x_max,
                width=520,
                height=230,
            )
        )

    table_rows = []
    for row in summary.to_dict("records"):
        table_rows.append(
            "<tr>"
            f"<td>P{html.escape(row['subject_id'])}</td>"
            f"<td>{int(row['n_trials'])}</td>"
            f"<td>{row['accuracy'] * 100:.1f}%</td>"
            f"<td>{fmt_ms(row['mean_rt_ms'])}</td>"
            f"<td>{fmt_ms(row['median_rt_ms'])}</td>"
            f"<td>{fmt_ms(row['sd_rt_ms'])}</td>"
            f"<td>{fmt_ms(row['p25_rt_ms'])}</td>"
            f"<td>{fmt_ms(row['p75_rt_ms'])}</td>"
            f"<td>{fmt_ms(row['min_rt_ms'])}</td>"
            f"<td>{fmt_ms(row['max_rt_ms'])}</td>"
            "</tr>"
        )

    trial_scope = "Correct trials only" if correct_only else "All trials"
    document = f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html.escape(title)}</title>
  <style>
    body {{
      margin: 24px;
      font-family: Arial, "Yu Gothic", sans-serif;
      color: #1f241f;
      background: #f6f7f4;
    }}
    h1 {{
      margin: 0 0 6px;
      font-size: 24px;
      letter-spacing: 0;
    }}
    .note {{
      margin: 0 0 18px;
      color: #586156;
      font-size: 14px;
    }}
    .legend {{
      display: flex;
      gap: 18px;
      align-items: center;
      margin-bottom: 18px;
      font-size: 13px;
      color: #3e473d;
      flex-wrap: wrap;
    }}
    .key {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }}
    .swatch {{
      width: 18px;
      height: 3px;
      display: inline-block;
      background: #b84435;
    }}
    .swatch.mean {{
      background: repeating-linear-gradient(90deg, #2f6f9f 0 5px, transparent 5px 8px);
      border-top: 2px solid #2f6f9f;
      height: 0;
    }}
    .swatch.iqr {{
      height: 10px;
      background: #d4a84f;
      opacity: 0.75;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(440px, 1fr));
      gap: 14px;
      margin-bottom: 24px;
    }}
    .panel {{
      width: 100%;
      background: #ffffff;
      border: 1px solid #d9ddd3;
      border-radius: 6px;
      box-shadow: 0 1px 2px rgba(25, 30, 20, 0.05);
    }}
    .panel-title {{
      font-size: 14px;
      font-weight: 700;
      fill: #253025;
    }}
    .axis-label {{
      font-size: 10px;
      fill: #697066;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: #ffffff;
      border: 1px solid #d9ddd3;
      border-radius: 6px;
      overflow: hidden;
      font-size: 13px;
    }}
    th, td {{
      padding: 8px 10px;
      border-bottom: 1px solid #ecefe9;
      text-align: right;
    }}
    th:first-child, td:first-child {{
      text-align: left;
    }}
    th {{
      background: #e8ece5;
      color: #2f382e;
      font-weight: 700;
    }}
    tr:last-child td {{
      border-bottom: 0;
    }}
  </style>
</head>
<body>
  <h1>{html.escape(title)}</h1>
  <p class="note">{trial_scope}. RT axis is shared across subjects: {x_min:.0f}-{x_max:.0f} ms. Histograms use {bins} bins.</p>
  <div class="legend">
    <span class="key"><span class="swatch"></span>Median</span>
    <span class="key"><span class="swatch mean"></span>Mean</span>
    <span class="key"><span class="swatch iqr"></span>IQR</span>
  </div>
  <div class="grid">
    {''.join(panels)}
  </div>
  <table>
    <thead>
      <tr>
        <th>Subject</th><th>n</th><th>Acc</th><th>Mean</th><th>Median</th><th>SD</th>
        <th>P25</th><th>P75</th><th>Min</th><th>Max</th>
      </tr>
    </thead>
    <tbody>
      {''.join(table_rows)}
    </tbody>
  </table>
</body>
</html>
"""
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(document)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default=os.path.join(SCRIPT_DIR, "pre_experiment_data.csv"))
    parser.add_argument("--outdir", default=os.path.join(SCRIPT_DIR, "results_subject_rt_distributions"))
    parser.add_argument("--bins", type=int, default=24)
    parser.add_argument("--include-incorrect", action="store_true")
    args = parser.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    correct_only = not args.include_incorrect
    df = load_data(args.data, correct_only=correct_only)
    summary = subject_summary(df)

    summary_path = os.path.join(args.outdir, "subject_rt_summary.csv")
    html_path = os.path.join(args.outdir, "subject_rt_distributions.html")
    summary.to_csv(summary_path, index=False)
    render_html(
        df,
        summary,
        title="Subject Reaction Time Distributions",
        bins=args.bins,
        out_path=html_path,
        correct_only=correct_only,
    )

    print("Subject RT distributions")
    print(f"Trial scope: {'correct only' if correct_only else 'all trials'}")
    print(summary.round(3).to_string(index=False))
    print()
    print(f"Wrote: {summary_path}")
    print(f"Wrote: {html_path}")


if __name__ == "__main__":
    main()
