"""Random LSB - key-driven pseudo-random placement.

Positions are given by a permutation derived from the key. Without the key an
attacker does not know where to look, and the changes are spread evenly over
the whole image instead of piling up in the first rows.
"""

from __future__ import annotations

import numpy as np

from ..prng import keyed_uniform_u64, stable_argsort_prefix
from .base import Codec, EmbedParams


class RandomLSB(Codec):
    """Write into a keyed permutation of all candidate samples."""

    name = "random"
    default_mode = "replace"
    uses_key = True

    def order(self, img: np.ndarray, params: EmbedParams,
              limit: int | None = None) -> np.ndarray:
        candidates = self._candidate_samples(img, params)
        tag = ("random", params.key, params.channels)
        marks = self._memoized(img, tag, lambda: keyed_uniform_u64(
            candidates.size, params.key, f"positions/{img.shape}"))

        if limit is None or limit >= candidates.size:
            perm = np.argsort(marks, kind="stable")
        else:
            perm = stable_argsort_prefix(marks, limit)
        return candidates[perm]
