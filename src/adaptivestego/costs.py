"""Turning the complexity map into per-sample embedding costs.

The ordering codecs ask "which samples should be used first?". Syndrome coding
asks a different question: "how expensive is it to change each sample?". The
answer is the same map read the other way round - high local complexity means a
change hides well, so the cost is low.

Two directions are costed separately, because a sample at 255 cannot go up and
a sample at 0 cannot go down. The forbidden direction is given an infinite
("wet") cost, which syndrome coding handles natively.

One thing becomes easier here than it is for the ordering codecs. They must
compute the map from the image with its low bits cleared, because the receiver
has to reproduce the same map from the stego image. A syndrome decoder never
recomputes the map, so the costs may be built from the untouched cover at full
precision.
"""

from __future__ import annotations

import numpy as np

from .maps import SCALE, complexity_map

__all__ = ["WET", "embedding_costs", "binary_costs", "preferred_direction"]

WET = np.inf

# Cost floor: without it a maximally textured sample would cost zero and the
# encoder would have no reason to spread changes at all.
DEFAULT_FLOOR = 0.02


def embedding_costs(img: np.ndarray, *, map_kind: str = "combined",
                    floor: float = DEFAULT_FLOOR,
                    gamma: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    """Cost of changing each sample by +1 and by -1.

    Returns two arrays shaped like the image. ``gamma`` sharpens (>1) or
    flattens (<1) the preference for textured areas.
    """
    if floor <= 0:
        raise ValueError("the cost floor must be positive")

    scores = complexity_map(img, map_kind, mask_bits=0).astype(np.float64) / SCALE
    cost = 1.0 / np.power(scores + floor, gamma)

    up, down = cost.copy(), cost.copy()
    up[img == 255] = WET          # cannot go above the range
    down[img == 0] = WET          # cannot go below it
    return up, down


def binary_costs(up: np.ndarray, down: np.ndarray) -> np.ndarray:
    """Cost of flipping the lowest bit, whichever direction is cheaper.

    Changing a sample by +1 or by -1 flips its lowest bit either way, so a
    binary syndrome code only needs the cheaper of the two. A sample is only
    unusable when both directions are, which cannot happen from the 0 and 255
    limits alone but can be requested deliberately.
    """
    return np.minimum(up, down)


def preferred_direction(up: np.ndarray, down: np.ndarray, key=None,
                        tag: str = "direction") -> np.ndarray:
    """+1 or -1 per sample: the cheaper direction, ties broken by the key.

    Breaking ties with a coin rather than with a constant matters: always
    choosing +1 would bias the histogram of the stego image upwards, and that
    is exactly the kind of regularity a detector looks for.
    """
    from .prng import keyed_uniform_u64

    coin = (keyed_uniform_u64(up.size, key, tag) & 1).reshape(up.shape)
    direction = np.where(coin == 1, 1, -1).astype(np.int16)
    direction[up < down] = 1
    direction[down < up] = -1
    return direction
