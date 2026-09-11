"""Tests for image I/O, the command line interface and the legacy format."""

import os
import subprocess
import sys
import tempfile

import numpy as np
from conftest import raises

import adaptivestego as sl
from adaptivestego.exceptions import StegoError
from adaptivestego.image_io import read_image, write_image
from adaptivestego.testing import synthetic_cover

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MESSAGE = "Message through a file: UTF-8 and paths, Привет."


def test_png_roundtrip_is_bit_exact():
    img = synthetic_cover(48, 48)
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "test.png")
        write_image(path, img)
        assert np.array_equal(read_image(path), img)


def test_non_ascii_path_supported():
    img = synthetic_cover(32, 32)
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "изображение-тест.png")
        write_image(path, img)
        assert np.array_equal(read_image(path), img)


def test_lossy_format_refused():
    img = synthetic_cover(32, 32)
    with tempfile.TemporaryDirectory() as tmp:
        exc = raises(StegoError, write_image, os.path.join(tmp, "out.jpg"), img)
        assert "lowest bits" in str(exc)


def test_missing_file_reported():
    raises(FileNotFoundError, read_image, os.path.join(ROOT, "no-such-file.png"))


def test_embed_file_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        cover = os.path.join(tmp, "cover.png")
        stego = os.path.join(tmp, "stego.png")
        write_image(cover, synthetic_cover(96, 96))
        sl.embed_file(cover, MESSAGE, stego, method="adaptive", key="k")
        assert sl.extract_file(stego, method="adaptive", key="k") == MESSAGE


def _run_cli(args, tmp, **extra_env):
    env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "src"),
               PYTHONIOENCODING="utf-8", **extra_env)
    return subprocess.run([sys.executable, "-m", "adaptivestego", *args], cwd=tmp,
                          env=env, capture_output=True, text=True, encoding="utf-8")


def test_cli_embed_extract_capacity():
    with tempfile.TemporaryDirectory() as tmp:
        cover = os.path.join(tmp, "cover.png")
        stego = os.path.join(tmp, "stego.png")
        out = os.path.join(tmp, "out.txt")
        write_image(cover, synthetic_cover(96, 96))

        result = _run_cli(["capacity", "-i", cover, "--method", "adaptive"], tmp)
        assert result.returncode == 0, result.stderr
        assert "capacity_bits" in result.stdout

        result = _run_cli(["embed", "-c", cover, "-o", stego, "-t", MESSAGE,
                           "--method", "adaptive", "--key", "pw"], tmp)
        assert result.returncode == 0, result.stderr
        assert os.path.isfile(stego)

        result = _run_cli(["extract", "-i", stego, "-o", out,
                           "--method", "adaptive", "--key", "pw"], tmp)
        assert result.returncode == 0, result.stderr
        with open(out, encoding="utf-8") as f:
            assert f.read() == MESSAGE


def test_cli_reports_error_on_clean_image():
    with tempfile.TemporaryDirectory() as tmp:
        cover = os.path.join(tmp, "cover.png")
        write_image(cover, synthetic_cover(64, 64))
        result = _run_cli(["extract", "-i", cover, "--method", "adaptive",
                           "--key", "pw"], tmp)
        assert result.returncode == 2
        assert "error" in result.stderr


def test_cli_selftest_passes():
    with tempfile.TemporaryDirectory() as tmp:
        result = _run_cli(["selftest"], tmp)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "interoperable" in result.stdout


def test_cli_prints_unicode_message():
    """Windows consoles default to a legacy code page; the CLI forces UTF-8."""
    with tempfile.TemporaryDirectory() as tmp:
        cover = os.path.join(tmp, "cover.png")
        stego = os.path.join(tmp, "stego.png")
        write_image(cover, synthetic_cover(96, 96))
        message = "Привіт, 中文, emoji 🙂"
        _run_cli(["embed", "-c", cover, "-o", stego, "-t", message,
                  "--method", "random", "--key", "k"], tmp)
        result = _run_cli(["extract", "-i", stego, "--method", "random",
                           "--key", "k"], tmp)
        assert result.returncode == 0, result.stderr
        assert message in result.stdout


def _legacy_build(message):
    """The bit packing of the original decoder.py, reproduced verbatim."""
    bits = ""
    for ch in message:
        bits += f"{ord(ch):08b}"
        bits = "0" * ((6 - len(bits) % 6) % 6) + bits
    return bits


def _legacy_read(bits, n_chars):
    useful = bits[-n_chars * 8:]
    return "".join(chr(int(useful[i:i + 8], 2)) for i in range(0, len(useful), 8))


