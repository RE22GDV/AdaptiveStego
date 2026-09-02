"""Local complexity maps that drive adaptive embedding.

Two constraints shape this module.

1. The map must be identical for the sender (who sees the cover) and for the
   receiver (who only sees the stego image). It is therefore always computed
   from the image with its lowest bits cleared - exactly the bits embedding is
   allowed to touch. No synchronisation side channel is needed.

2. The map must be bit-identical on every machine and library version.
   A one-ULP difference would move a sample into a different quantisation band,
   shift the whole position order and destroy the message. Everything here is
   therefore integer arithmetic: integer convolutions, exact order statistics
   for normalisation, integer division, and an entropy table computed with the
   ``decimal`` module rather than the platform's libm.

Higher values mean "safer to modify". The range is 0..~1300.
"""

from __future__ import annotations

from decimal import Decimal, getcontext

import cv2
import numpy as np

__all__ = ["MAP_KINDS", "SCALE", "mask_low_bits", "complexity_map"]

MAP_KINDS = ("sobel", "laplacian", "variance", "entropy", "highfreq",
             "chroma", "combined", "uniform")

SCALE = 1024          # normalised maps span 0..SCALE-1
_LO_PCT, _HI_PCT = 1.0, 99.0
_WIN = 5              # window size of the local statistics


def mask_low_bits(img: np.ndarray, n_bits: int) -> np.ndarray:
    """Clear the n lowest bits of every sample."""
    if n_bits <= 0:
        return img
    return img & np.uint8(0xFF ^ ((1 << n_bits) - 1))


def _gray(img: np.ndarray) -> np.ndarray:
    """Integer luma (ITU-R BT.601 weights in fixed point)."""
    if img.ndim == 2:
        return img.astype(np.int32)
    if img.shape[2] == 1:
        return img[:, :, 0].astype(np.int32)
    f = img[:, :, :3].astype(np.int32)
    return (299 * f[:, :, 0] + 587 * f[:, :, 1] + 114 * f[:, :, 2]) // 1000


def _norm(x: np.ndarray) -> np.ndarray:
    """Normalise to 0..SCALE-1 using exact order statistics and integer math."""
    x = x.astype(np.int64)
    lo = int(np.percentile(x, _LO_PCT, method="lower"))
    hi = int(np.percentile(x, _HI_PCT, method="lower"))
    if hi <= lo:
        return np.zeros(x.shape, dtype=np.int32)
    y = (np.clip(x, lo, hi) - lo) * (SCALE - 1) // (hi - lo)
    return y.astype(np.int32)


def _sobel(gray: np.ndarray) -> np.ndarray:
    """|Gx| + |Gy|. uint8 input and CV_16S output keep the maths exact."""
    g = np.asarray(gray, dtype=np.uint8)
    gx = cv2.Sobel(g, cv2.CV_16S, 1, 0, ksize=3, borderType=cv2.BORDER_REFLECT_101)
    gy = cv2.Sobel(g, cv2.CV_16S, 0, 1, ksize=3, borderType=cv2.BORDER_REFLECT_101)
    return np.abs(gx.astype(np.int32)) + np.abs(gy.astype(np.int32))


def _laplacian(gray: np.ndarray) -> np.ndarray:
    lap = cv2.Laplacian(np.asarray(gray, dtype=np.uint8), cv2.CV_16S, ksize=3,
                        borderType=cv2.BORDER_REFLECT_101)
    return np.abs(lap.astype(np.int32))


def _sum_filter(x: np.ndarray, k: int = _WIN) -> np.ndarray:
    """Exact k-by-k window sum via an integral image (int64).

    Written with numpy rather than cv2 because the operation must stay purely
    integral while replicating BORDER_REFLECT_101 edge handling.
    """
    r = k // 2
    xp = np.pad(x.astype(np.int64), r, mode="reflect")
    ii = np.zeros((xp.shape[0] + 1, xp.shape[1] + 1), dtype=np.int64)
    np.cumsum(np.cumsum(xp, axis=0), axis=1, out=ii[1:, 1:])
    h, w = x.shape
    return (ii[k:k + h, k:k + w] - ii[0:h, k:k + w]
            - ii[k:k + h, 0:w] + ii[0:h, 0:w])


def _variance(gray: np.ndarray, k: int = _WIN) -> np.ndarray:
    """k^4 times the local variance: an integer that ranks the same way."""
    n = k * k
    s = _sum_filter(gray, k).astype(np.int64)
    sq = _sum_filter(gray.astype(np.int64) ** 2, k).astype(np.int64)
    return np.maximum(n * sq - s * s, 0)


