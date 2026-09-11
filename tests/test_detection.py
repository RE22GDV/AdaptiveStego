"""Tests for the detection tools: probing, scanning, file forensics, models.

The statistical detectors are checked against payloads whose size is known, so
the assertions are about what the estimator should say rather than about a
number that happened to come out once.
"""

import os
import struct
import tempfile
import zlib

import numpy as np
from conftest import skip

import adaptivestego as sl
from adaptivestego import analysis, container, crypto, detector, forensics
from adaptivestego.exceptions import ContainerError
from adaptivestego.features import SPAM_DIM, spam_features
from adaptivestego.prng import deterministic_bits
from adaptivestego.testing import synthetic_cover


def _write(path: str, data: bytes) -> str:
    with open(path, "wb") as handle:
        handle.write(data)
    return path


def _png_bytes(cover=None) -> bytes:
    """A real PNG on disk, as bytes, for the file-structure tests."""
    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, "x.png")
        sl.write_image(path, synthetic_cover(32, 32, seed=1)
                       if cover is None else cover)
        with open(path, "rb") as handle:
            return handle.read()


# ---------------------------------------------------------------------------
# detection before decryption
# ---------------------------------------------------------------------------
def test_detect_finds_a_container_and_says_what_it_is():
    cover = synthetic_cover(128, 128, seed=2)
    message = "a message of a very particular length"
    result = sl.embed(cover, message, method="adaptive", key="k", compress=False)

    probe = sl.detect(result.stego, method="adaptive", key="k")
    assert probe.found and probe.readable
    assert probe.message_bytes == len(message)
    assert probe.container_bytes == result.payload_bytes
    assert not probe.needs_password


def test_detect_reports_absence_without_raising():
    """A clean image is an answer, not an error."""
    probe = sl.detect(synthetic_cover(64, 64, seed=3), method="adaptive", key="k")
    assert not probe.found
    assert not probe.readable
    assert probe.detail


def test_detect_needs_no_password_to_describe_an_encrypted_container():
    if not crypto.available():
        skip("the cryptography package is not installed")
    cover = synthetic_cover(128, 128, seed=4)
    result = sl.embed(cover, "secret", method="adaptive", key="k",
                      password="pw", compress=False)

    probe = sl.detect(result.stego, method="adaptive", key="k")
    assert probe.found and probe.encrypted and probe.needs_password
    assert not probe.readable
    assert probe.message_bytes == len("secret")


def test_detect_with_the_password_reads_the_message():
    if not crypto.available():
        skip("the cryptography package is not installed")
    cover = synthetic_cover(128, 128, seed=5)
    result = sl.embed(cover, "secret", method="adaptive", key="k", password="pw")
    probe = sl.detect(result.stego, method="adaptive", key="k", password="pw")
    assert probe.readable and not probe.needs_password


def test_detect_is_wrong_settings_rather_than_wrong_image():
    """The wrong key finds nothing, and that is indistinguishable from empty."""
    cover = synthetic_cover(96, 96, seed=6)
    result = sl.embed(cover, "hidden", method="adaptive", key="right")
    assert not sl.detect(result.stego, method="adaptive", key="wrong").found


def test_scan_finds_the_method_that_was_used():
    cover = synthetic_cover(96, 96, seed=7)
    result = sl.embed(cover, "found me", method="random", key="k",
                      bits_per_sample=2)

    hits = sl.scan(result.stego, key="k")
    assert hits, "the scan found nothing"
    best = hits[0]
    assert best["method"] == "random"
    assert best["bits_per_sample"] == 2
    assert best["readable"]


def test_scan_of_a_clean_image_finds_nothing():
    assert sl.scan(synthetic_cover(64, 64, seed=8), key=None) == []


def test_probe_survives_a_truncated_container():
    """A header that promises more than the image holds must not crash."""
    blob = container.pack("x" * 40, compress=False)
    state = {"off": 0}

    def read(n):
        chunk = blob[state["off"]:state["off"] + n]
        state["off"] += n
        if len(chunk) < n:
            raise ContainerError("the data ends early")
        return chunk

    truncated = blob[:len(blob) - 10]
    state2 = {"off": 0}

    def read_short(n):
        chunk = truncated[state2["off"]:state2["off"] + n]
        state2["off"] += n
        if len(chunk) < n:
            raise ContainerError("the data ends early")
        return chunk

    assert container.probe(read).readable
    assert not container.probe(read_short).readable


