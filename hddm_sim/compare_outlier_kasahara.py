import pandas as pd
import numpy as np

df = pd.read_csv('/mnt/user-data/uploads/pre_experiment_data.csv')
df['rt_ms'] = df['rt'] * 1000

correct = df[df['response'] == 1].copy()

print("=" * 70)
print("Kasahara風(下限100/150ms + 上限N ms)固定範囲アプローチの比較")
print("=" * 70)

methods = {
    "100-1000ms (緩い、CRT標準範囲)": (100, 1000),
    "150-700ms": (150, 700),
    "150-600ms": (150, 600),
    "150-550ms": (150, 550),
    "150-500ms": (150, 500),
    "150-475ms": (150, 475),
    "150-450ms": (150, 450),
}

results = []
for name, (lo, hi) in methods.items():
    data = correct[(correct['rt_ms'] >= lo) & (correct['rt_ms'] <= hi)]
    subj_stats = data.groupby('subject_id')['rt_ms'].agg(['mean', 'std', 'count'])
    n_removed = len(correct) - len(data)
    results.append({
        'method': name,
        'excluded': n_removed,
        'excl_pct': round(100*n_removed/len(correct), 1),
        'mean_RT': round(data['rt_ms'].mean(), 1),
        'between_SD': round(subj_stats['mean'].std(), 1),
        'within_SD_mean': round(subj_stats['std'].mean(), 1),
        'within_SD_range': f"{subj_stats['std'].min():.1f}-{subj_stats['std'].max():.1f}",
    })

result_df = pd.DataFrame(results)
print(result_df.to_string(index=False))

# Kasahara同等の除外率 7% を達成するのはどの範囲か
print("\n[Kasaharaは7%除外。同等を狙うなら]")
target_pct = 7.0
for name, (lo, hi) in methods.items():
    data = correct[(correct['rt_ms'] >= lo) & (correct['rt_ms'] <= hi)]
    pct = 100*(len(correct) - len(data))/len(correct)
    if 5 < pct < 10:
        print(f"  {name}: 除外率 {pct:.1f}% (Kasahara基準近い)")

# 各被験者で「最初の2試行除外」もやってみる
print("\n[Kasahara風: 最初の2試行除外 + 150-500ms]")
def skip_first_two(group):
    return group.iloc[2:]
trimmed_first = pd.concat([skip_first_two(g) for _, g in correct.groupby('subject_id')])
filtered = trimmed_first[(trimmed_first['rt_ms'] >= 150) & (trimmed_first['rt_ms'] <= 500)]
n_removed = len(correct) - len(filtered)
subj_stats = filtered.groupby('subject_id')['rt_ms'].agg(['mean', 'std', 'count'])
print(f"  除外率: {100*n_removed/len(correct):.1f}%")
print(f"  全体平均: {filtered['rt_ms'].mean():.1f} ms")
print(f"  被験者間SD: {subj_stats['mean'].std():.1f} ms")
print(f"  被験者内SD平均: {subj_stats['std'].mean():.1f} ms")
print(f"  被験者内SD範囲: {subj_stats['std'].min():.1f}-{subj_stats['std'].max():.1f} ms")
