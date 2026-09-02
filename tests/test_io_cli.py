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


def _run_cli(args, tmp):
    env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "src"),
               PYTHONIOENCODING="utf-8")
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