def test_legacy_format_works_for_ascii_but_wastes_half_the_capacity():
    """For ASCII the old format is correct: the padding piles up at the front.

    It still spends 12 bits per character instead of 8, so half of the
    capacity is lost to alignment.
    """
    message = "Hello, world!"
    assert _legacy_read(_legacy_build(message), len(message)) == message
    assert len(_legacy_build(message)) == 12 * len(message)


def test_legacy_format_breaks_on_non_ascii():
    """The real defect: ord(ch):08b does not limit a character to eight bits."""
    assert len(f"{ord('П'):08b}") == 11        # Cyrillic does not fit in 8 bits
    message = "Привет"
    assert _legacy_read(_legacy_build(message), len(message)) != message

    # The new format handles any UTF-8 text.
    img = synthetic_cover(64, 64)
    res = sl.embed(img, message, method="sequential")
    assert sl.extract(res.stego, method="sequential") == message


def test_legacy_capacity_check_underestimates_wide_codepoints():
    """The "two pixels per character" check is wrong above 12 bits."""
    assert len(f"{ord('中'):08b}") == 15 and len(f"{ord('🙂'):08b}") == 17
    message = "中文🙂"
    needed_pixels = len(_legacy_build(message)) / 6
    assert needed_pixels > 2 * len(message)   # the capacity check would pass


def test_cli_detect_reports_a_clean_image_and_a_stego_one():
    """`detect` exits 0 on a clean image and non-zero when it finds something."""
    import json

    with tempfile.TemporaryDirectory() as tmp:
        cover = os.path.join(tmp, "cover.png")
        stego = os.path.join(tmp, "stego.png")
        write_image(cover, synthetic_cover(96, 96, seed=40))

        clean = _run_cli(["detect", "-i", cover, "--no-scan"], tmp)
        assert clean.returncode == 0, clean.stderr
        assert json.loads(clean.stdout)["level"] == "clean"

        _run_cli(["embed", "-c", cover, "-o", stego, "-t", MESSAGE,
                  "--method", "random", "--key", "k"], tmp)
        found = _run_cli(["detect", "-i", stego, "--key", "k"], tmp)
        assert found.returncode == 1, found.stderr
        report = json.loads(found.stdout)
        assert report["container_found"]
        assert any(hit["readable"] for hit in report["containers"])


def test_cli_scan_finds_the_method():
    import json

    with tempfile.TemporaryDirectory() as tmp:
        cover = os.path.join(tmp, "cover.png")
        stego = os.path.join(tmp, "stego.png")
        write_image(cover, synthetic_cover(96, 96, seed=41))
        _run_cli(["embed", "-c", cover, "-o", stego, "-t", "found me",
                  "--method", "random", "--key", "k", "--bits", "2"], tmp)

        result = _run_cli(["scan", "-i", stego, "--key", "k"], tmp)
        hits = json.loads(result.stdout)["hits"]
        assert hits and hits[0]["method"] == "random"
        assert hits[0]["bits_per_sample"] == 2


def test_cli_extract_announces_what_it_found_before_the_password():
    """The detection phase must report, and a missing password must not hang."""
    from adaptivestego import crypto

    if not crypto.available():
        from conftest import skip
        skip("the cryptography package is not installed")

    with tempfile.TemporaryDirectory() as tmp:
        cover = os.path.join(tmp, "cover.png")
        stego = os.path.join(tmp, "stego.png")
        write_image(cover, synthetic_cover(96, 96, seed=42))

        embedded = _run_cli(["embed", "-c", cover, "-o", stego, "-t",
                             "classified", "--method", "random", "--key", "k",
                             "--password-env", "PW"], tmp, PW="pw")
        assert embedded.returncode == 0, embedded.stderr

        # No password, no terminal to prompt on: it must say what it found and
        # then say what it needs, rather than waiting for input that cannot come.
        blocked = _run_cli(["extract", "-i", stego, "--method", "random",
                            "--key", "k"], tmp)
        assert blocked.returncode == 2
        assert "encrypted" in blocked.stderr
        assert "password" in blocked.stderr

        opened = _run_cli(["extract", "-i", stego, "--method", "random",
                           "--key", "k", "--password-env", "PW"], tmp, PW="pw")
        assert opened.returncode == 0, opened.stderr
        assert opened.stdout.strip() == "classified"
        assert "found:" in opened.stderr


def test_cli_refuses_no_key_material_without_a_password():
    with tempfile.TemporaryDirectory() as tmp:
        cover = os.path.join(tmp, "cover.png")
        write_image(cover, synthetic_cover(64, 64, seed=43))
        result = _run_cli(["embed", "-c", cover, "-o", "out.png", "-t", "x",
                           "--no-key-material"], tmp)
        assert result.returncode == 2
        assert "--no-key-material" in result.stderr
