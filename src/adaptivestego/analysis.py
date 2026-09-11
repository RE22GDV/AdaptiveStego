"""Classical (non neural) steganalysis, used as a baseline and as a tool.

No single statistic detects steganography. Each of the detectors here answers
a narrower question, and they fail in different places, which is the reason to
run all of them:

  chi-square      does the lowest bit plane look levelled out?
  SPA, RS, WS     how many samples were changed by LSB *replacement*?
  HCF-COM         has the histogram been smoothed, as +/-1 embedding does?
  bit planes      does the lowest plane look like noise at all?

The first four break LSB replacement and are blind to LSB matching; HCF-COM is
the other way round. A verdict that mentions only one of them is worth very
little, so :func:`quick_report` runs them together and :func:`verdict` states
what the combination supports.

References:
  A. Westfeld, A. Pfitzmann. Attacks on Steganographic Systems (1999) - chi2.
  J. Fridrich, M. Goljan, R. Du. Reliable detection of LSB steganography in
  color and grayscale images (2001) - RS analysis.
  S. Dumitrescu, X. Wu, Z. Wang. Detection of LSB steganography via sample
  pair analysis (2003) - SPA.
  J. Fridrich, M. Goljan. On estimation of secret message length in LSB
  steganography in spatial domain (2004) - weighted stego image.
  A. Ker. Steganalysis of LSB matching in grayscale images (2005) - HCF-COM
  with downsampling calibration.
  A. Ker, R. Bohme. Revisiting weighted stego-image steganalysis (2008).
"""

from __future__ import annotations

import numpy as np

__all__ = ["chi_square_attack", "sample_pair_analysis", "rs_analysis",
           "weighted_stego", "hcf_com", "lsb_plane_stats", "bit_plane_profile",
           "quick_report", "verdict", "DETECTORS"]


def _channels(img: np.ndarray) -> list[np.ndarray]:
    """The image as a list of 2D planes, whatever its shape."""
    a = np.asarray(img)
    if a.ndim == 2:
        return [a]
    return [a[:, :, c] for c in range(a.shape[2])]


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
    estimates = []
    for plane in _channels(img):
        channel = plane.astype(np.int32)
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


# ---------------------------------------------------------------------------
# RS analysis
# ---------------------------------------------------------------------------
def _flip_lsb(values: np.ndarray) -> np.ndarray:
    """F1: the LSB flip, 0<->1, 2<->3, ..., 254<->255."""
    return values ^ 1


def _flip_dual(values: np.ndarray) -> np.ndarray:
    """F-1: the shifted flip, -1<->0, 1<->2, ..., 255<->256.

    Defined as F1(x + 1) - 1, which is why it is the natural partner of F1: it
    moves a sample the other way across the pair boundary.
    """
    return ((values + 1) ^ 1) - 1


def _rs_counts(groups: np.ndarray, mask: np.ndarray) -> tuple[float, float]:
    """Fractions of regular and singular groups for one mask.

    ``groups`` is (n_groups, group_size) of int32; ``mask`` says which members
    of a group are flipped, with +1 for F1 and -1 for F-1.
    """
    def smoothness(block: np.ndarray) -> np.ndarray:
        return np.abs(np.diff(block, axis=1)).sum(axis=1)

    flipped = groups.copy()
    up = mask > 0
    down = mask < 0
    if up.any():
        flipped[:, up] = _flip_lsb(groups[:, up])
    if down.any():
        flipped[:, down] = _flip_dual(groups[:, down])

    before = smoothness(groups)
    after = smoothness(flipped)
    n = float(len(groups))
    return float(np.count_nonzero(after > before) / n), \
        float(np.count_nonzero(after < before) / n)


