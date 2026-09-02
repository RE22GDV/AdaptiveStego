"""Content-adaptive embedding driven by a local complexity map.

The testable hypothesis behind this project: writing preferentially into
samples with high local complexity - edges, textures, areas of high variance
and entropy - makes the changes both less visible and harder to detect at an
equal payload than sequential or uniformly random placement.

The order of positions is a sort by descending quantised complexity, with a
keyed pseudo-random permutation inside each quantisation band. A short message
therefore lands only in the noisiest regions of the image.

The map is computed from the image with its lowest bits cleared, so the
receiver reproduces the same order without any side information.
"""

from __future__ import annotations

import numpy as np

from ..maps import SCALE, complexity_map
from ..prng import keyed_uniform_u64, stable_argsort_prefix
from .base import Codec, EmbedParams


class AdaptiveLSB(Codec):
    """Order samples by descending local complexity, ties broken by the key."""

    name = "adaptive"
    default_mode = "replace"
    uses_key = True
    adaptive = True
    forced_map: str | None = None

    def map_kind(self, params: EmbedParams) -> str:
        return self.forced_map or params.map_kind

    def _bands_and_ties(self, img: np.ndarray, params: EmbedParams,
                        candidates: np.ndarray):
        """Quantised complexity of each candidate plus its keyed tie-breaker."""
        tag = ("adaptive", self.map_kind(params), self.mask_bits(params),
               params.band_bits, params.key, params.channels)
        return self._memoized(img, tag,
                              lambda: self._build_bands(img, params, candidates))

    def _build_bands(self, img: np.ndarray, params: EmbedParams,
                     candidates: np.ndarray):
        cmap = complexity_map(img, self.map_kind(params),
                              mask_bits=self.mask_bits(params))
        scores = cmap.reshape(-1)[candidates]

        band_bits = int(np.clip(params.band_bits, 1, 10))
        shift = int(np.log2(SCALE)) - band_bits          # SCALE is 2^10
        bands = (scores >> shift).astype(np.int64)

        ties = keyed_uniform_u64(candidates.size, params.key,
                                 f"adaptive/{self.map_kind(params)}/{img.shape}")
        return bands, ties

    def order(self, img: np.ndarray, params: EmbedParams,
              limit: int | None = None) -> np.ndarray:
        candidates = self._candidate_samples(img, params)
        bands, ties = self._bands_and_ties(img, params, candidates)

        if limit is None or limit >= candidates.size:
            # Primary key: decreasing complexity. Secondary key: keyed noise.
            return candidates[np.lexsort((ties, -bands))]
        return candidates[self._prefix(bands, ties, limit)]

    @staticmethod
    def _prefix(bands: np.ndarray, ties: np.ndarray, limit: int) -> np.ndarray:
        """First ``limit`` entries of ``lexsort((ties, -bands))``, computed in O(n).

        The bands form a small set of integers, so a histogram finds the band at
        which the requested number of samples is reached. Everything above that
        band is taken whole and only the boundary band has to be ranked by its
        tie-breaker.
        """
        counts = np.bincount(bands)
        # remaining[b] is the number of samples whose band is at least b.
        remaining = np.cumsum(counts[::-1])[::-1]
        cutoff = int(np.flatnonzero(remaining >= limit).max())

        above = np.flatnonzero(bands > cutoff)           # always fewer than limit
        head = above[np.lexsort((ties[above], -bands[above]))]

        still_needed = limit - head.size
        if still_needed <= 0:
            return head[:limit].astype(np.int64)

        boundary = np.flatnonzero(bands == cutoff)
        picked = boundary[stable_argsort_prefix(ties[boundary], still_needed)]
        return np.concatenate([head, picked]).astype(np.int64)


class EdgeAdaptiveLSB(AdaptiveLSB):
    """Classic edge-adaptive LSB: priority from the Sobel gradient alone."""

    name = "edge"
    forced_map = "sobel"


class AdaptiveMatching(AdaptiveLSB):
    """The proposed combination: adaptive ordering plus +/-1 embedding."""

    name = "adaptive-matching"
    default_mode = "match"
