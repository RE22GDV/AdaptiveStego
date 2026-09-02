"""Tests for syndrome-trellis coding.

A round-trip test alone would be weak here: it only shows that the decoder
undoes the encoder, not that the encoder found a cheap solution. The important
tests are the ones that check the syndrome constraint directly and compare the
result against brute force on vectors short enough to enumerate.
"""

import itertools

import numpy as np
from conftest import raises

import adaptivestego as sl
from adaptivestego import costs, stc
from adaptivestego.codecs import EmbedParams, get_codec
from adaptivestego.exceptions import CapacityError, StegoError
from adaptivestego.prng import deterministic_bits
from adaptivestego.testing import synthetic_cover

RNG = np.random.default_rng(20260902)


def random_case(n, k, wet_fraction=0.0):
    cover = RNG.integers(0, 2, n).astype(np.uint8)
    cost = np.round(RNG.random(n) * 4 + 0.25, 3)
    if wet_fraction:
        wet = RNG.random(n) < wet_fraction
        cost[wet] = costs.WET
    message = RNG.integers(0, 2, k).astype(np.uint8)
    return cover, cost, message


# ---------------------------------------------------------------------------
# the constraint itself
# ---------------------------------------------------------------------------
def test_syndrome_of_the_solution_is_the_message():
    for n, k, height in [(64, 16, 4), (200, 80, 6), (1000, 400, 8), (60, 60, 5)]:
        cover, cost, message = random_case(n, k)
        result = stc.embed(cover, cost, message, height=height, key="k")
        assert np.array_equal(stc.syndrome(result.bits, k, height, "k"), message)
        assert np.array_equal(stc.extract(result.bits, k, height=height, key="k"),
                              message)


def test_syndrome_is_linear():
    """H(a xor b) = Ha xor Hb - the defining property of the code."""
    n, k, height = 300, 100, 6
    a = RNG.integers(0, 2, n).astype(np.uint8)
    b = RNG.integers(0, 2, n).astype(np.uint8)
    left = stc.syndrome(a ^ b, k, height, "k")
    right = stc.syndrome(a, k, height, "k") ^ stc.syndrome(b, k, height, "k")
    assert np.array_equal(left, right)


def test_parity_matrix_is_banded_and_reproducible():
    n, k, height = 200, 50, 6
    columns = stc.parity_columns(n, k, height, "k")
    assert np.array_equal(columns, stc.parity_columns(n, k, height, "k"))
    assert not np.array_equal(columns, stc.parity_columns(n, k, height, "other"))

    # Every column reaches its own constraint, and none reaches past the end.
    blocks = stc.block_of_column(n, k)
    assert np.all(columns & 1 == 1)
    highest = np.array([int(c).bit_length() for c in columns])
    assert np.all(blocks + highest <= k)


# ---------------------------------------------------------------------------
# optimality, by exhaustive search
# ---------------------------------------------------------------------------
def _brute_force_minimum(cover, cost, message, height, key):
    """Cheapest y over all 2**n vectors that satisfy the constraint."""
    best = np.inf
    for combination in itertools.product((0, 1), repeat=cover.size):
        candidate = np.array(combination, dtype=np.uint8)
        if np.array_equal(stc.syndrome(candidate, message.size, height, key),
                          message):
            changed = candidate != cover
            if np.any(np.isinf(cost[changed])):
                continue
            best = min(best, float(cost[changed].sum()))
    return best


def test_solution_is_the_true_minimum():
    """On short vectors the exact optimum can be enumerated - match it."""
    for n, k, height in [(12, 4, 3), (14, 5, 4), (15, 7, 2), (16, 8, 5),
                         (13, 3, 4), (10, 10, 3)]:
        cover, cost, message = random_case(n, k)
        result = stc.embed(cover, cost, message, height=height, key="brute")
        best = _brute_force_minimum(cover, cost, message, height, "brute")
        assert abs(result.distortion - best) < 1e-9, (n, k, height,
                                                      result.distortion, best)


