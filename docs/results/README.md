# Committed result summaries

These are the aggregated outputs behind the tables in the top-level README.
Raw per-run rows are not committed (`results/` is git-ignored); regenerate them
with the commands below and the summaries will be reproduced exactly.

| File | Produced by |
|---|---|
| `bossbase-smoke.summary.csv` | `experiments/benchmark.py --config configs/bossbase.json` then `experiments/report.py`; 200 BOSSBase covers, three realisations each |
| `bossbase-smoke.paired.csv` | the same run: per-cover differences against the `random` baseline |
| `ablation-summary-bossbase.csv` | `experiments/ablation.py` over the same 200 covers |
| `bossbase-manifest.json` | which BOSSBase files the runs used, and a digest of the collection |
| `main.summary.csv` | the same on 12 synthetic covers, kept for comparison with the real data |
| `main.paired.csv` | the same run: per-cover differences against the `random` baseline |
| `main.robustness.csv` | the same run: recovery rate per attack and method |
| `ablation-summary.csv` | `experiments/ablation.py` - one run per complexity map |
| `ecc-summary.csv` | application-mode runs with `--ecc 0 8 16 32` under localised damage |
| `performance.csv` | `experiments/performance.py --sizes 256 512 1024 2048` |
| `performance.meta.json` | the machine those timings were measured on |
| `detector-calibration.json` | `experiments/calibrate_detectors.py --skip 5000 --limit 150`; the thresholds in `analysis.py` and the detection table in the README come from this file. `--skip 5000` keeps it clear of the half of BOSSBase the shipped model was trained on |

Timings depend on the machine; every other column is deterministic and should
match on any installation whose `python -m adaptivestego selftest` digest agrees with
the reference one.
