"""Statistics that respect the clustered design of the experiments.

Several embedding realisations of the same cover are not independent
observations: they share the image, and image content dominates almost every
metric here. Treating them as independent (n = images x replicates) shrinks the
confidence intervals and overstates the evidence.

Everything below therefore averages within a cover first and then resamples
whole covers - a cluster bootstrap. Comparisons between methods are paired on
the cover, because every method is run on exactly the same images.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = ["per_cluster_means", "cluster_summary", "paired_comparison",
           "BOOTSTRAP_SAMPLES"]

BOOTSTRAP_SAMPLES = 10_000
BOOTSTRAP_SEED = 20260902


def per_cluster_means(df: pd.DataFrame, value: str, by: list[str],
                      cluster: str = "image") -> pd.DataFrame:
    """Average the replicates of each cluster, giving one row per cluster."""
    return (df.groupby([*by, cluster], as_index=False)[value]
              .mean()
              .rename(columns={value: "value"}))


def _bootstrap_ci(values: np.ndarray, samples: int, rng) -> tuple[float, float]:
    """Percentile bootstrap interval for the mean of independent clusters."""
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if values.size < 2:
        return (float("nan"), float("nan"))
    draws = rng.integers(0, values.size, size=(samples, values.size))
    means = values[draws].mean(axis=1)
    return tuple(float(v) for v in np.percentile(means, [2.5, 97.5]))


def cluster_summary(df: pd.DataFrame, value: str, by: list[str],
                    cluster: str = "image",
                    samples: int = BOOTSTRAP_SAMPLES) -> pd.DataFrame:
    """Mean of a metric with a 95% cluster bootstrap interval.

    ``n_clusters`` is the real sample size; ``n_runs`` is only reported so that
    the amount of computation behind a number stays visible.
    """
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    per_cluster = per_cluster_means(df, value, by, cluster)
    runs = df.groupby(by, as_index=False)[value].size().rename(
        columns={"size": "n_runs"})

    rows = []
    for keys, group in per_cluster.groupby(by):
        keys = keys if isinstance(keys, tuple) else (keys,)
        low, high = _bootstrap_ci(group["value"].to_numpy(), samples, rng)
        rows.append({**dict(zip(by, keys, strict=True)),
                     "mean": float(group["value"].mean()),
                     "ci_low": low, "ci_high": high,
                     "n_clusters": int(group["value"].size)})
    out = pd.DataFrame(rows)
    return out.merge(runs, on=by, how="left")


def paired_comparison(df: pd.DataFrame, value: str, baseline: str,
                      group_col: str = "method", within: list[str] | None = None,
                      cluster: str = "image",
                      samples: int = BOOTSTRAP_SAMPLES) -> pd.DataFrame:
    """Compare every group against a baseline, paired on the cluster.

    The design is paired: every method sees the same covers. Comparing the two
    marginal means throws that away, so the difference is formed per cover and
    the covers are then bootstrapped.
    """
    within = within or []
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    per_cluster = per_cluster_means(df, value, [group_col, *within], cluster)

    rows = []
    for keys, block in (per_cluster.groupby(within) if within
                        else [((), per_cluster)]):
        keys = keys if isinstance(keys, tuple) else (keys,)
        wide = block.pivot_table(index=cluster, columns=group_col, values="value")
        if baseline not in wide.columns:
            continue
        for method in wide.columns:
            if method == baseline:
                continue
            paired = wide[[baseline, method]].dropna()
            if paired.empty:
                continue
            diff = (paired[method] - paired[baseline]).to_numpy()
            low, high = _bootstrap_ci(diff, samples, rng)
            ratio = (paired[method] / paired[baseline].replace(0, np.nan)).to_numpy()
            rows.append({
                **dict(zip(within, keys, strict=True)),
                group_col: method, "baseline": baseline,
                "mean_diff": float(diff.mean()),
                "diff_ci_low": low, "diff_ci_high": high,
                "median_ratio": float(np.nanmedian(ratio)) if ratio.size else float("nan"),
                "better_on": int((diff < 0).sum()), "n_clusters": int(diff.size),
                "significant": bool(low < 0 and high < 0) or bool(low > 0 and high > 0),
            })
    return pd.DataFrame(rows)