def test_solution_is_the_true_minimum_with_wet_samples():
    """Unusable samples must be respected and still leave an optimal answer."""
    for n, k, height in [(14, 4, 3), (16, 5, 4), (15, 6, 3)]:
        cover, cost, message = random_case(n, k, wet_fraction=0.3)
        try:
            result = stc.embed(cover, cost, message, height=height, key="wet")
        except StegoError:
            assert _brute_force_minimum(cover, cost, message, height,
                                        "wet") == np.inf
            continue
        assert np.all(result.bits[np.isinf(cost)] == cover[np.isinf(cost)])
        best = _brute_force_minimum(cover, cost, message, height, "wet")
        assert abs(result.distortion - best) < 1e-9


def test_reported_distortion_matches_the_changes():
    cover, cost, message = random_case(400, 150)
    result = stc.embed(cover, cost, message, height=7, key="k")
    changed = result.bits != cover
    assert result.changes == int(changed.sum())
    assert abs(result.distortion - float(cost[changed].sum())) < 1e-9
    assert abs(result.efficiency - message.size / result.changes) < 1e-9


# ---------------------------------------------------------------------------
# behaviour across the parameter space
# ---------------------------------------------------------------------------
def test_taller_trellis_never_costs_much_more():
    """More states means a wider search, so the cost should not get worse.

    It is not guaranteed to improve monotonically, because a taller trellis is
    also a different parity check matrix, but it must stay in the same range.
    """
    cover, cost, message = random_case(2000, 500)
    distortions = {}
    for height in (2, 4, 6, 8, 10):
        result = stc.embed(cover, cost, message, height=height, key="k")
        assert np.array_equal(stc.extract(result.bits, message.size,
                                          height=height, key="k"), message)
        distortions[height] = result.distortion
    assert distortions[10] < distortions[2]


def test_higher_payload_costs_more():
    cover = RNG.integers(0, 2, 2000).astype(np.uint8)
    cost = RNG.random(2000) + 0.1
    previous = -1.0
    for k in (100, 400, 800, 1600):
        message = RNG.integers(0, 2, k).astype(np.uint8)
        result = stc.embed(cover, cost, message, height=8, key="k")
        assert result.distortion > previous
        previous = result.distortion


def test_syndrome_coding_beats_random_placement_at_equal_payload():
    """The point of the whole exercise: fewer and cheaper changes."""
    n, k = 4000, 800
    cover = RNG.integers(0, 2, n).astype(np.uint8)
    cost = RNG.random(n) + 0.05
    message = RNG.integers(0, 2, k).astype(np.uint8)

    result = stc.embed(cover, cost, message, height=9, key="k")

    # Writing the message into the first k positions, ignoring the costs.
    naive = cover.copy()
    naive[:k] = message
    naive_cost = float(cost[:k][naive[:k] != cover[:k]].sum())

    assert result.changes < k / 2
    assert result.distortion < naive_cost
    assert result.efficiency > 2.0


def test_empty_and_degenerate_inputs():
    cover = RNG.integers(0, 2, 50).astype(np.uint8)
    cost = np.ones(50)
    empty = stc.embed(cover, cost, np.zeros(0, dtype=np.uint8), height=4)
    assert np.array_equal(empty.bits, cover) and empty.changes == 0

    raises(CapacityError, stc.embed, cover, cost,
           np.zeros(51, dtype=np.uint8), height=4)
    raises(ValueError, stc.embed, cover, cost[:10], np.zeros(5, dtype=np.uint8))
    raises(ValueError, stc.parity_columns, 10, 5, 0)
    raises(ValueError, stc.parity_columns, 10, 5, stc.MAX_HEIGHT + 1)


def test_all_wet_has_no_solution():
    cover = RNG.integers(0, 2, 40).astype(np.uint8)
    cost = np.full(40, costs.WET)
    message = 1 - stc.syndrome(cover, 10, 4, "k")      # forces some change
    raises(StegoError, stc.embed, cover, cost, message, height=4, key="k")


# ---------------------------------------------------------------------------
# costs derived from an image
# ---------------------------------------------------------------------------
def test_costs_are_lower_where_the_image_is_complex():
    img = synthetic_cover(128, 128, seed=1)
    up, down = costs.embedding_costs(img)
    flat = up[20:35, 20:50]                    # inside the constant rectangle
    textured = up[100:, :]
    assert flat.mean() > 3.0 * textured.mean()


