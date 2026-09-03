"""Tests for the embedding cost models.

The structural tests always run. The comparison against the reference MATLAB
implementation runs whenever the reference maps are present in
tests/data/cost_vectors; see matlab/README.md for how they are produced.
"""

import os

import numpy as np
from conftest import raises, skip

import adaptivestego as sl
from adaptivestego import cost_models
from adaptivestego.cost_models import cost_model_names, costs_for, wet_cost
from adaptivestego.image_io import read_image
from adaptivestego.prng import deterministic_bits
from adaptivestego.testing import synthetic_cover

VECTOR_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "data", "cost_vectors")
REFERENCE_MODELS = ("wow", "uniward")

# Costs an embedder would ever act on; typical values are 0.01 to 100.
USABLE_COST = 1e3
TOLERANCE = 1e-9
# Above USABLE_COST the reciprocal Holder norm of WOW amplifies floating point
# cancellation: in a perfectly flat region the residual is zero up to rounding,
# so a cost of order 1e9 keeps only a few significant digits and any two
# implementations disagree there. Those samples are never chosen anyway.
EXTREME_TOLERANCE = 1e-4


def test_wet_costs_match_the_reference_constants():
    """WOW.m uses 10^10 and S_UNIWARD.m uses 10^8; the ports must agree.

    A cost map is only comparable to the reference value by value if the
    entries for impossible directions match too.
    """
    assert wet_cost("wow") == 1e10
    assert wet_cost("uniward") == 1e8


# ---------------------------------------------------------------------------
# agreement with the reference implementation
# ---------------------------------------------------------------------------
def _reference_pairs():
    """(image path, model, direction, reference path) for what is available."""
    if not os.path.isdir(VECTOR_DIR):
        return []
    pairs = []
    for name in sorted(os.listdir(VECTOR_DIR)):
        if not name.endswith(".pgm"):
            continue
        stem = os.path.splitext(name)[0]
        for model in REFERENCE_MODELS:
            for direction in ("up", "down"):
                reference = os.path.join(VECTOR_DIR,
                                         f"{stem}.{model}.{direction}.f64")
                if os.path.isfile(reference):
                    pairs.append((os.path.join(VECTOR_DIR, name), model,
                                  direction, reference))
    return pairs


def test_ports_match_the_reference_implementation():
    """The ported costs must equal the DDE Lab MATLAB output.

    Every later comparison against WOW or S-UNIWARD rests on this, so the
    tolerance is numerical rather than approximate.
    """
    pairs = _reference_pairs()
    if not pairs:
        skip("no reference cost maps; see matlab/README.md")

    for image_path, model, direction, reference_path in pairs:
        cover = read_image(image_path, grayscale=True)
        up, down = costs_for(cover, model)
        ported = up if direction == "up" else down

        reference = np.fromfile(reference_path,
                                dtype=np.float64).reshape(cover.shape)

        wet = wet_cost(model)
        wet_ported, wet_reference = ported >= wet, reference >= wet
        assert np.array_equal(wet_ported, wet_reference), (
            f"{model}/{direction} disagrees about which samples are unusable")

        live = ~wet_reference
        relative = (np.abs(ported - reference)
                    / np.maximum(np.abs(reference), 1e-12))
        name = f"{os.path.basename(image_path)}/{model}/{direction}"

        usable = live & (reference <= USABLE_COST)
        assert usable.any(), f"{name}: no usable costs to compare"
        assert relative[usable].max() <= TOLERANCE, (
            f"{name}: usable costs differ by {relative[usable].max():.3e}")

        extreme = live & (reference > USABLE_COST)
        if extreme.any():
            assert relative[extreme].max() <= EXTREME_TOLERANCE, (
                f"{name}: near-infinite costs differ by "
                f"{relative[extreme].max():.3e}")


def test_reference_vectors_are_present():
    """Images and reference maps are committed, so the check is reproducible."""
    assert os.path.isdir(VECTOR_DIR)
    images = [n for n in os.listdir(VECTOR_DIR) if n.endswith(".pgm")]
    assert len(images) >= 4
    assert len(_reference_pairs()) == len(images) * len(REFERENCE_MODELS) * 2


def test_convolution_uses_the_matlab_alignment():
    """conv2(..., 'same') starts at floor(K/2), one later than most libraries.

    The reference filters are 16 by 16 and each cost model convolves twice, so
    getting this wrong shifts the whole cost map by two pixels - which is what
    the first comparison against MATLAB actually caught.
    """
    from scipy.signal import convolve2d

    from adaptivestego.cost_models import _conv2_same, wavelet_filters

    image = np.random.default_rng(0).random((40, 40))
    kernel = wavelet_filters()[0]
    full = convolve2d(image, kernel, mode="full")
    offset = kernel.shape[0] // 2
    expected = full[offset:offset + 40, offset:offset + 40]

    interior = (slice(20, 30), slice(20, 30))
    assert np.abs(_conv2_same(image, kernel)[interior]
                  - expected[interior]).max() < 1e-12


