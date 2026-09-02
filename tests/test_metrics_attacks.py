"""Tests for metrics, attacks and classical steganalysis."""

import math

import numpy as np
from conftest import raises

import adaptivestego as sl
from adaptivestego import analysis, attacks, metrics
from adaptivestego.testing import synthetic_cover

MESSAGE = "a message used to check robustness " * 4


def test_psnr_and_ssim_of_identical_images():
    img = synthetic_cover(64, 64)
    assert math.isinf(metrics.psnr(img, img))
    assert abs(metrics.ssim(img, img) - 1.0) < 1e-9
    assert metrics.mse(img, img) == 0.0


def test_psnr_decreases_with_distortion():
    img = synthetic_cover(64, 64)
    weak = attacks.gaussian_noise(img, sigma=1.0, seed=0)
    strong = attacks.gaussian_noise(img, sigma=8.0, seed=0)
    assert metrics.psnr(img, weak) > metrics.psnr(img, strong)
    assert metrics.ssim(img, weak) > metrics.ssim(img, strong)


def test_lsb_embedding_gives_high_psnr():
    img = synthetic_cover(128, 128)
    res = sl.embed(img, MESSAGE, method="adaptive", key="k")
    report = metrics.quality_report(img, res.stego, res.payload_bytes * 8)
    assert report["psnr_db"] > 60
    assert report["ssim"] > 0.999
    assert report["max_abs_diff"] == 1
    assert 1.0 <= report["embedding_efficiency"] <= 8.0


def test_ber_bounds():
    assert metrics.ber(b"abc", b"abc") == 0.0
    assert metrics.ber(b"\x00", b"\xff") == 1.0
    assert 0.0 < metrics.ber(b"\x00\x00", b"\x00\xff") < 1.0
    assert metrics.ber(b"abcd", b"ab") > 0.0  # truncated message


def test_attacks_preserve_shape_and_dtype():
    img = synthetic_cover(64, 64)
    specs = ["identity", "jpeg:quality=85", "noise:sigma=2", "salt_pepper:p=0.01",
             "resize:scale=0.5", "crop:keep=0.9", "brightness:delta=5",
             "contrast:alpha=1.1", "blur:sigma=0.6", "median:ksize=3",
             "quantize:levels=64", "drop:p=0.01"]
    for spec in specs:
        out = attacks.apply_attack(img, spec)
        assert out.shape == img.shape and out.dtype == np.uint8, spec


def test_attacks_are_deterministic():
    img = synthetic_cover(64, 64)
    for spec in ("noise:sigma=3,seed=7", "salt_pepper:p=0.02,seed=7",
                 "drop:p=0.02,seed=7"):
        assert np.array_equal(attacks.apply_attack(img, spec),
                              attacks.apply_attack(img, spec)), spec


def test_unknown_attack_rejected():
    raises(ValueError, attacks.parse_spec, "teleportation:p=1")


def test_identity_attack_keeps_message():
    img = synthetic_cover(96, 96)
    res = sl.embed(img, MESSAGE, method="random", key="k")
    same = attacks.apply_attack(res.stego, "identity")
    assert sl.extract(same, method="random", key="k") == MESSAGE


def test_jpeg_destroys_lsb_message():
    """A documented limitation: LSB embedding does not survive JPEG."""
    img = synthetic_cover(96, 96)
    res = sl.embed(img, MESSAGE, method="random", key="k")
    attacked = attacks.apply_attack(res.stego, "jpeg:quality=75")
    try:
        recovered = sl.extract(attacked, method="random", key="k")
    except Exception:
        return  # nothing was recovered, which is the expected outcome
    assert recovered != MESSAGE


def test_spa_detects_sequential_lsb_but_not_matching():
    img = synthetic_cover(160, 160, seed=2)
    payload = bytes(np.random.default_rng(1).integers(0, 256, 3000, dtype=np.uint8))
    replacement = sl.embed(img, payload, method="random", key="k",
                           compress=False).stego
    matching = sl.embed(img, payload, method="matching", key="k",
                        compress=False).stego
    assert analysis.sample_pair_analysis(replacement) > analysis.sample_pair_analysis(img)
    assert analysis.sample_pair_analysis(matching) < analysis.sample_pair_analysis(replacement)


def test_adaptive_is_less_detectable_by_spa_than_sequential():
    """The project hypothesis in its simplest testable form."""
    img = synthetic_cover(160, 160, seed=3)
    payload = bytes(np.random.default_rng(2).integers(0, 256, 2000, dtype=np.uint8))
    seq = sl.embed(img, payload, method="sequential", key="k", compress=False).stego
    ada = sl.embed(img, payload, method="adaptive", key="k", compress=False).stego
    assert analysis.sample_pair_analysis(ada) < analysis.sample_pair_analysis(seq)


def test_quick_report_fields():
    report = analysis.quick_report(synthetic_cover(64, 64))
    for field in ("chi2_p_max", "spa_rate", "ones_ratio", "autocorr_lag1"):
        assert field in report
