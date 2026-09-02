"""Classical (non neural) steganalysis attacks used as a baseline.

They make detectability measurable before a neural detector exists, and they
show the difference between methods: chi-square and SPA break LSB replacement
but are blind to LSB matching.

References:
  A. Westfeld, A. Pfitzmann. Attacks on Steganographic Systems (1999) - chi2.
  S. Dumitrescu, X. Wu, Z. Wang. Detection of LSB steganography via sample
  pair analysis (2003) - SPA.
"""

from __future__ import annotations

import numpy as np

__all__ = ["chi_square_attack", "sample_pair_analysis", "lsb_plane_stats",
           "quick_report"]


def _chi2_sf(stat: float, dof: int) -> float:
    """P(X > stat) for a chi-square distribution with dof degrees of freedom."""
    try:
        from scipy.stats import chi2
        return float(chi2.sf(stat, dof))
    except ImportError:  # pragma: no cover - fallback when scipy is absent
        import math

        # Regularised upper incomplete gamma function: series branch for small
        # x, continued fraction otherwise (Numerical Recipes, gammq).
        a, x = dof / 2.0, stat / 2.0
        if x <= 0:
            return 1.0
        if x < a + 1.0:
            term = 1.0 / a
            total, n = term, 0
            while abs(term) > 1e-15 * abs(total) and n < 10000:
                n += 1
                term *= x / (a + n)
                total += term
            return float(1.0 - total * math.exp(-x + a * math.log(x) - math.lgamma(a)))
        b, c = x + 1.0 - a, 1e300
        d = 1.0 / b
        h = d
        for i in range(1, 10000):
            an = -i * (i - a)
            b += 2.0
            d = an * d + b
            if abs(d) < 1e-300:
                d = 1e-300
            c = b + an / c
            if abs(c) < 1e-300:
                c = 1e-300
            d = 1.0 / d
            delta = d * c
            h *= delta
            if abs(delta - 1.0) < 1e-15:
                break
        return float(math.exp(-x + a * math.log(x) - math.lgamma(a)) * h)


def chi_square_attack(img: np.ndarray, n_blocks: int = 1) -> dict:
    """Chi-square attack against LSB replacement.

    Returns the probability that the lowest bit plane has been levelled out by
    embedding: close to one means suspicious, close to zero means clean. With
    n_blocks > 1 the image is split into consecutive blocks, which exposes
    sequential embedding as a high probability in the first blocks only.
    """
    flat = np.asarray(img).reshape(-1)
    probabilities = []
    for chunk in np.array_split(flat, n_blocks):
        hist = np.bincount(chunk, minlength=256).astype(np.float64)
        even, odd = hist[0::2], hist[1::2]
        expected = (even + odd) / 2.0
        keep = expected > 4.0            # ignore bins with a tiny expectation
        if keep.sum() < 2:
            probabilities.append(0.0)
            continue
        stat = float(np.sum((even[keep] - expected[keep]) ** 2 / expected[keep]))
        probabilities.append(_chi2_sf(stat, int(keep.sum()) - 1))
    return {"p_embedded_max": float(np.max(probabilities)),
            "p_embedded_mean": float(np.mean(probabilities)),
            "blocks": [float(p) for p in probabilities]}


def sample_pair_analysis(img: np.ndarray) -> float:
    """SPA estimate of the fraction of samples used for LSB replacement.

    Computed over horizontally adjacent pixel pairs of each channel and
    averaged over the channels.
    """
    a = np.asarray(img)
    if a.ndim == 2:
        a = a[:, :, None]
    estimates = []
    for c in range(a.shape[2]):
        channel = a[:, :, c].astype(np.int32)
        u, v = channel[:, :-1].ravel(), channel[:, 1:].ravel()
        n = u.size
        if n == 0:
            continue
        v_even = (v % 2) == 0
        x = int(np.count_nonzero((v_even & (u < v)) | (~v_even & (u > v))))
        y = int(np.count_nonzero((v_even & (u > v)) | (~v_even & (u < v))))
        z = int(np.count_nonzero(u == v))
        w = int(np.count_nonzero((u ^ v) == 1))

        qa = 0.5 * (w + z)
        qb = 2.0 * x - n
        qc = float(y - x)
        if abs(qa) < 1e-9:
            p = 0.0 if abs(qb) < 1e-9 else -qc / qb
        else:
            disc = qb * qb - 4.0 * qa * qc
            if disc < 0:
                continue
            root = np.sqrt(disc)
            p = min([(-qb - root) / (2 * qa), (-qb + root) / (2 * qa)], key=abs)
        estimates.append(float(np.clip(p, 0.0, 1.0)))
    return float(np.mean(estimates)) if estimates else 0.0


def lsb_plane_stats(img: np.ndarray) -> dict:
    """Ones ratio and lag-1 autocorrelation of the lowest bit plane."""
    lsb = (np.asarray(img) & 1).astype(np.float64)
    flat = lsb.reshape(-1)
    centered = flat - flat.mean()
    denom = float(np.dot(centered, centered))
    corr = float(np.dot(centered[:-1], centered[1:]) / denom) if denom else 0.0
    return {"ones_ratio": float(flat.mean()), "autocorr_lag1": corr}


def quick_report(img: np.ndarray) -> dict:
    """Classical steganalysis summary for a single image."""
    chi = chi_square_attack(img, n_blocks=8)
    return {
        "chi2_p_max": chi["p_embedded_max"],
        "chi2_p_mean": chi["p_embedded_mean"],
        "spa_rate": sample_pair_analysis(img),
        **lsb_plane_stats(img),
    }
