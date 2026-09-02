"""Embedding engine: write and read bits at a given list of sample positions.

A position is the index of one sample (one channel of one pixel) in the
flattened image. Every sample carries ``bits_per_sample`` bits, most
significant bit first.

Two write modes are supported:

``replace``
    Classic LSB replacement; only the lowest bits ever change.
``match``
    LSB matching (+/-1). It does not create the value pairs (2k, 2k+1) that
    histogram attacks such as chi-square, RS and SPA rely on.
"""

from __future__ import annotations

import numpy as np

from .exceptions import CapacityError
from .prng import keyed_uniform_u64

__all__ = ["MODES", "capacity_bits", "embed_bits", "extract_bits"]

MODES = ("replace", "match")


def capacity_bits(n_positions: int, bits_per_sample: int) -> int:
    """How many message bits fit into the given number of samples."""
    return int(n_positions) * int(bits_per_sample)


def _check(bits_per_sample: int, mode: str) -> None:
    if bits_per_sample not in (1, 2, 3, 4):
        raise ValueError("bits_per_sample must be 1..4")
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    if mode == "match" and bits_per_sample != 1:
        raise ValueError("LSB matching is only defined for bits_per_sample=1")


def _values_from_bits(bits: np.ndarray, bits_per_sample: int) -> np.ndarray:
    """Group a bit stream (MSB first) into integers of bits_per_sample bits."""
    n = bits.size // bits_per_sample
    view = bits[:n * bits_per_sample].reshape(n, bits_per_sample).astype(np.uint8)
    weights = (1 << np.arange(bits_per_sample - 1, -1, -1)).astype(np.uint8)
    return (view * weights).sum(axis=1).astype(np.uint8)


def _bits_from_values(values: np.ndarray, bits_per_sample: int) -> np.ndarray:
    """Expand integers back into a bit stream (MSB first)."""
    shifts = np.arange(bits_per_sample - 1, -1, -1, dtype=np.uint8)
    return ((values[:, None] >> shifts[None, :]) & 1).astype(np.uint8).ravel()


def embed_bits(img: np.ndarray, bits: np.ndarray, positions: np.ndarray, *,
               bits_per_sample: int = 1, mode: str = "replace",
               key=None, preserve_above_bit: int | None = None) -> np.ndarray:
    """Return a copy of the image with the given bits written into it.

    ``preserve_above_bit`` applies to the ``match`` mode: the +/-1 direction is
    chosen so that bits above the given position never change. Adaptive codecs
    need this because they rebuild their complexity map from the high bits.
    """
    _check(bits_per_sample, mode)
    bits = np.asarray(bits, dtype=np.uint8).ravel()

    need = int(np.ceil(bits.size / bits_per_sample))
    if need > positions.size:
        raise CapacityError(
            f"{need} samples are required but only {positions.size} are available "
            f"({bits.size} bits against a capacity of "
            f"{capacity_bits(positions.size, bits_per_sample)})"
        )

    pad = (-bits.size) % bits_per_sample
    if pad:
        bits = np.concatenate([bits, np.zeros(pad, dtype=np.uint8)])
    values = _values_from_bits(bits, bits_per_sample)

    out = img.copy()
    flat = out.reshape(-1)
    idx = positions[:values.size]
    cur = flat[idx].astype(np.int16)

    if mode == "replace":
        mask = np.uint8(0xFF ^ ((1 << bits_per_sample) - 1))
        flat[idx] = (flat[idx] & mask) | values
        return out

    # LSB matching: move the sample by +/-1 wherever the lowest bit disagrees.
    diff = (cur & 1) != values
    if int(diff.sum()):
        coin = (keyed_uniform_u64(values.size, key, "matching") & 1).astype(np.int16)
        step = np.where(coin == 1, 1, -1).astype(np.int16)
        step[cur == 0] = 1
        step[cur == 255] = -1
        if preserve_above_bit is not None and preserve_above_bit > 0:
            block = 1 << preserve_above_bit
            low = cur % block
            step[low == block - 1] = -1   # +1 would carry out of the block
            step[low == 0] = 1            # -1 would borrow out of the block
        new = cur.copy()
        new[diff] = cur[diff] + step[diff]
        flat[idx] = np.clip(new, 0, 255).astype(np.uint8)
    return out


def extract_bits(img: np.ndarray, positions: np.ndarray, n_bits: int, *,
                 bits_per_sample: int = 1) -> np.ndarray:
    """Read n_bits bits from the samples listed in ``positions``."""
    if bits_per_sample not in (1, 2, 3, 4):
        raise ValueError("bits_per_sample must be 1..4")
    need = int(np.ceil(n_bits / bits_per_sample))
    if need > positions.size:
        raise CapacityError(
            f"{n_bits} bits requested but only "
            f"{capacity_bits(positions.size, bits_per_sample)} are available")
    flat = img.reshape(-1)
    mask = np.uint8((1 << bits_per_sample) - 1)
    values = flat[positions[:need]] & mask
    return _bits_from_values(values, bits_per_sample)[:n_bits]
