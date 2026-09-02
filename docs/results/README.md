# Committed result summaries

These are the aggregated outputs behind the tables in the top-level README.
Raw per-run rows are not committed (`results/` is git-ignored); regenerate them
with the commands below and the summaries will be reproduced exactly.

| File | Produced by |
|---|---|
| `main.summary.csv` | `experiments/benchmark.py --synthetic 12 --size 256 --seeds 3` then `experiments/report.py`; means with 95% cluster bootstrap intervals over covers |
| `main.paired.csv` | the same run: per-cover differences against the `random` baseline |
| `main.robustness.csv` | the same run: recovery rate per attack and method |
| `ablation-summary.csv` | `experiments/ablation.py` - one run per complexity map |
| `ecc-summary.csv` | application-mode runs with `--ecc 0 8 16 32` under localised damage |
| `performance.csv` | `experiments/performance.py --sizes 256 512 1024 2048` |
| `performance.meta.json` | the machine those timings were measured on |

Timings depend on the machine; every other column is deterministic and should
match on any installation whose `python -m adaptivestego selftest` digest agrees with
the reference one.
