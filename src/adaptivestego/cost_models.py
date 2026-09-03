"""Embedding cost models for syndrome coding.

A cost model answers one question per sample: how expensive is it to change
this one by +1, and by -1? Syndrome coding then finds the cheapest bit vector
that carries the message, so the cost model *is* the steganographic method -
the coder is the same for all of them.

Three models live here:

``complexity``
    This project's own: the integer complexity map read as a cost.

``wow``
    Wavelet Obtained Weights (Holub, Fridrich, WIFS 2012). Directional wavelet
    residuals, aggregated with a reciprocal Holder norm so that a sample is
    only cheap when it is unpredictable in *every* direction.

``uniward``
    S-UNIWARD (Holub, Fridrich, Denemark, EURASIP JIS 2014), the spatial-domain
    universal wavelet relative distortion.

The last two are ports of the reference implementations published by the
Binghamton DDE Lab. They are validated numerically against that MATLAB code:
``matlab/dump_reference_costs.m`` writes reference cost maps, and
``tests/test_cost_models.py`` checks the port against the stored output, so the
comparison keeps holding without MATLAB installed.

Unlike the ordering codecs, nothing here has to be reproducible by the
receiver: a syndrome decoder never rebuilds the cost map. That is why these
models may use floating point and the untouched cover at full precision.
"""

from __future__ import annotations

import cv2
import numpy as np

__all__ = ["COST_MODELS", "WET", "WET_COST", "wet_cost", "cost_model_names",
           "costs_for", "complexity_costs", "wow_costs", "uniward_costs",
           "wavelet_filters", "binary_costs", "preferred_direction"]

# A "wet" sample is one that cannot be changed in a given direction. The
# reference implementations use a large finite number rather than infinity,
# and they do not agree on which: WOW.m uses 10^10 and S_UNIWARD.m uses 10^8.
# Each model keeps its own value, because a cost map is only comparable to the
# reference value by value if the wet entries match too. The syndrome coder
# treats anything this large as unusable either way.
WET = 1e10

WET_COST = {"complexity": 1e10, "wow": 1e10, "uniward": 1e8}


def wet_cost(model: str) -> float:
    """The value this model assigns to a direction that cannot be taken."""
    return WET_COST.get(model, WET)

# Daubechies 8 high-pass decomposition filter, exactly as in the DDE Lab code.
_HPDF = np.array([
    -0.0544158422, 0.3128715909, -0.6756307363, 0.5853546837, 0.0158291053,
    -0.2840155430, -0.0004724846, 0.1287474266, 0.0173693010, -0.0440882539,
    -0.0139810279, 0.0087460940, 0.0048703530, -0.0003917404, -0.0006754494,
    -0.0001174768], dtype=np.float64)


def wavelet_filters() -> list[np.ndarray]:
    """The three directional 2D wavelet filters: LH, HL and HH."""
    signs = (-1.0) ** np.arange(_HPDF.size)
    lpdf = signs * _HPDF[::-1]
    return [np.outer(lpdf, _HPDF),      # horizontal detail
            np.outer(_HPDF, lpdf),      # vertical detail
            np.outer(_HPDF, _HPDF)]     # diagonal detail


def _conv2_same(image: np.ndarray, kernel: np.ndarray) -> np.ndarray:
    """True convolution with MATLAB's ``conv2(..., 'same')`` alignment.

    OpenCV correlates, so the kernel is flipped. For an even-sized kernel the
    default anchor then lands where MATLAB puts it, which matters here because
    the filters are 16 by 16 and a one pixel shift would corrupt the whole
    comparison against the reference implementation.
    """
    return cv2.filter2D(image, cv2.CV_64F, np.flip(kernel),
                        borderType=cv2.BORDER_REFLECT)


def _suitability(cover: np.ndarray, transform) -> np.ndarray:
    """Shared skeleton of WOW and S-UNIWARD.

    Both pad symmetrically, filter with each directional wavelet, apply their
    own transform to the residual, correlate the result with the absolute
    filter, undo the even-size shift and crop the padding away.
    """
    filters = wavelet_filters()
    pad = max(max(f.shape) for f in filters)
    padded = np.pad(cover.astype(np.float64), pad, mode="symmetric")

    parts = []
    for kernel in filters:
        residual = _conv2_same(padded, kernel)
        xi = _conv2_same(transform(residual), np.rot90(np.abs(kernel), 2))

        # The reference code shifts by one for each even filter dimension.
        if kernel.shape[0] % 2 == 0:
            xi = np.roll(xi, 1, axis=0)
        if kernel.shape[1] % 2 == 0:
            xi = np.roll(xi, 1, axis=1)

        parts.append(xi[pad:pad + cover.shape[0], pad:pad + cover.shape[1]])
    return parts


