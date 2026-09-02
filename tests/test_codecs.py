"""Embedding tests: round-trips, keys, capacity and map determinism."""

import numpy as np
from conftest import raises, skip

import adaptivestego as sl
from adaptivestego import core, crypto, ecc
from adaptivestego.codecs import EmbedParams, get_codec
from adaptivestego.exceptions import CapacityError, ContainerError, CryptoError
from adaptivestego.maps import MAP_KINDS, complexity_map, mask_low_bits
from adaptivestego.testing import synthetic_cover

METHODS = sl.codec_names()
MESSAGE = "Привет! Cyrillic, ASCII and 🙂 in a single message."


def cover(seed=0, h=96, w=96, channels=3):
    return synthetic_cover(h, w, seed=seed, channels=channels)


def test_all_methods_roundtrip():
    img = cover()
    for method in METHODS:
        res = sl.embed(img, MESSAGE, method=method, key="the-key")
        assert sl.extract(res.stego, method=method, key="the-key") == MESSAGE, method


def test_cover_is_not_modified_in_place():
    img = cover()
    before = img.copy()
    sl.embed(img, MESSAGE, method="adaptive", key="k")
    assert np.array_equal(img, before)


def test_stego_differs_from_cover():
    img = cover()
    res = sl.embed(img, MESSAGE, method="adaptive", key="k")
    assert not np.array_equal(img, res.stego)
    assert res.changed_samples > 0


def test_replacement_changes_only_low_bit():
    img = cover()
    res = sl.embed(img, MESSAGE, method="random", key="k", bits_per_sample=1)
    assert np.array_equal(res.stego >> 1, img >> 1)


def test_matching_changes_value_by_one_at_most():
    img = cover()
    res = sl.embed(img, MESSAGE, method="matching", key="k")
    assert int(np.abs(res.stego.astype(int) - img.astype(int)).max()) <= 1


def test_wrong_key_fails():
    img = cover()
    res = sl.embed(img, MESSAGE, method="adaptive", key="right")
    raises(ContainerError, sl.extract, res.stego, method="adaptive", key="wrong")


def test_wrong_method_fails():
    img = cover()
    res = sl.embed(img, MESSAGE, method="adaptive", key="k")
    raises(ContainerError, sl.extract, res.stego, method="sequential", key="k")


def test_clean_image_reports_no_message():
    exc = raises(ContainerError, sl.extract, cover(), method="adaptive", key="k")
    assert "signature" in str(exc)


def test_bits_per_sample_variants():
    img = cover()
    for bits in (1, 2, 3, 4):
        res = sl.embed(img, MESSAGE, method="random", key="k", bits_per_sample=bits)
        got = sl.extract(res.stego, method="random", key="k", bits_per_sample=bits)
        assert got == MESSAGE, bits
        assert res.max_bpp == 3 * bits


def test_more_bits_per_sample_means_more_distortion():
    img = cover()
    long_message = MESSAGE * 20
    d1 = np.abs(sl.embed(img, long_message, method="random", key="k",
                         bits_per_sample=1).stego.astype(int) - img.astype(int)).max()
    d3 = np.abs(sl.embed(img, long_message, method="random", key="k",
                         bits_per_sample=3).stego.astype(int) - img.astype(int)).max()
    assert d1 == 1 and d3 > d1


def test_channel_selection():
    img = cover()
    res = sl.embed(img, MESSAGE, method="random", key="k", channels=(2,))
    assert np.array_equal(res.stego[:, :, :2], img[:, :, :2])
    assert sl.extract(res.stego, method="random", key="k", channels=(2,)) == MESSAGE


def test_grayscale_roundtrip():
    img = cover(channels=1)
    res = sl.embed(img, MESSAGE, method="adaptive", key="k")
    assert sl.extract(res.stego, method="adaptive", key="k") == MESSAGE


def test_capacity_report_and_overflow():
    img = cover(h=32, w=32)
    info = sl.capacity(img, method="random")
    assert info["capacity_bits"] == img.size
    too_long = "y" * (info["message_bytes_max"] + 100)
    raises(CapacityError, sl.embed, img, too_long, method="random",
           key="k", compress=False)


def test_capacity_is_actually_usable():
    img = cover(h=64, w=64)
    info = sl.capacity(img, method="random")
    payload = b"\x00" * info["message_bytes_max"]
    res = sl.embed(img, payload, method="random", key="k", compress=False)
    assert res.payload_bytes <= info["capacity_bytes"]
    assert sl.extract(res.stego, method="random", key="k", as_text=False) == payload


def test_binary_payload_roundtrip():
    img = cover()
    data = bytes(np.random.default_rng(0).integers(0, 256, 500, dtype=np.uint8))
    res = sl.embed(img, data, method="adaptive", key="k")
    assert sl.extract(res.stego, method="adaptive", key="k", as_text=False) == data


def test_positions_are_deterministic_and_key_dependent():
    img = cover()
    codec = get_codec("adaptive")
    p1 = codec.positions(img, EmbedParams(key="a"))
    p2 = codec.positions(img, EmbedParams(key="a"))
    p3 = codec.positions(img, EmbedParams(key="b"))
    assert np.array_equal(p1, p2)
    assert not np.array_equal(p1, p3)
    assert sorted(p1.tolist()) == list(range(img.size))


