"""Codec base class: one embedding loop, many position orderings."""

from __future__ import annotations

import math
from dataclasses import dataclass
from dataclasses import replace as _replace

import numpy as np

from .. import core

__all__ = ["EmbedParams", "Codec"]


@dataclass(frozen=True)
class EmbedParams:
    """Parameters shared by every codec.

    These must match on both sides: they are not stored inside the image
    (and the key is never stored anywhere).
    """

    bits_per_sample: int = 1
    key: str | None = None
    map_kind: str = "combined"
    band_bits: int = 6          # quantisation step of the complexity map
    mode: str | None = None     # None means the codec default
    channels: tuple[int, ...] | None = None  # None means every channel
    map_mask_bits: int | None = None  # None means the required minimum
    stc_height: int = 8         # trellis height for syndrome coding
    cost_gamma: float = 1.0     # sharpens the cost preference for texture

    def with_(self, **kw) -> EmbedParams:
        """Return a copy with some fields replaced."""
        return _replace(self, **kw)


class Codec:
    """A codec is a rule that orders the samples of the cover image.

    Orderings are produced lazily: ``limit`` asks for only the first N
    positions, which every codec computes without sorting the whole image.
    Hiding a short message in a large photograph is therefore linear in the
    number of samples rather than N log N.
    """

    name = "base"
    default_mode = "replace"
    uses_key = False
    adaptive = False
    syndrome_coded = False      # True when the payload length must be known

    # -- to be overridden -------------------------------------------------
    def order(self, img: np.ndarray, params: EmbedParams,
              limit: int | None = None) -> np.ndarray:
        """Return sample indices in writing order, at most ``limit`` of them."""
        raise NotImplementedError

    # -- shared behaviour -------------------------------------------------
    def mode(self, params: EmbedParams) -> str:
        return params.mode or self.default_mode

    def mask_bits(self, params: EmbedParams) -> int:
        """How many low bits are ignored when building the complexity map.

        The minimum is the set of bits embedding may change, otherwise the
        sender's and the receiver's maps would differ. It can be raised through
        ``map_mask_bits``, which is an ablation knob ("how coarse may the map
        be?"). It does not buy robustness: the position order comes from a
        global sort, so moving a single sample into another band shifts the
        whole remaining stream (see docs/limitations.md).
        """
        minimum = params.bits_per_sample + (1 if self.mode(params) == "match" else 0)
        if params.map_mask_bits is None:
            return minimum
        if params.map_mask_bits < minimum:
            raise ValueError(
                f"map_mask_bits={params.map_mask_bits} is below the minimum "
                f"{minimum} for this mode: the map would not match on extraction")
        return min(int(params.map_mask_bits), 7)

    def _memoized(self, img: np.ndarray, tag, build):
        """Cache one intermediate result for one image on this codec instance.

        Extraction reads the header from a short prefix and only then asks for
        enough positions to cover the payload, so the ordering is built twice.
        Without this cache the complexity map would also be computed twice, and
        it dominates the cost. The image itself is kept in the cache entry so
        that its identity cannot be reused by another array.
        """
        cached = getattr(self, "_memo", None)
        if cached is not None and cached[0] is img and cached[1] == tag:
            return cached[2]
        value = build()
        self._memo = (img, tag, value)
        return value

    def candidate_count(self, img: np.ndarray, params: EmbedParams) -> int:
        """How many samples this codec may use, without ordering them."""
        if params.channels is None or img.ndim == 2:
            return int(img.size)
        n_channels = img.shape[2]
        used = len({c for c in params.channels if 0 <= c < n_channels})
        return int(img.size // n_channels * used)

    def _candidate_samples(self, img: np.ndarray, params: EmbedParams) -> np.ndarray:
        """Indices of the samples this codec is allowed to use."""
        n = img.size
        if params.channels is None or img.ndim == 2:
            return np.arange(n, dtype=np.int64)
        c = img.shape[2]
        keep = np.zeros(c, dtype=bool)
        for ch in params.channels:
            keep[ch] = True
        mask = np.tile(keep, n // c)
        return np.nonzero(mask)[0].astype(np.int64)

    def positions(self, img: np.ndarray, params: EmbedParams,
                  limit: int | None = None) -> np.ndarray:
        """Ordered sample positions used for embedding and extraction."""
        pos = self.order(img, params, limit)
        if pos.dtype != np.int64:
            pos = pos.astype(np.int64)
        return pos

    def capacity_bits(self, img: np.ndarray, params: EmbedParams) -> int:
        return core.capacity_bits(self.candidate_count(img, params),
                                  params.bits_per_sample)

    def samples_needed(self, n_bits: int, params: EmbedParams) -> int:
        """How many samples are required to carry n_bits bits."""
        return int(math.ceil(n_bits / params.bits_per_sample))

    def embed(self, img: np.ndarray, bits: np.ndarray,
              params: EmbedParams) -> np.ndarray:
        mode = self.mode(params)
        preserve = self.mask_bits(params) if (self.adaptive and mode == "match") else None
        needed = self.samples_needed(np.asarray(bits).size, params)
        return core.embed_bits(
            img, bits, self.positions(img, params, limit=needed),
            bits_per_sample=params.bits_per_sample, mode=mode, key=params.key,
            preserve_above_bit=preserve,
        )

    def extract(self, img: np.ndarray, n_bits: int,
                params: EmbedParams) -> np.ndarray:
        needed = self.samples_needed(n_bits, params)
        return core.extract_bits(img, self.positions(img, params, limit=needed),
                                 n_bits, bits_per_sample=params.bits_per_sample)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Codec {self.name}>"
