"""Tests for the ASG1 container format."""

from conftest import raises, skip

from adaptivestego import container, crypto, ecc
from adaptivestego.exceptions import ContainerError, CryptoError


def _reader(blob: bytes):
    state = {"off": 0}

    def read(n: int) -> bytes:
        chunk = blob[state["off"]:state["off"] + n]
        if len(chunk) != n:
            raise ContainerError("data ends early")
        state["off"] += n
        return chunk

    return read


def roundtrip(message, **kw):
    blob = container.pack(message, **kw)
    payload, header = container.unpack(_reader(blob), password=kw.get("password"))
    return payload, header, blob


def test_roundtrip_ascii():
    payload, header, _ = roundtrip("hello world")
    assert payload == b"hello world"
    assert header.version == container.VERSION


def test_roundtrip_unicode():
    message = "Привет, мир! Ёжик, 中文, emoji 🙂"
    payload, _, _ = roundtrip(message)
    assert payload.decode("utf-8") == message


def test_roundtrip_empty():
    payload, _, _ = roundtrip("")
    assert payload == b""


def test_roundtrip_bytes():
    data = bytes(range(256)) * 4
    payload, _, _ = roundtrip(data)
    assert payload == data


def test_compression_shrinks_repetitive_text():
    message = "abc" * 500
    small = container.pack(message, compress=True)
    big = container.pack(message, compress=False)
    assert len(small) < len(big)
    assert container.parse_preamble(small).compressed
    assert not container.parse_preamble(big).compressed


def test_bad_magic_rejected():
    blob = bytearray(container.pack("x"))
    blob[0] = ord("Z")
    exc = raises(ContainerError, container.unpack, _reader(bytes(blob)))
    assert "signature" in str(exc)


def test_corrupted_preamble_detected():
    blob = bytearray(container.pack("x"))
    blob[5] ^= 0x40  # damaged flags: the check byte will not match
    raises(ContainerError, container.unpack, _reader(bytes(blob)))


def test_corrupted_payload_detected_by_crc():
    blob = bytearray(container.pack("a message used to verify the crc",
                                    compress=False))
    blob[-1] ^= 0xFF
    raises(ContainerError, container.unpack, _reader(bytes(blob)))


def test_truncated_container_detected():
    blob = container.pack("a longer message so that truncation is visible")
    raises(ContainerError, container.unpack, _reader(blob[:-5]))


def test_container_size_matches_pack():
    blob = container.pack("payload", compress=False)
    header = container.parse_preamble(blob)
    assert container.container_size(len(b"payload"), header.flags, 0) == len(blob)


def test_encryption_roundtrip():
    if not crypto.available():
        skip("needs the cryptography package")
    message = "a secret message"
    payload, header, blob = roundtrip(message, password="correct-password")
    assert payload.decode() == message
    assert header.encrypted
    assert message.encode() not in blob


def test_wrong_password_rejected():
    if not crypto.available():
        skip("needs the cryptography package")
    blob = container.pack("secret", password="correct")
    raises(CryptoError, container.unpack, _reader(blob), password="wrong")


def test_password_required():
    if not crypto.available():
        skip("needs the cryptography package")
    blob = container.pack("secret", password="pw")
    raises(CryptoError, container.unpack, _reader(blob))


def test_ecc_roundtrip_and_repair():
    if not ecc.available():
        skip("needs the reedsolo package")
    message = "a message protected by error correction " * 3
    blob = bytearray(container.pack(message, ecc_nsym=16))
    for i in range(container.PREAMBLE_LEN + 2, container.PREAMBLE_LEN + 8):
        blob[i] ^= 0xFF  # six damaged bytes, well within the RS limit
    payload, header = container.unpack(_reader(bytes(blob)))
    assert payload.decode("utf-8") == message
    assert header.has_ecc


def test_ecc_protects_the_preamble():
    if not ecc.available():
        skip("needs the reedsolo package")
    message = "the preamble itself must survive corruption"
    blob = bytearray(container.pack(message, ecc_nsym=16))
    blob[1] ^= 0xFF          # damage the magic
    blob[5] ^= 0xFF          # damage the flags
    payload, _ = container.unpack(_reader(bytes(blob)))
    assert payload.decode("utf-8") == message


def test_ecc_overhead_formula():
    if not ecc.available():
        skip("needs the reedsolo package")
    data = b"x" * 500
    assert len(ecc.encode(data, 16)) == ecc.encoded_len(len(data), 16)
    assert ecc.decode(ecc.encode(data, 16), 16, len(data)) == data