# ---------------------------------------------------------------------------
# statistical detectors
# ---------------------------------------------------------------------------
def _stego(cover, rate, method="random"):
    bits = deterministic_bits("key", "payload",
                              sl.payload_bits_for_bpp(cover, rate))
    return sl.embed_raw(cover, bits, method=method, key="key").stego


def test_the_rate_estimators_track_a_known_payload():
    """SPA, RS and WS all estimate the same quantity, so all three are checked.

    The tolerance is wide because these are estimators on one small synthetic
    image, not because the answer is vague: what is asserted is that each one
    is near the true rate and far from zero.
    """
    cover = synthetic_cover(256, 256, seed=9, channels=1)
    for rate in (0.25, 0.5):
        stego = _stego(cover, rate)
        for name, estimate in (("spa", analysis.sample_pair_analysis(stego)),
                               ("rs", analysis.rs_analysis(stego)["rate"]),
                               ("ws", analysis.weighted_stego(stego))):
            assert abs(estimate - rate) < 0.15, (name, rate, estimate)


def test_the_rate_estimators_are_near_zero_on_a_clean_image():
    cover = synthetic_cover(256, 256, seed=10, channels=1)
    assert analysis.sample_pair_analysis(cover) < 0.1
    assert analysis.rs_analysis(cover)["rate"] < 0.1
    assert analysis.weighted_stego(cover) < 0.1


def test_the_rate_estimators_are_blind_to_lsb_matching():
    """Not a defect: they detect the pairing that +/-1 embedding never creates.

    Asserted so that a change which appears to improve them is checked against
    what they are actually measuring.
    """
    cover = synthetic_cover(256, 256, seed=11, channels=1)
    stego = _stego(cover, 0.5, method="matching")
    assert analysis.sample_pair_analysis(stego) < 0.2
    assert analysis.weighted_stego(stego) < 0.25


def test_the_verdict_reports_its_reasons():
    cover = synthetic_cover(256, 256, seed=12, channels=1)
    clean = analysis.quick_report(cover)
    assert clean["verdict"]["level"] == "clean"
    assert clean["verdict"]["reasons"] == []

    loud = analysis.quick_report(_stego(cover, 0.6))
    assert loud["verdict"]["level"] == "detected"
    assert loud["verdict"]["score"] >= 2
    assert loud["verdict"]["reasons"]


def test_chi_square_sees_sequential_embedding_where_it_happened():
    """Blocks the embedding reached change; blocks past the end do not.

    Asserted as a change from the cover rather than as an absolute level,
    because the absolute level means little: this synthetic cover already
    reads p = 1 in five of its eight clean blocks, which is the same effect
    that makes a high chi-square probability on its own worth 22 % false
    positives on real photographs and keeps it out of the verdict score.
    """
    cover = synthetic_cover(256, 256, seed=13, channels=1)
    bits = deterministic_bits("k", "p", sl.payload_bits_for_bpp(cover, 0.5))
    stego = sl.embed_raw(cover, bits, method="sequential").stego

    before = analysis.chi_square_attack(cover, n_blocks=8)["blocks"]
    after = analysis.chi_square_attack(stego, n_blocks=8)["blocks"]

    assert before[1] < 0.1 and after[1] > 0.9, (before[1], after[1])
    assert after[-1] == before[-1], "a block past the payload must not change"


def test_bit_plane_profile_has_one_entry_per_plane():
    profile = analysis.bit_plane_profile(synthetic_cover(64, 64, seed=14))
    assert len(profile["ones_ratio"]) == 8
    assert len(profile["autocorr_lag1"]) == 8
    # The top plane carries the picture, the bottom one is closest to noise.
    assert profile["autocorr_lag1"][7] > profile["autocorr_lag1"][0]


def test_hcf_com_is_reported_for_colour_and_grayscale():
    for channels in (1, 3):
        report = analysis.hcf_com(synthetic_cover(64, 64, seed=15,
                                                  channels=channels))
        assert report["com"] > 0 and report["com_calibrated"] > 0
        assert 0.0 < report["ratio"] < 3.0