# ---------------------------------------------------------------------------
# structural properties, independent of the reference
# ---------------------------------------------------------------------------
def test_every_model_produces_finite_costs_with_the_right_shape():
    cover = synthetic_cover(64, 64, seed=1, channels=1)
    for model in cost_model_names():
        up, down = costs_for(cover, model)
        assert up.shape[:2] == cover.shape
        assert down.shape[:2] == cover.shape
        assert np.all(up > 0) and np.all(down > 0)
        assert np.isfinite(up[up < wet_cost(model)]).all()


def test_costs_are_lower_where_the_image_is_textured():
    """The whole point of a cost model: texture is cheap, flat areas are not.

    How much cheaper differs a lot between models. WOW spreads its costs over
    orders of magnitude, while S-UNIWARD deliberately compresses the range, so
    only the direction is asserted for every model and the strong ratio is
    asserted where it actually holds.
    """
    cover = synthetic_cover(128, 128, seed=1, channels=1)
    ratios = {}
    for model in cost_model_names():
        up, _down = costs_for(cover, model)
        flat = up[20:33, 20:50]                 # inside the constant rectangle
        textured = up[100:, :]
        ratios[model] = float(flat.mean() / textured.mean())
        assert ratios[model] > 1.2, (model, ratios[model])

    assert ratios["wow"] > 5.0
    assert ratios["complexity"] > 5.0


def test_saturated_samples_have_one_wet_direction():
    cover = synthetic_cover(64, 64, seed=2, channels=1).copy()
    cover[0, 0] = 0
    cover[0, 1] = 255
    for model in cost_model_names():
        wet = wet_cost(model)
        up, down = costs_for(cover, model)
        assert down[0, 0] >= wet and up[0, 0] < wet, model
        assert up[0, 1] >= wet and down[0, 1] < wet, model


def test_models_are_deterministic():
    cover = synthetic_cover(64, 64, seed=3, channels=1)
    for model in cost_model_names():
        first = costs_for(cover, model)[0]
        second = costs_for(cover, model)[0]
        assert np.array_equal(first, second), model


def test_colour_costs_have_the_shape_of_the_image():
    cover = synthetic_cover(48, 48, seed=4)
    for model in cost_model_names():
        up, down = costs_for(cover, model)
        assert up.shape == cover.shape and down.shape == cover.shape, model


def test_ported_models_treat_colour_channels_independently():
    """WOW and S-UNIWARD are grayscale models, applied channel by channel."""
    cover = synthetic_cover(48, 48, seed=4)
    for model in ("wow", "uniward"):
        colour = costs_for(cover, model)[0]
        single = costs_for(cover[:, :, 1], model)[0]
        assert np.allclose(colour[:, :, 1], single), model


def test_the_complexity_model_uses_colour_information():
    """Ours is not a per-channel model, and that difference is deliberate.

    It weights the channels by how visible a change is in each and includes an
    inter-channel term, so a channel of a colour image is not costed the same
    way as that channel on its own.
    """
    cover = synthetic_cover(48, 48, seed=4)
    colour = costs_for(cover, "complexity")[0]
    single = costs_for(cover[:, :, 1], "complexity")[0]
    assert not np.allclose(colour[:, :, 1], single)


def test_wavelet_filters_are_the_published_ones():
    filters = cost_models.wavelet_filters()
    assert len(filters) == 3
    for kernel in filters:
        assert kernel.shape == (16, 16)
        # A wavelet detail filter has (almost) zero mean in at least one axis.
        assert abs(kernel.sum()) < 1e-9


def test_unknown_model_is_rejected():
    exc = raises(ValueError, costs_for, synthetic_cover(32, 32, channels=1),
                 "no-such-model")
    assert "unknown cost model" in str(exc)


# ---------------------------------------------------------------------------
# the models inside syndrome coding
# ---------------------------------------------------------------------------
def test_syndrome_coding_works_with_every_cost_model():
    cover = synthetic_cover(96, 96, seed=5)
    n_bits = sl.payload_bits_for_bpp(cover, 0.2)
    payload = deterministic_bits("key", "payload", n_bits)

    for model in cost_model_names():
        result = sl.embed_raw(cover, payload, method="stc", key="k",
                              cost_model=model)
        recovered = sl.extract_raw(result.stego, n_bits, method="stc", key="k",
                                   cost_model=model)
        assert np.array_equal(payload, recovered), model
        assert np.abs(result.stego.astype(int) - cover.astype(int)).max() <= 1


def test_the_cost_model_only_matters_to_the_encoder():
    """The decoder never sees the costs, so it does not need to match."""
    cover = synthetic_cover(96, 96, seed=6)
    payload = deterministic_bits("key", "payload", 2000)
    result = sl.embed_raw(cover, payload, method="stc", key="k",
                          cost_model="wow")
    recovered = sl.extract_raw(result.stego, 2000, method="stc", key="k",
                               cost_model="uniward")
    assert np.array_equal(payload, recovered)
