"""Syndrome-trellis coding: minimum-distortion embedding.

The codecs in ``codecs/`` order the cover samples by a complexity map and write
the message into the first N of them. The receiver has to rebuild that order,
so the cost map must be recomputable from the stego image, and one sample that
moves into a different band after an attack shifts the whole stream.

Syndrome coding removes both constraints. The message is the syndrome of the
stego bit vector under a fixed parity check matrix::

    H y = m

The samples stay in their natural raster order, the cost map is used by the
encoder alone and never has to be reconstructed, and the decoder only needs the
dimensions and the key. Among all y that satisfy the constraint, the encoder
picks one of minimum total cost, so the costs can be anything - including
infinite, which marks a sample that must not change (a "wet" sample).

Two things this is **not**:

* an error correcting code. After an attack the syndrome changes, so bits are
  still lost. Robustness comes from ECC layered on top and has to be measured;
* an approximation. The Viterbi pass here explores the whole trellis without
  pruning, so for a given matrix the result is the exact minimum. The test
  suite checks that against brute force on short vectors.

Reference: T. Filler, J. Judas, J. Fridrich, "Minimizing additive distortion in
steganography using syndrome-trellis codes", IEEE TIFS 6(3), 2011.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .exceptions import CapacityError, StegoError
from .prng import keyed_uniform_u64

__all__ = ["MAX_HEIGHT", "StcResult", "parity_columns", "syndrome", "embed",
           "extract", "block_of_column"]

MAX_HEIGHT = 14          # 2**14 trellis states is already very slow
DEFAULT_HEIGHT = 8


@dataclass
class StcResult:
    """Outcome of one syndrome-coding operation."""

    bits: np.ndarray         # the stego bit vector y
    distortion: float        # total cost of the changes
    changes: int             # number of flipped bits
    efficiency: float        # message bits per flipped bit


def block_of_column(n: int, k: int) -> np.ndarray:
    """Which message bit each cover element belongs to.

    The n elements are split into k blocks as evenly as possible, so the
    payload does not have to be a whole fraction of the cover.
    """
    if k <= 0:
        return np.zeros(n, dtype=np.int64)
    edges = (np.arange(k + 1, dtype=np.int64) * n) // k
    return np.repeat(np.arange(k, dtype=np.int64), np.diff(edges))


def parity_columns(n: int, k: int, height: int, key=None) -> np.ndarray:
    """The parity check matrix, as one h-bit column per cover element.

    Bit r of column i means "this element takes part in constraint
    block_of_column[i] + r". The matrix is therefore banded: an element
    influences at most ``height`` consecutive message bits, which is what makes
    the trellis narrow enough to search exactly.

    The columns are derived from the key, so the matrix is part of the secret
    while still being reproducible by the receiver.
    """
    if not 1 <= height <= MAX_HEIGHT:
        raise ValueError(f"trellis height must be 1..{MAX_HEIGHT}")
    if k <= 0 or n <= 0:
        return np.zeros(0, dtype=np.int64)

    blocks = block_of_column(n, k)
    raw = keyed_uniform_u64(n, key, f"stc/matrix/{n}/{k}/{height}")
    columns = (raw & np.uint64((1 << height) - 1)).astype(np.int64)

    # Every column must reach its own constraint (bit 0) and the far end of the
    # band (top bit); otherwise the band degenerates and the code gets weaker.
    columns |= 1
    columns |= 1 << (height - 1)

    # Near the end of the message the band runs out of constraints to touch.
    available = np.minimum(height, k - blocks)
    columns &= (1 << available) - 1
    columns |= 1                       # bit 0 always survives, available >= 1
    return columns


def syndrome(bits: np.ndarray, k: int, height: int, key=None) -> np.ndarray:
    """Compute H y, the message carried by a bit vector."""
    bits = np.asarray(bits, dtype=np.uint8).ravel()
    n = bits.size
    if k <= 0:
        return np.zeros(0, dtype=np.uint8)
    columns = parity_columns(n, k, height, key)
    blocks = block_of_column(n, k)

    out = np.zeros(k, dtype=np.uint8)
    active = np.flatnonzero(bits)
    for offset in range(height):
        touched = (columns[active] >> offset) & 1
        rows = blocks[active] + offset
        keep = (touched == 1) & (rows < k)
        if not keep.any():
            continue
        np.bitwise_xor.at(out, rows[keep], 1)
    return out


def _check_inputs(cover_bits, costs, message):
    cover_bits = np.asarray(cover_bits, dtype=np.uint8).ravel()
    costs = np.asarray(costs, dtype=np.float64).ravel()
    message = np.asarray(message, dtype=np.uint8).ravel()
    if cover_bits.size != costs.size:
        raise ValueError(
            f"{cover_bits.size} cover bits but {costs.size} costs")
    if cover_bits.size and cover_bits.max() > 1:
        raise ValueError("cover bits must be 0 or 1")
    if message.size and message.max() > 1:
        raise ValueError("message bits must be 0 or 1")
    if message.size > cover_bits.size:
        raise CapacityError(
            f"{message.size} message bits do not fit into {cover_bits.size} "
            f"cover elements")
    if np.any(costs < 0):
        raise ValueError("costs must be non-negative")
    return cover_bits, costs, message


def embed(cover_bits: np.ndarray, costs: np.ndarray, message: np.ndarray, *,
          height: int = DEFAULT_HEIGHT, key=None) -> StcResult:
    """Find the cheapest bit vector whose syndrome is the message.

    ``costs`` may contain ``inf`` for samples that must not change. The search
    is an exact Viterbi pass over 2**height states, so the answer is the true
    minimum for this parity check matrix, not a heuristic.
    """
    cover_bits, costs, message = _check_inputs(cover_bits, costs, message)
    n, k = cover_bits.size, message.size
    if k == 0:
        return StcResult(cover_bits.copy(), 0.0, 0, float("inf"))

    columns = parity_columns(n, k, height, key)
    blocks = block_of_column(n, k)
    n_states = 1 << height
    state_bytes = (n_states + 7) // 8

    cost = np.full(n_states, np.inf, dtype=np.float64)
    cost[0] = 0.0
    choices = np.zeros((n, state_bytes), dtype=np.uint8)
    order = np.arange(n_states, dtype=np.int64)

    column = 0
    for block in range(k):
        while column < n and blocks[column] == block:
            mask = int(columns[column])
            same = 0.0 if cover_bits[column] == 0 else costs[column]
            flip = costs[column] if cover_bits[column] == 0 else 0.0

            # y = 0 leaves the state alone; y = 1 exclusive-ors the column in.
            keep_zero = cost + same
            keep_one = (cost + flip)[order ^ mask]
            take_one = keep_one < keep_zero
            cost = np.where(take_one, keep_one, keep_zero)
            choices[column] = np.packbits(take_one)
            column += 1

        # The accumulated parity of this block must equal the message bit.
        wanted = int(message[block])
        surviving = cost[(order & 1) == wanted]
        cost = np.full(n_states, np.inf, dtype=np.float64)
        cost[:surviving.size] = surviving           # shift the window along

    if not np.isfinite(cost[0]):
        raise StegoError(
            "syndrome coding found no solution: too many samples are marked "
            "unusable, or the payload is too close to the capacity")

    # Walk the trellis backwards, undoing the shift at each block boundary.
    stego = cover_bits.copy()
    state = 0
    for block in range(k - 1, -1, -1):
        state = (state << 1) | int(message[block])
        while column > 0 and blocks[column - 1] == block:
            column -= 1
            bit = (choices[column][state >> 3] >> (7 - (state & 7))) & 1
            stego[column] = bit
            if bit:
                state ^= int(columns[column])

    changed = np.flatnonzero(stego != cover_bits)
    distortion = float(costs[changed].sum())
    return StcResult(stego, distortion, int(changed.size),
                     float(k / changed.size) if changed.size else float("inf"))


def extract(stego_bits: np.ndarray, k: int, *, height: int = DEFAULT_HEIGHT,
            key=None) -> np.ndarray:
    """Recover the message: it is simply the syndrome of the stego vector."""
    return syndrome(stego_bits, k, height, key)
