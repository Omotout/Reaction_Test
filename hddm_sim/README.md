# HDDM Simulation Notes

This folder contains simulation scripts for checking whether the planned
reaction-time experiment can support a descriptive HDDM analysis.

## Current Interpretation

The simulation parameters in `utils.py` are **direct TestData-recovered generic
HDDM parameters**, not a documented HDDM sqrt(2) correction. HDDM fitting and
`hddm.generate.gen_rand_data` are treated as using the same parameter scale.

The current mode prioritizes defensibility of parameter origin over matching a
targeted 90-92% accuracy scenario.

Current group-level parameters:

| parameter | Control | EMS | note |
|---|---:|---:|---|
| `a` | 1.6865 | 1.6865 | TestData generic HDDM recovery; held equal |
| `v` | 5.1379 | 5.1379 | TestData generic HDDM recovery; held equal |
| `t` | 0.2191 | 0.2091 | TestData recovery, with hypothetical 10 ms EMS shortening |
| `z` | 0.5 | 0.5 | unbiased start point |

Current subject-level variability:

| parameter | SD | note |
|---|---:|---|
| `a_sd` | 0.8623 | from generic TestData HDDM subject-level estimates |
| `v_sd` | 1.3421 | from generic TestData HDDM subject-level estimates |
| `t_sd` | 0.00339 | from generic TestData HDDM subject-level estimates |

Earlier checks showed this direct-recovery setting produces higher accuracy
than the raw TestData:

| condition | accuracy | mean RT |
|---|---:|---:|
| Control | about 0.98 | about 398 ms |
| EMS | about 0.98 | about 386 ms |
| difference | about 0.00 | about -12 ms |

This is expected because a correctness-coded generic HDDM fit to high-accuracy
data tends to recover large `a` and `v`. Use this setting when the priority is
"use recovered DDM parameters directly"; use the calibrated setting when the
priority is a conservative 90-92% behavioral scenario.

## Scripts

- `01_simulate_data.py`: generate Control/EMS dummy data from `utils.py`
- `02_fit_hddm.py`: fit one simulated dataset and summarize posterior differences
- `03_run_grid.py`: run sample-size/trial-count grid simulations
- `04_analyze_results.py`: summarize and plot grid results
- `fit_pre_experiment.py`: fit current pre-experiment TestData
- `fit_szul_style_dummy.py`: run one Szul-style descriptive HDDM check
- `visualize_a_rope_impact.py`: visualize how changes in `a` affect RT/accuracy
- `verify_correction.py`: legacy filename; now verifies calibrated parameters, not a correction

## Docker Examples

```powershell
docker run --rm `
  -v ${PWD}:/work `
  -w /work/hddm_sim `
  hcp4715/hddm:latest `
  python verify_correction.py
```

```powershell
docker run --rm `
  -v ${PWD}:/work `
  -w /work/hddm_sim `
  hcp4715/hddm:latest `
  python fit_szul_style_dummy.py --n-subj 20 --n-trials 80 --samples 2000 --burn 1000 --thin 2
```

## Analysis Caution

With 80 trials/subject, HDDM should be treated as a secondary/descriptive
mechanism analysis. The primary behavioral claims should be RT reduction and
accuracy non-inferiority. For `a`, report posterior differences, 95% HDIs, and
ROPE sensitivity rather than relying on a single equivalence threshold.
