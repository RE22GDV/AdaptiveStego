"""Sequential LSB - the baseline method (as in the original decoder.py).

It writes from the top-left corner onwards: the message is trivial to locate
and the statistics of the lowest bit plane break sharply at the start of the
image. Kept as the reference point every other method is compared against.
"""

from __future__ import annotations

import numpy as np

from .base import Codec, EmbedParams


class SequentialLSB(Codec):
    """Write into consecutive samples, ignoring image content."""

    name = "sequential"
    default_mode = "replace"

    def order(self, img: np.ndarray, params: EmbedParams,
              limit: int | None = None) -> np.ndarray:
        if limit is not None and params.channels is None:
            # No selection is needed at all: the order is the natural one.
            return np.arange(min(limit, img.size), dtype=np.int64)
        candidates = self._candidate_samples(img, params)
        return candidates if limit is None else candidates[:limit]