_ENT_LUT_CACHE: dict[int, np.ndarray] = {}


def _entropy_lut(n: int) -> np.ndarray:
    """LUT[c] = round(-c/n * log2(c/n) * SCALE) as integers.

    Computed with ``decimal`` at 40 significant digits: pure Python arithmetic
    gives the same table on every platform, whereas ``math.log2`` delegates to
    the system libm and may differ in the last bit.
    """
    lut = _ENT_LUT_CACHE.get(n)
    if lut is None:
        getcontext().prec = 40
        ln2 = Decimal(2).ln()
        values = [0]
        for c in range(1, n + 1):
            p = Decimal(c) / Decimal(n)
            values.append(int((-p * (p.ln() / ln2) * SCALE).to_integral_value()))
        lut = np.array(values, dtype=np.int32)
        _ENT_LUT_CACHE[n] = lut
    return lut


def _entropy(gray: np.ndarray, k: int = _WIN, levels: int = 16) -> np.ndarray:
    """Local entropy over 16 luma bins inside a k-by-k window."""
    q = np.clip(gray // (256 // levels), 0, levels - 1)
    lut = _entropy_lut(k * k)
    ent = np.zeros(gray.shape, dtype=np.int32)
    for level in range(levels):
        counts = _sum_filter((q == level).astype(np.int32), k)
        ent += lut[np.clip(counts, 0, k * k)]
    return ent


def _highfreq(gray: np.ndarray, k: int = _WIN) -> np.ndarray:
    """Integer stand-in for a high-pass response: |k^2*pixel - window sum|."""
    return np.abs(k * k * gray.astype(np.int64) - _sum_filter(gray, k).astype(np.int64))


def _chroma(img: np.ndarray) -> np.ndarray:
    """Spread between colour channels; noise hides well where they disagree."""
    if img.ndim == 2 or img.shape[2] == 1:
        return np.zeros(img.shape[:2], dtype=np.int32)
    f = img[:, :, :3].astype(np.int32)
    return f.max(axis=2) - f.min(axis=2)


# Weights of the combined map, in parts per thousand (see the ablation study).
COMBINED_WEIGHTS = {"sobel": 350, "variance": 250, "entropy": 200,
                    "highfreq": 150, "chroma": 50}

# Relative "safety" of the R, G and B channels in parts per thousand: the human
# visual system is most sensitive to green and least sensitive to blue.
CHANNEL_WEIGHTS = (1000, 850, 1150)

# How much a channel's own local activity adds to its priority, per thousand.
CHANNEL_ACTIVITY = 250


def _spatial(kind: str, img: np.ndarray, gray: np.ndarray) -> np.ndarray:
    if kind == "sobel":
        return _norm(_sobel(gray))
    if kind == "laplacian":
        return _norm(_laplacian(gray))
    if kind == "variance":
        return _norm(_variance(gray))
    if kind == "entropy":
        return _norm(_entropy(gray))
    if kind == "highfreq":
        return _norm(_highfreq(gray))
    if kind == "chroma":
        return _norm(_chroma(img))
    if kind == "uniform":
        return np.full(gray.shape, SCALE - 1, dtype=np.int32)
    raise ValueError(f"unknown complexity map {kind!r}; available: {MAP_KINDS}")


def complexity_map(img: np.ndarray, kind: str = "combined", *,
                   mask_bits: int = 0, per_channel: bool = True) -> np.ndarray:
    """Embedding priority map of shape (H, W, C) and dtype int32."""
    base = mask_low_bits(img, mask_bits)
    if base.ndim == 2:
        base = base[:, :, None]

    if kind == "uniform":
        # The ablation control: no preference at all, not even between
        # channels, so that an adaptive codec degrades to keyed random order.
        return np.full(base.shape, SCALE - 1, dtype=np.int32)

    gray = _gray(base)

    if kind == "combined":
        spatial = np.zeros(gray.shape, dtype=np.int64)
        for name, weight in COMBINED_WEIGHTS.items():
            spatial += weight * _spatial(name, base, gray).astype(np.int64)
        spatial = (spatial // 1000).astype(np.int32)
    else:
        spatial = _spatial(kind, base, gray)

    n_ch = base.shape[2]
    out = np.repeat(spatial[:, :, None].astype(np.int64), n_ch, axis=2)
    if per_channel and n_ch == 3:
        out = out * np.array(CHANNEL_WEIGHTS, dtype=np.int64)[None, None, :] // 1000
        for c in range(3):
            activity = _norm(_sobel(base[:, :, c].astype(np.int32))).astype(np.int64)
            out[:, :, c] += CHANNEL_ACTIVITY * activity // 1000
    return out.astype(np.int32)
