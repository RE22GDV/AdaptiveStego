"""Minimum-distortion embedding driven by syndrome-trellis coding.

Every other codec here answers "which samples first?" and the receiver has to
reproduce that answer. This one does not order anything: the samples stay in
raster order, the cost map decides how expensive each change is, and syndrome
coding finds the cheapest bit vector whose syndrome is the message.

Consequences worth knowing:

* the decoder needs the dimensions, the key and the trellis height, and nothing
  about the cost map, so the map can use the untouched cover at full precision;
* one damaged sample no longer shifts the rest of the stream, because there is
  no stream order to shift - though the syndrome still changes, so error
  correction on top is what actually buys robustness;
* the payload length has to be known before decoding, so this codec works in
  research mode and refuses the progressive container format.
"""

from __future__ import annotations

import numpy as np

from .. import stc
from ..costs import binary_costs, embedding_costs, preferred_direction
from .base import Codec, EmbedParams


class StcLSB(Codec):
    """Syndrome-trellis coding over the lowest bits, with +/-1 changes."""

    name = "stc"
    default_mode = "match"
    uses_key = True
    adaptive = True
    syndrome_coded = True          # the payload length cannot be discovered

    def order(self, img: np.ndarray, params: EmbedParams,
              limit: int | None = None) -> np.ndarray:
        """Raster order. Nothing is ranked; the costs do the work."""
        candidates = self._candidate_samples(img, params)
        return candidates if limit is None else candidates[:limit]

    def _check(self, params: EmbedParams) -> None:
        if params.bits_per_sample != 1:
            raise ValueError(
                "syndrome coding writes one bit per sample; "
                "bits_per_sample must be 1")

    def _costs(self, img: np.ndarray, params: EmbedParams,
               candidates: np.ndarray):
        up, down = embedding_costs(img, map_kind=params.map_kind,
                                   gamma=params.cost_gamma)
        flat_up, flat_down = up.reshape(-1)[candidates], down.reshape(-1)[candidates]
        return flat_up, flat_down

    def embed(self, img: np.ndarray, bits: np.ndarray,
              params: EmbedParams) -> np.ndarray:
        self._check(params)
        candidates = self.positions(img, params)
        flat = img.reshape(-1)
        cover_bits = (flat[candidates] & 1).astype(np.uint8)

        up, down = self._costs(img, params, candidates)
        result = stc.embed(cover_bits, binary_costs(up, down), bits,
                           height=params.stc_height, key=params.key)

        changed = np.flatnonzero(result.bits != cover_bits)
        if changed.size == 0:
            return img.copy()

        direction = preferred_direction(up, down, params.key,
                                        f"stc/direction/{img.shape}")[changed]
        out = img.copy()
        target = out.reshape(-1)
        values = target[candidates[changed]].astype(np.int16) + direction
        target[candidates[changed]] = np.clip(values, 0, 255).astype(np.uint8)
        return out

    def extract(self, img: np.ndarray, n_bits: int,
                params: EmbedParams) -> np.ndarray:
        self._check(params)
        candidates = self.positions(img, params)
        cover_bits = (img.reshape(-1)[candidates] & 1).astype(np.uint8)
        return stc.extract(cover_bits, int(n_bits), height=params.stc_height,
                           key=params.key)