def _finish(rho: np.ndarray, cover: np.ndarray,
            wet: float) -> tuple[np.ndarray, np.ndarray]:
    """Clamp, then forbid the direction that would leave the 0..255 range."""
    rho = np.where(np.isnan(rho), wet, rho)
    rho = np.minimum(rho, wet)
    up, down = rho.copy(), rho.copy()
    up[cover == 255] = wet
    down[cover == 0] = wet
    return up, down


def _per_channel(cover: np.ndarray, single):
    """Apply a grayscale cost model to each channel of a colour image.

    WOW and S-UNIWARD are defined for grayscale. Treating the channels
    independently is the simplest defensible extension and is what the colour
    experiments here use; it ignores inter-channel correlation, which is worth
    remembering when reading colour results.
    """
    if cover.ndim == 2:
        return single(cover)
    ups, downs = [], []
    for channel in range(cover.shape[2]):
        up, down = single(cover[:, :, channel])
        ups.append(up)
        downs.append(down)
    return np.stack(ups, axis=2), np.stack(downs, axis=2)


# ---------------------------------------------------------------------------
# the models
# ---------------------------------------------------------------------------
def wow_costs(cover: np.ndarray, *, p: float = -1.0,
              **_ignored) -> tuple[np.ndarray, np.ndarray]:
    """Wavelet Obtained Weights.

    The suitability of a sample is the correlation of the absolute residual
    with the absolute filter, in each of three directions. The reciprocal
    Holder norm with p = -1 then aggregates them so that a sample is cheap only
    if it is textured in every direction: one smooth direction, such as a clean
    edge, is enough to make it expensive.
    """
    def single(channel: np.ndarray):
        parts = _suitability(channel, np.abs)
        with np.errstate(divide="ignore", invalid="ignore"):
            summed = sum(np.power(part, p) for part in parts)
            rho = np.power(summed, -1.0 / p)
        return _finish(rho, channel, WET_COST["wow"])

    return _per_channel(cover, single)


def uniward_costs(cover: np.ndarray, *, sigma: float = 1.0,
                  **_ignored) -> tuple[np.ndarray, np.ndarray]:
    """S-UNIWARD in the spatial domain.

    The residual is turned into 1 / (|residual| + sigma) before correlation, so
    the cost is the accumulated relative change a modification would cause in
    the wavelet domain. The three directions are simply summed, which is what
    makes it "universal" rather than directional.
    """
    def single(channel: np.ndarray):
        parts = _suitability(channel, lambda r: 1.0 / (np.abs(r) + sigma))
        return _finish(sum(parts), channel, WET_COST["uniward"])

    return _per_channel(cover, single)


def complexity_costs(cover: np.ndarray, *, map_kind: str = "combined",
                     floor: float = 0.02, gamma: float = 1.0,
                     **_ignored) -> tuple[np.ndarray, np.ndarray]:
    """This project's own model: the integer complexity map read as a cost."""
    from .costs import embedding_costs

    return embedding_costs(cover, map_kind=map_kind, floor=floor, gamma=gamma)


COST_MODELS = {
    "complexity": complexity_costs,
    "wow": wow_costs,
    "uniward": uniward_costs,
}


def cost_model_names() -> list[str]:
    """Names of the available cost models."""
    return list(COST_MODELS)


def costs_for(cover: np.ndarray, model: str = "complexity",
              **kwargs) -> tuple[np.ndarray, np.ndarray]:
    """Cost of a +1 and of a -1 change for every sample, by model name."""
    try:
        function = COST_MODELS[model]
    except KeyError:
        raise ValueError(
            f"unknown cost model {model!r}; available: "
            f"{', '.join(COST_MODELS)}") from None
    return function(cover, **kwargs)


def binary_costs(up: np.ndarray, down: np.ndarray) -> np.ndarray:
    """Cost of flipping the lowest bit, whichever direction is cheaper."""
    from .costs import binary_costs as _binary

    return _binary(up, down)


def preferred_direction(up: np.ndarray, down: np.ndarray, key=None,
                        tag: str = "direction") -> np.ndarray:
    """+1 or -1 per sample: the cheaper direction, ties broken by the key."""
    from .costs import preferred_direction as _direction

    return _direction(up, down, key, tag)