def test_quick_report_has_every_advertised_detector():
    report = analysis.quick_report(synthetic_cover(64, 64, seed=16))
    for name in analysis.DETECTORS:
        assert name in report, name


# ---------------------------------------------------------------------------
# file-structure forensics
# ---------------------------------------------------------------------------
def test_appended_data_after_the_end_of_a_png_is_found():
    data = _png_bytes()
    with tempfile.TemporaryDirectory() as folder:
        path = _write(os.path.join(folder, "trailer.png"),
                      data + b"SECRET-PAYLOAD" * 20)
        report = forensics.file_report(path)
        kinds = {f.kind for f in report.findings}
        assert "appended data" in kinds
        assert report.level == "detected"


def test_a_clean_png_has_no_findings():
    with tempfile.TemporaryDirectory() as folder:
        path = _write(os.path.join(folder, "clean.png"), _png_bytes())
        report = forensics.file_report(path)
        assert report.format == "png"
        assert report.level == "clean", [f.as_dict() for f in report.findings]


def test_a_text_chunk_in_a_png_is_reported():
    data = _png_bytes()
    end = data.rfind(b"IEND") - 4
    payload = b"Comment\x00" + b"a hidden note " * 60
    chunk = (struct.pack(">I", len(payload)) + b"tEXt" + payload
             + struct.pack(">I", zlib.crc32(b"tEXt" + payload) & 0xFFFFFFFF))
    with tempfile.TemporaryDirectory() as folder:
        path = _write(os.path.join(folder, "text.png"),
                      data[:end] + chunk + data[end:])
        report = forensics.file_report(path)
        findings = {f.kind: f for f in report.findings}
        assert "metadata chunk" in findings
        assert findings["metadata chunk"].severity == "suspicious"


def test_an_embedded_archive_is_found_wherever_it_sits():
    data = _png_bytes()
    with tempfile.TemporaryDirectory() as folder:
        path = _write(os.path.join(folder, "zip.png"),
                      data + b"PK\x03\x04" + b"\x00" * 64)
        report = forensics.file_report(path)
        assert any(f.kind == "embedded file" for f in report.findings)


def test_an_extension_that_lies_is_reported():
    with tempfile.TemporaryDirectory() as folder:
        path = _write(os.path.join(folder, "photo.jpg"), _png_bytes())
        report = forensics.file_report(path)
        assert report.format == "png"
        assert not report.extension_matches
        assert any(f.kind == "extension mismatch" for f in report.findings)


def test_a_bmp_gap_before_the_pixels_is_reported():
    """BMP lets the header point past itself, and the gap is a hiding place."""
    with tempfile.TemporaryDirectory() as folder:
        source = os.path.join(folder, "x.bmp")
        sl.write_image(source, synthetic_cover(16, 16, seed=17))
        with open(source, "rb") as handle:
            data = bytearray(handle.read())

        hidden = b"H" * 64
        offset = struct.unpack("<I", bytes(data[10:14]))[0]
        dib = struct.unpack("<I", bytes(data[14:18]))[0]
        patched = (bytes(data[:14 + dib]) + hidden + bytes(data[14 + dib:]))
        patched = bytearray(patched)
        patched[10:14] = struct.pack("<I", offset + len(hidden))
        patched[2:6] = struct.pack("<I", len(patched))

        path = _write(os.path.join(folder, "gap.bmp"), bytes(patched))
        report = forensics.file_report(path)
        assert any(f.kind == "header gap" for f in report.findings), \
            [f.as_dict() for f in report.findings]


def test_byte_entropy_separates_text_from_random():
    assert forensics.byte_entropy(b"aaaaaaaaaaaaaaaa") < 1.0
    assert forensics.byte_entropy(bytes(range(256)) * 4) > 7.9


def test_full_report_covers_every_stage():
    cover = synthetic_cover(128, 128, seed=18)
    result = sl.embed(cover, "a message worth finding", method="adaptive",
                      key="k")
    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, "stego.png")
        sl.write_image(path, result.stego)
        report = forensics.full_report(path, key="k")

    assert report["file"]["format"] == "png"
    assert "verdict" in report["pixels"]
    assert report["container_found"]
    assert report["level"] == "detected"
    assert any(hit["readable"] for hit in report["containers"])


