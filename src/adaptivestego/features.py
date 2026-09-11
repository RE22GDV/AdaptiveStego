"""SPAM features: the classical feature set for spatial-domain steganalysis.

Every detector in :mod:`analysis` is a hand-built statistic with a threshold,
and all of them are blind to LSB matching, which changes the histogram only by
smoothing it. What does see +/-1 embedding is a *learned* detector, and the
standard input to one is the subtractive pixel adjacency matrix:

    take the differences between neighbouring pixels along eight directions,
    truncate them to [-T, T] so that the alphabet stays small, model each
    direction as a second-order Markov chain, and average over the four
    horizontal/vertical and the four diagonal directions.

Embedding adds an independent +/-1 to scattered pixels, which perturbs the
transition probabilities of that chain in a way no single histogram statistic
picks up but a linear classifier over all 686 of them does.

Reference:
  T. Pevny, P. Bas, J. Fridrich. Steganalysis by subtractive pixel adjacency
  matrix. IEEE TIFS 5(2), 2010.
"""

from __future__ import annotations

import numpy as np

__all__ = ["SPAM_T", "SPAM_DIM", "spam_features", "feature_names"]

SPAM_T = 3                      # differences are truncated to [-T, T]
_ALPHABET = 2 * SPAM_T + 1      # 7
SPAM_DIM = 2 * _ALPHABET ** 3   # 686

# (dy, dx) for the eight neighbours: the four axis-aligned ones first.
_AXIAL = ((0, 1), (0, -1), (1, 0), (-1, 0))
_DIAGONAL = ((1, 1), (-1, -1), (1, -1), (-1, 1))


def _shifted(plane: np.ndarray, dy: int, dx: int, step: int) -> np.ndarray:
    """The plane sampled at (i + step*dy, j + step*dx), cropped to the region
    where every step from 0 to 2 stays inside the image."""
    height, width = plane.shape
    y0, y1 = max(0, -2 * dy), height - max(0, 2 * dy)
    x0, x1 = max(0, -2 * dx), width - max(0, 2 * dx)
    return plane[y0 + step * dy:y1 + step * dy,
                 x0 + step * dx:x1 + step * dx]


def _direction_matrix(plane: np.ndarray, dy: int, dx: int) -> np.ndarray:
    """Second-order transition probabilities of the differences along (dy, dx).

    Returns an ``_ALPHABET**3`` vector holding P(w | u, v) for the three
    consecutive truncated differences u, v, w.
    """
    # One difference array, then three views of it one step apart. Taking the
    # differences first and the triples second is what makes this second order
    # in the differences rather than in the pixels.
    diff = plane.astype(np.int16)
    height, width = diff.shape
    y0, y1 = max(0, -dy), height - max(0, dy)
    x0, x1 = max(0, -dx), width - max(0, dx)
    d = (diff[y0:y1, x0:x1]
         - diff[y0 + dy:y1 + dy, x0 + dx:x1 + dx])
    np.clip(d, -SPAM_T, SPAM_T, out=d)
    d += SPAM_T                                  # now in 0.._ALPHABET-1

    if d.shape[0] <= 2 * abs(dy) or d.shape[1] <= 2 * abs(dx):
        return np.zeros(_ALPHABET ** 3)

    u = _shifted(d, dy, dx, 0).ravel()
    v = _shifted(d, dy, dx, 1).ravel()
    w = _shifted(d, dy, dx, 2).ravel()

    index = (u.astype(np.int32) * _ALPHABET + v) * _ALPHABET + w
    counts = np.bincount(index, minlength=_ALPHABET ** 3).astype(np.float64)
    counts = counts.reshape(_ALPHABET, _ALPHABET, _ALPHABET)

    # Conditional on (u, v), as the paper defines it. A pair that never occurs
    # contributes zeros rather than a division by zero.
    totals = counts.sum(axis=2, keepdims=True)
    np.divide(counts, totals, out=counts, where=totals > 0)
    return counts.ravel()


def spam_features(img: np.ndarray) -> np.ndarray:
    """686 SPAM features for one image, averaged over colour channels.

    The feature set is defined for grayscale. A colour image is reduced by
    averaging the per-channel features, which keeps the dimensionality and is
    what makes a model trained on grayscale covers applicable at all; it is
    not the same thing as a colour-aware feature set.
    """
    a = np.asarray(img)
    planes = [a] if a.ndim == 2 else [a[:, :, c] for c in range(a.shape[2])]

    per_plane = []
    for plane in planes:
        axial = np.mean([_direction_matrix(plane, dy, dx)
                         for dy, dx in _AXIAL], axis=0)
        diagonal = np.mean([_direction_matrix(plane, dy, dx)
                            for dy, dx in _DIAGONAL], axis=0)
        per_plane.append(np.concatenate([axial, diagonal]))
    return np.mean(per_plane, axis=0)


def feature_names() -> list[str]:
    """Human-readable names, in the order :func:`spam_features` returns."""
    names = []
    for group in ("axial", "diagonal"):
        for u in range(-SPAM_T, SPAM_T + 1):
            for v in range(-SPAM_T, SPAM_T + 1):
                for w in range(-SPAM_T, SPAM_T + 1):
                    names.append(f"{group}[{u},{v},{w}]")
    return names