def test_boundary_samples_have_a_wet_direction():
    img = synthetic_cover(64, 64, seed=2).copy()
    img[0, 0, :] = 0          # whole pixel at the bottom of the range
    img[0, 1, :] = 255        # and at the top
    up, down = costs.embedding_costs(img)
    assert np.all(np.isinf(down[0, 0])) and np.all(np.isfinite(up[0, 0]))
    assert np.all(np.isinf(up[0, 1])) and np.all(np.isfinite(down[0, 1]))

    # The binary cost stays finite: one direction is always available.
    assert np.all(np.isfinite(costs.binary_costs(up, down)))

    direction = costs.preferred_direction(up, down, key="k")
    assert np.all(direction[0, 0] == 1) and np.all(direction[0, 1] == -1)
    assert set(np.unique(direction)) <= {-1, 1}


# ---------------------------------------------------------------------------
# the codec on real images
# ---------------------------------------------------------------------------
def test_stc_codec_roundtrip():
    img = synthetic_cover(96, 96, seed=3)
    n_bits = sl.payload_bits_for_bpp(img, 0.2)
    payload = deterministic_bits("key", "payload", n_bits)
    result = sl.embed_raw(img, payload, method="stc", key="k")
    assert np.array_equal(
        sl.extract_raw(result.stego, n_bits, method="stc", key="k"), payload)


def test_stc_changes_samples_by_one_and_stays_in_range():
    img = synthetic_cover(96, 96, seed=4).copy()
    img[0, :10, :] = 0                    # force the boundary cases
    img[1, :10, :] = 255
    payload = deterministic_bits("key", "payload", 3000)
    result = sl.embed_raw(img, payload, method="stc", key="k")
    difference = result.stego.astype(int) - img.astype(int)
    assert np.abs(difference).max() <= 1
    assert result.stego.min() >= 0 and result.stego.max() <= 255
    # A sample at 0 may only go up, one at 255 may only go down.
    assert np.all(difference[img == 0] >= 0)
    assert np.all(difference[img == 255] <= 0)
    assert np.array_equal(
        sl.extract_raw(result.stego, 3000, method="stc", key="k"), payload)


def test_stc_needs_the_right_key_and_height():
    img = synthetic_cover(96, 96, seed=5)
    payload = deterministic_bits("key", "payload", 2000)
    result = sl.embed_raw(img, payload, method="stc", key="right")
    assert not np.array_equal(
        sl.extract_raw(result.stego, 2000, method="stc", key="wrong"), payload)
    assert not np.array_equal(
        sl.extract_raw(result.stego, 2000, method="stc", key="right",
                       stc_height=6), payload)


def test_stc_is_cheaper_than_ordered_placement():
    """At an equal payload, minimum-distortion embedding changes less."""
    from adaptivestego import metrics

    img = synthetic_cover(128, 128, seed=6)
    n_bits = sl.payload_bits_for_bpp(img, 0.2)
    payload = deterministic_bits("key", "payload", n_bits)

    syndrome_coded = sl.embed_raw(img, payload, method="stc", key="k")
    ordered = sl.embed_raw(img, payload, method="adaptive-matching", key="k")

    assert syndrome_coded.changed_samples < ordered.changed_samples
    assert metrics.psnr(img, syndrome_coded.stego) > metrics.psnr(img, ordered.stego)


def test_stc_refuses_the_container_format():
    img = synthetic_cover(64, 64)
    exc = raises(StegoError, sl.embed, img, "hello", method="stc", key="k")
    assert "syndrome" in str(exc)
    raises(StegoError, sl.extract, img, method="stc", key="k")


def test_stc_requires_one_bit_per_sample():
    img = synthetic_cover(64, 64)
    payload = deterministic_bits("key", "payload", 500)
    raises(ValueError, sl.embed_raw, img, payload, method="stc", key="k",
           bits_per_sample=2)


def test_stc_positions_do_not_depend_on_the_image():
    """No ranking means nothing for an attacker to disturb."""
    codec = get_codec("stc")
    params = EmbedParams(key="k")
    first = codec.positions(synthetic_cover(64, 64, seed=1), params)
    second = codec.positions(synthetic_cover(64, 64, seed=2), params)
    assert np.array_equal(first, second)
    assert np.array_equal(first, np.arange(first.size))