def rs_analysis(img: np.ndarray, mask=(0, 1, 1, 0)) -> dict:
    """RS analysis: an independent estimate of the LSB replacement rate.

    The image is cut into groups of four horizontally adjacent samples and
    each group is classified by whether a masked LSB flip makes it smoother or
    rougher. In a natural image flipping adds roughness, so regular groups
    outnumber singular ones; LSB replacement pushes the two counts together,
    and the rate is read off the quadratic that fits the four curves.

    Returns the estimated rate together with the raw group fractions, which
    are what the estimate is made of and are worth seeing when it misbehaves.
    """
    mask = np.asarray(mask, dtype=np.int8)
    size = mask.size
    r_m = s_m = r_neg = s_neg = 0.0
    r_m1 = s_m1 = r_neg1 = s_neg1 = 0.0
    planes = 0

    for plane in _channels(img):
        flat = plane.reshape(-1)
        n_groups = flat.size // size
        if n_groups < 16:
            continue
        groups = flat[:n_groups * size].reshape(n_groups, size).astype(np.int32)
        # The same measurement on the image with every LSB flipped gives the
        # second point the quadratic needs; it corresponds to a fully embedded
        # image, which is the far end of the curve.
        groups_flipped = _flip_lsb(groups)

        a, b = _rs_counts(groups, mask)
        r_m, s_m = r_m + a, s_m + b
        a, b = _rs_counts(groups, -mask)
        r_neg, s_neg = r_neg + a, s_neg + b
        a, b = _rs_counts(groups_flipped, mask)
        r_m1, s_m1 = r_m1 + a, s_m1 + b
        a, b = _rs_counts(groups_flipped, -mask)
        r_neg1, s_neg1 = r_neg1 + a, s_neg1 + b
        planes += 1

    if not planes:
        return {"rate": 0.0, "rm": 0.0, "sm": 0.0, "r_m": 0.0, "s_m": 0.0}

    r_m, s_m, r_neg, s_neg = (v / planes for v in (r_m, s_m, r_neg, s_neg))
    r_m1, s_m1, r_neg1, s_neg1 = (v / planes
                                  for v in (r_m1, s_m1, r_neg1, s_neg1))

    # d and dn are the gaps for the positive and the negative mask; the suffix
    # 1 marks the measurement on the LSB-flipped image.
    d0, dn0 = r_m - s_m, r_neg - s_neg
    d1, dn1 = r_m1 - s_m1, r_neg1 - s_neg1

    a = 2.0 * (d1 + d0)
    b = dn0 - dn1 - d1 - 3.0 * d0
    c = d0 - dn0
    if abs(a) < 1e-12:
        root = 0.0 if abs(b) < 1e-12 else -c / b
    else:
        disc = b * b - 4.0 * a * c
        if disc < 0:
            root = 0.0
        else:
            sq = float(np.sqrt(disc))
            root = min([(-b + sq) / (2 * a), (-b - sq) / (2 * a)], key=abs)

    denominator = root - 0.5
    rate = 0.0 if abs(denominator) < 1e-12 else root / denominator
    return {"rate": float(np.clip(rate, 0.0, 1.0)),
            "rm": float(r_m), "sm": float(s_m),
            "r_m": float(r_neg), "s_m": float(s_neg)}


# ---------------------------------------------------------------------------
# weighted stego image
# ---------------------------------------------------------------------------
_WS_FILTER = np.array([[-1.0, 2.0, -1.0],
                       [2.0, 0.0, 2.0],
                       [-1.0, 2.0, -1.0]]) / 4.0


def _neighbourhood(plane: np.ndarray) -> np.ndarray:
    """A (9, H, W) stack of the 3x3 neighbourhood, edges replicated."""
    padded = np.pad(plane, 1, mode="edge")
    h, w = plane.shape
    return np.stack([padded[dy:dy + h, dx:dx + w]
                     for dy in range(3) for dx in range(3)])