def test_full_report_on_something_that_is_not_an_image():
    with tempfile.TemporaryDirectory() as folder:
        path = _write(os.path.join(folder, "notes.png"), b"not an image at all")
        report = forensics.full_report(path)
        assert "error" in report["pixels"]
        assert report["level"] in ("clean", "suspicious", "detected")


# ---------------------------------------------------------------------------
# features and the trained model
# ---------------------------------------------------------------------------
def test_spam_features_have_the_documented_shape():
    features = spam_features(synthetic_cover(64, 64, seed=19, channels=1))
    assert features.shape == (SPAM_DIM,)
    # Each of the two groups holds 49 conditional distributions summing to one.
    assert abs(features.sum() - 98.0) < 1e-9
    assert (features >= 0).all()


def test_spam_features_move_when_a_payload_is_embedded():
    cover = synthetic_cover(128, 128, seed=20, channels=1)
    stego = _stego(cover, 0.5, method="matching")
    assert not np.allclose(spam_features(cover), spam_features(stego))


def test_spam_features_are_deterministic():
    cover = synthetic_cover(64, 64, seed=21, channels=1)
    assert np.array_equal(spam_features(cover), spam_features(cover))


def test_the_trained_model_loads_and_carries_its_provenance():
    model = detector.load()
    if model is None:
        skip("no trained model is installed")
    assert model.weights.shape == (SPAM_DIM,)
    for field in ("trained_on", "valid_for", "method", "bpp", "test_auc"):
        assert field in model.meta, field
    assert "AUC" in model.describe()


def test_the_trained_model_separates_covers_from_stegos():
    """A weak check on synthetic images: the model must at least order them.

    The shipped model is trained on photographs, so its accuracy on a
    synthetic cover means nothing; what must hold is that adding a payload
    moves the score in the direction the model was trained to move it.
    """
    model = detector.load()
    if model is None:
        skip("no trained model is installed")
    wins = 0
    for seed in range(6):
        cover = synthetic_cover(256, 256, seed=30 + seed, channels=1)
        stego = _stego(cover, 0.5, method="matching")
        wins += model.score(stego) > model.score(cover)
    assert wins >= 5, f"the payload raised the score in only {wins} of 6"


def test_roc_auc_matches_hand_computed_cases():
    assert detector.roc_auc([0, 1, 2], [3, 4, 5]) == 1.0
    assert detector.roc_auc([3, 4, 5], [0, 1, 2]) == 0.0
    assert detector.roc_auc([0, 1], [0, 1]) == 0.5


def test_training_recovers_a_separable_split():
    """The trainer must find a direction that exists, and calibrate on it."""
    # A shift of three standard deviations along one of twelve dimensions:
    # separable, but only for a classifier that finds the right direction.
    rng = np.random.default_rng(7)
    cover = rng.normal(0.0, 1.0, (200, 12))
    stego = cover + np.array([3.0] + [0.0] * 11)
    model = detector.train_fld(cover, stego, meta={"method": "synthetic"})
    assert model.meta["validation_auc"] > 0.9
    assert model.score_features(stego[0]) > model.score_features(cover[0])
    assert 0.0 <= model.probability_of_score(model.score_features(stego[0])) <= 1.0


def test_autocorrelation_is_measured_along_rows_not_across_the_layout():
    """A grayscale image stored as three channels must read the same.

    Taking the lag-1 correlation over the flattened array instead measures how
    the samples are laid out: three identical channels put a copy of every
    sample next to itself, and the number comes out near 2/3 whatever the
    image holds.
    """
    gray = synthetic_cover(64, 64, seed=40, channels=1)
    tripled = np.repeat(gray[:, :, None], 3, axis=2)

    one = analysis.lsb_plane_stats(gray)
    three = analysis.lsb_plane_stats(tripled)
    assert abs(one["autocorr_lag1"] - three["autocorr_lag1"]) < 1e-9
    assert abs(one["ones_ratio"] - three["ones_ratio"]) < 1e-9


def test_full_report_collapses_a_grayscale_image_stored_in_colour():
    import tempfile

    gray = synthetic_cover(64, 64, seed=41, channels=1)
    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, "gray.png")
        sl.write_image(path, gray)
        report = forensics.full_report(path, scan_methods=False)
    assert report["image"]["channels"] == 1
