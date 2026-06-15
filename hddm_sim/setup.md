# 環境構築手順

## HDDMの注意点

HDDMは2024年現在、**Python 3.7〜3.9**でしか安定動作しない。最新Pythonでは依存関係(特にPyMC2)で詰む。**conda環境で隔離**するのが鉄則。

## 推奨環境

- Python 3.8
- HDDM 0.9.x
- macOS (Apple Silicon含む) / Linux (x86_64) / WSL2

Windows nativeはコンパイル周りで詰みがちなのでWSL2推奨。

## 手順

### Option A: conda環境(推奨)

```bash
# environment.ymlから一括構築
conda env create -f environment.yml
conda activate hddm_sim

# 動作確認
python -c "import hddm; print(hddm.__version__)"
```

### Option B: 手動構築

```bash
conda create -n hddm_sim python=3.8 -y
conda activate hddm_sim

# 数値計算スタック
conda install -y numpy=1.22 scipy=1.8 pandas=1.4 matplotlib seaborn

# HDDMとMCMC
pip install hddm==0.9.8
pip install kabuki==0.6.5

# 並列化と進捗表示
pip install joblib tqdm

# 動作確認
python -c "import hddm; data, params = hddm.generate.gen_rand_data({'a': 0.7, 'v': 1.5, 't': 0.3}, size=20); print(data.head())"
```

## トラブルシューティング

### `ImportError: No module named 'pymc'` (HDDMが内部で使うPyMC2が見つからない)

```bash
pip install pymc==2.3.8
```

PyMC2は古いがHDDMはこれに依存。最新のPyMCではない。

### Apple SiliconでHDDMフィットがクラッシュ

HDDMの一部Cython拡張がx86_64想定で書かれている。Rosetta 2で動かす:

```bash
arch -x86_64 zsh
conda env create -f environment.yml
arch -x86_64 conda activate hddm_sim
arch -x86_64 python 03_run_grid.py
```

または、Docker使う:
```bash
docker run -it --rm -v $(pwd):/work python:3.8-slim bash
cd /work && pip install -r requirements.txt && python 03_run_grid.py
```

### `RuntimeError: Cannot pickle ...` (joblibの並列化エラー)

joblibの`backend='multiprocessing'`を試す:
```python
Parallel(n_jobs=8, backend='multiprocessing')(...)
```

## ハードウェア推奨

- **CPU**: 物理8コア以上推奨(並列化で大幅短縮)
- **RAM**: 16GB以上(HDDMフィット中に各プロセス約1GB使う)
- **時間**: フルグリッド ≈ 4〜8時間 (8コア並列時)

研究室のサーバーマシンを使えるならそちらで。