def weighted_stego(img: np.ndarray) -> float:
    """Weighted stego-image estimate of the LSB replacement rate.

    Each sample is compared with what its neighbours predict it should be. If
    the difference correlates with the sample's own lowest bit, that bit was
    written rather than grown: a cover image gives no such correlation. Flat
    areas predict well and textured ones do not, so the samples are weighted
    by the inverse of their local variance, which is what makes this the
    sharpest of the simple estimators at low payloads.

    The returned number is the embedding rate (bits per sample), twice the
    change rate, clipped to [0, 1].
    """
    estimates = []
    for plane in _channels(img):
        s = plane.astype(np.float64)
        stack = _neighbourhood(s)
        weights = _WS_FILTER.reshape(9, 1, 1)
        mu = (stack * weights).sum(axis=0)

        neighbours = np.delete(stack, 4, axis=0)         # drop the centre
        variance = neighbours.var(axis=0)
        w = 1.0 / (1.0 + variance)
        w /= w.sum()

        # s - F1(s) is +1 where the lowest bit is 1 and -1 where it is 0.
        parity = 2.0 * (plane.astype(np.int64) & 1) - 1.0
        beta = float((w * (s - mu) * parity).sum())
        estimates.append(2.0 * beta)

    if not estimates:
        return 0.0
    return float(np.clip(np.mean(estimates), 0.0, 1.0))