def test_complexity_map_identical_for_cover_and_stego():
    """The property adaptive embedding depends on: the map never moves."""
    img = cover()
    for method in ("adaptive", "edge", "adaptive-matching"):
        codec = get_codec(method)
        params = EmbedParams(key="k")
        mask = codec.mask_bits(params)
        res = sl.embed(img, MESSAGE * 5, method=method, key="k")
        for kind in MAP_KINDS:
            before = complexity_map(img, kind, mask_bits=mask)
            after = complexity_map(res.stego, kind, mask_bits=mask)
            assert np.array_equal(before, after), (method, kind)
        assert np.array_equal(codec.positions(img, params),
                              codec.positions(res.stego, params))


def test_masked_high_bits_survive_matching():
    img = cover()
    res = sl.embed(img, MESSAGE * 5, method="adaptive-matching", key="k")
    assert np.array_equal(mask_low_bits(res.stego, 2), mask_low_bits(img, 2))


def test_adaptive_writes_into_complex_areas_only():
    """A short message must land in the samples with high complexity."""
    img = cover(h=128, w=128)
    res = sl.embed(img, MESSAGE, method="adaptive", key="k")
    cmap = complexity_map(img, "combined", mask_bits=1)
    changed = res.stego != img
    assert changed.any()
    assert cmap[changed].mean() > 3.0 * cmap.mean()

    # The interior of the flat rectangle is left untouched.
    flat = (slice(int(128 * 0.15) + 4, int(128 * 0.35) - 4),
            slice(int(128 * 0.10) + 4, int(128 * 0.45) - 4))
    assert not changed[flat].any()


def test_sequential_unlike_adaptive_writes_into_flat_areas():
    """At an equal payload the adaptive method spares the flat regions."""
    img = cover(h=128, w=128)
    payload = bytes(np.random.default_rng(3).integers(0, 256, 5000, dtype=np.uint8))
    flat = (slice(int(128 * 0.15) + 4, int(128 * 0.35) - 4),
            slice(int(128 * 0.10) + 4, int(128 * 0.45) - 4))
    seq = sl.embed(img, payload, method="sequential", compress=False).stego
    ada = sl.embed(img, payload, method="adaptive", key="k", compress=False).stego
    assert np.count_nonzero((seq != img)[flat]) > np.count_nonzero((ada != img)[flat])


def test_adaptive_beats_sequential_on_ssim():
    from adaptivestego import metrics

    img = cover(h=128, w=128)
    message = MESSAGE * 8
    seq = sl.embed(img, message, method="sequential", key="k").stego
    ada = sl.embed(img, message, method="adaptive", key="k").stego
    assert metrics.ssim(img, ada) > metrics.ssim(img, seq)


def test_all_maps_work():
    img = cover()
    for kind in MAP_KINDS:
        res = sl.embed(img, MESSAGE, method="adaptive", key="k", map_kind=kind)
        assert sl.extract(res.stego, method="adaptive", key="k",
                          map_kind=kind) == MESSAGE, kind


def test_map_mismatch_fails():
    img = cover()
    res = sl.embed(img, MESSAGE, method="adaptive", key="k", map_kind="sobel")
    raises(ContainerError, sl.extract, res.stego, method="adaptive", key="k",
           map_kind="entropy")


def test_map_mask_bits_below_minimum_is_refused():
    img = cover()
    raises(ValueError, sl.embed, img, MESSAGE, method="adaptive-matching",
           key="k", map_mask_bits=1)


def test_encrypted_roundtrip_in_image():
    if not crypto.available():
        skip("needs the cryptography package")
    img = cover()
    res = sl.embed(img, MESSAGE, method="adaptive", key="k", password="pw")
    assert sl.extract(res.stego, method="adaptive", key="k", password="pw") == MESSAGE
    raises(CryptoError, sl.extract, res.stego, method="adaptive", key="k",
           password="another")


def test_ecc_survives_pixel_damage():
    if not ecc.available():
        skip("needs the reedsolo package")
    img = cover(h=128, w=128)
    res = sl.embed(img, MESSAGE, method="random", key="k", ecc_nsym=32)
    stego = res.stego.copy()
    rng = np.random.default_rng(0)
    flat = stego.reshape(-1)
    flat[rng.choice(2000, size=40, replace=False)] ^= 1
    assert sl.extract(stego, method="random", key="k") == MESSAGE


def test_unknown_method_and_params():
    img = cover()
    raises(ValueError, sl.embed, img, MESSAGE, method="no-such-method")
    raises(TypeError, sl.embed, img, MESSAGE, method="random", nonsense=1)


def test_core_capacity_error_message():
    img = cover(h=8, w=8)
    positions = np.arange(img.size, dtype=np.int64)
    bits = np.ones(img.size + 8, dtype=np.uint8)
    raises(CapacityError, core.embed_bits, img, bits, positions)