# ---------------------------------------------------------------------------
# histogram characteristic function - the LSB matching detector
# ---------------------------------------------------------------------------
def _com(histogram: np.ndarray) -> float:
    """Centre of mass of the magnitude of the histogram's Fourier transform."""
    spectrum = np.abs(np.fft.fft(histogram))
    half = spectrum[:len(spectrum) // 2]
    total = half.sum()
    if total <= 0:
        return 0.0
    return float((np.arange(half.size) * half).sum() / total)


def hcf_com(img: np.ndarray) -> dict:
    """Calibrated HCF centre of mass, after Ker (2005).

    Every embedding method that moves samples by +/-1 convolves the histogram
    with a small kernel, and convolution suppresses its high frequencies. The
    centre of mass of the histogram's spectrum therefore falls. How far it
    should be in the first place depends on the image, so it is calibrated
    against the same image downsampled 2x1, whose histogram is close to the
    cover's and is barely affected by embedding.

    A ratio near 1 is a clean image; embedding pushes it below 1. This is the
    only detector here that sees LSB matching, which chi-square, SPA, RS and
    WS are blind to by construction.
    """
    ratios, raw, calibrated = [], [], []
    for plane in _channels(img):
        if plane.shape[1] < 2:
            continue
        image_com = _com(np.bincount(plane.reshape(-1), minlength=256)
                         .astype(np.float64))
        # The cover estimate: average horizontally adjacent pairs. Ker's
        # down-sampling; it keeps the image statistics and drops the embedding.
        pairs = plane[:, :plane.shape[1] // 2 * 2].astype(np.uint16)
        down = ((pairs[:, 0::2] + pairs[:, 1::2]) // 2).astype(np.uint8)
        down_com = _com(np.bincount(down.reshape(-1), minlength=256)
                        .astype(np.float64))
        raw.append(image_com)
        calibrated.append(down_com)
        ratios.append(image_com / down_com if down_com > 0 else 1.0)

    if not ratios:
        return {"ratio": 1.0, "com": 0.0, "com_calibrated": 0.0}
    return {"ratio": float(np.mean(ratios)), "com": float(np.mean(raw)),
            "com_calibrated": float(np.mean(calibrated))}


# ---------------------------------------------------------------------------
# bit planes
# ---------------------------------------------------------------------------
def _horizontal_autocorrelation(plane: np.ndarray) -> float:
    """Correlation between horizontally adjacent samples of one bit plane.

    Along the rows of one channel, never across a row end or a channel
    boundary. Taking it over the flattened array instead would measure the
    layout: a grayscale image loaded as three identical channels reads 2/3
    there, whatever its content.
    """
    a = plane[:, :-1].astype(np.float64).ravel()
    b = plane[:, 1:].astype(np.float64).ravel()
    if a.size < 2:
        return 0.0
    a = a - a.mean()
    b = b - b.mean()
    denom = float(np.sqrt(np.dot(a, a) * np.dot(b, b)))
    return float(np.dot(a, b) / denom) if denom else 0.0


def lsb_plane_stats(img: np.ndarray) -> dict:
    """Ones ratio and lag-1 autocorrelation of the lowest bit plane."""
    planes = [(plane & 1) for plane in _channels(img)]
    ones = float(np.mean([plane.mean() for plane in planes]))
    corr = float(np.mean([_horizontal_autocorrelation(plane)
                          for plane in planes]))
    return {"ones_ratio": ones, "autocorr_lag1": corr}


def bit_plane_profile(img: np.ndarray) -> dict:
    """Per-plane ones ratio and structure, lowest plane first.

    In a photograph the lowest planes are close to noise (ones ratio near 0.5,
    autocorrelation near 0) and the higher ones carry the picture. Two things
    show up here that the estimators above do not report. A lowest plane that
    is far *more* structured than the next one means the image is not a
    photograph at all - a screenshot or a rendering - and the estimators must
    not be read as if it were. A lowest plane that is markedly *less*
    structured than its neighbours is the signature of a plane that has been
    overwritten with compressed or encrypted data.
    """
    planes, correlations = [], []
    channels = _channels(img)
    for bit in range(8):
        bits = [(channel >> bit) & 1 for channel in channels]
        planes.append(float(np.mean([plane.mean() for plane in bits])))
        correlations.append(float(np.mean([_horizontal_autocorrelation(plane)
                                           for plane in bits])))
    return {"ones_ratio": planes, "autocorr_lag1": correlations,
            "noise_like_planes": int(sum(1 for c in correlations if abs(c) < 0.02))}


# ---------------------------------------------------------------------------
# putting it together
# ---------------------------------------------------------------------------
# name -> (what it detects, what a large value means)
DETECTORS = {
    "chi2_p_max": ("LSB replacement", "the lowest bit plane is levelled out"),
    "spa_rate": ("LSB replacement", "estimated fraction of changed samples"),
    "rs_rate": ("LSB replacement", "estimated fraction of changed samples"),
    "ws_rate": ("LSB replacement", "estimated fraction of changed samples"),
    "hcf_ratio": ("LSB matching", "below 1 means the histogram was smoothed"),
}

# Thresholds measured on 200 clean BOSSBase images that no model here was
# trained on; reproduce the table with experiments/calibrate_detectors.py.
#
#   detector      99th percentile on clean images   fires on clean
#   SPA           0.072                             0.7 %
#   RS            0.072                             0.7 %
#   WS            0.046                             0.0 %
#   chi2 p_max    -                                 22 %    (not scored)
#   chi2 seq.     -                                 1.3 %
#   HCF ratio     0.731 (1st pct; it falls on embedding)  29 % below 0.92
#
# RATE_STRONG sits above all three 99th percentiles, so one detector firing is
# roughly a 1-in-200 event on a clean photograph and two agreeing is rare
# enough to call it. RATE_WEAK is worth mentioning and not worth scoring.
RATE_STRONG = 0.08
RATE_WEAK = 0.03
CHI2_STRONG = 0.9
# 29 % of clean BOSSBase images have an HCF ratio below 0.92, so this detector
# cannot carry a threshold of its own: it is reported, and it is only
# mentioned when it is past the 1st percentile of the clean distribution.
HCF_EXTREME = 0.75


def quick_report(img: np.ndarray) -> dict:
    """Run every classical detector on one image."""
    chi = chi_square_attack(img, n_blocks=8)
    rs = rs_analysis(img)
    hcf = hcf_com(img)
    planes = bit_plane_profile(img)
    report = {
        "chi2_p_max": chi["p_embedded_max"],
        "chi2_p_mean": chi["p_embedded_mean"],
        "chi2_blocks": chi["blocks"],
        "spa_rate": sample_pair_analysis(img),
        "rs_rate": rs["rate"],
        "ws_rate": weighted_stego(img),
        "hcf_ratio": hcf["ratio"],
        "hcf_com": hcf["com"],
        "hcf_com_calibrated": hcf["com_calibrated"],
        "bit_plane_ones": planes["ones_ratio"],
        "bit_plane_autocorr": planes["autocorr_lag1"],
        **lsb_plane_stats(img),
    }
    report["verdict"] = verdict(report)
    return report


def verdict(report: dict) -> dict:
    """Turn the detector outputs into one statement, with its reasons.

    The score counts *independent* detectors that fired past a threshold each
    one clears on clean images only about once in two hundred. Two agreeing is
    called detection; one on its own is called suspicious, because the
    estimators here are not zero on clean photographs and a single small
    positive rate is not evidence of anything.

    Notes are returned alongside: things worth knowing that do not count as
    evidence, such as an HCF ratio outside the clean range or a lowest bit
    plane that says the image is not a photograph at all. Every conclusion is
    returned with the reasons behind it so it can be checked rather than
    believed - and none of this sees LSB matching at a low payload, which is
    what the trained detector in :mod:`adaptivestego.detector` is for.
    """
    reasons, notes, score = [], [], 0

    replacement = [("SPA", report.get("spa_rate", 0.0)),
                   ("RS", report.get("rs_rate", 0.0)),
                   ("WS", report.get("ws_rate", 0.0))]
    for name, rate in replacement:
        if rate > RATE_STRONG:
            score += 1
            reasons.append(f"{name} estimates {rate * 100:.1f} % of the "
                           f"samples were changed")
        elif rate > RATE_WEAK:
            notes.append(f"{name} estimates {rate * 100:.1f} % of the samples "
                         f"were changed, which clean images also reach")

    # The chi-square attack was designed against embedding that fills the
    # image from the start, and that is the only shape of it worth scoring:
    # a high probability in the first block and a low one in the last fires on
    # 1.3 % of clean BOSSBase images and on 73 % of sequentially embedded ones
    # at 0.25 bpp. A high probability *somewhere* fires on 22 % of clean
    # images, so that is worth reporting and not worth counting.
    blocks = report.get("chi2_blocks") or []
    if len(blocks) > 2 and blocks[0] > CHI2_STRONG and blocks[-1] < 0.1:
        score += 1
        reasons.append("the chi-square probability is high at the start of "
                       "the image and low at the end, which is what "
                       "sequential embedding looks like")
    elif report.get("chi2_p_max", 0.0) > CHI2_STRONG:
        notes.append(f"chi-square reaches p = {report['chi2_p_max']:.3f} in "
                     f"one block, which about a fifth of clean images also do")

    ratio = report.get("hcf_ratio", 1.0)
    if ratio < HCF_EXTREME:
        notes.append(f"the calibrated HCF centre of mass is {ratio:.3f} of the "
                     f"cover estimate, lower than 99 % of clean images; both "
                     f"+/-1 embedding and heavy LSB replacement do that, and "
                     f"so does an unusual image")

    ones = report.get("ones_ratio", 0.5)
    planes_ones = report.get("bit_plane_ones") or []
    if len(planes_ones) > 1 and abs(ones - 0.5) > 0.2 and abs(planes_ones[1] - 0.5) > 0.2:
        notes.append("the lowest bit planes are far from balanced: this is "
                     "computer-generated graphics rather than a photograph, "
                     "and the rate estimators are unreliable on it")

    if score >= 2:
        level = "detected"
    elif score == 1:
        level = "suspicious"
    else:
        level = "clean"
    return {"level": level, "score": score, "reasons": reasons, "notes": notes}
