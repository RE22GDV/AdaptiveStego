"""The ASG1 container format.

    +- preamble (8 bytes, ECC protected only when ECC is on) ---------------+
    | magic "ASG1" (4) | version (1) | flags (1) | ecc_nsym (1) | check (1) |
    +----------------------------------------------------------------------+
    +- header body (16 bytes, or 44 when encrypted; one RS block) ----------+
    | payload_len u32 | plain_len u32 | plain_crc32 u32 | kdf u8 | rsv (3)  |
    | [salt (16) | nonce (12)]  - present only when the ENCRYPTED flag is set|
    +----------------------------------------------------------------------+
    +- payload (RS blocks of 223 bytes when ECC is on) ---------------------+
    | message -> utf-8 -> [zlib] -> [AES-256-GCM] -> payload_len bytes      |
    +----------------------------------------------------------------------+

Four independent checks: the magic and version identify the format, the
preamble check byte catches header corruption, the CRC32 of the plaintext
catches data corruption, and the GCM tag proves authenticity and the password.

All multi-byte fields are big endian.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

from . import crypto, ecc
from .exceptions import ContainerError, CryptoError

__all__ = ["MAGIC", "VERSION", "FLAG_COMPRESSED", "FLAG_ENCRYPTED", "FLAG_ECC",
           "PREAMBLE_LEN", "PREAMBLE_ECC_NSYM", "Header", "pack", "unpack",
           "container_size", "overhead", "max_message_bytes", "parse_preamble"]

MAGIC = b"ASG1"
VERSION = 1

FLAG_COMPRESSED = 0b0000_0001
FLAG_ENCRYPTED = 0b0000_0010
FLAG_ECC = 0b0000_0100

PREAMBLE_LEN = 8
PREAMBLE_ECC_NSYM = 8   # fixed parity size for the preamble when ECC is on
BODY_BASE_LEN = 16
CRYPTO_EXTRA_LEN = crypto.SALT_LEN + crypto.NONCE_LEN  # 28


@dataclass(frozen=True)
class Header:
    """Parsed container header."""

    version: int
    flags: int
    ecc_nsym: int
    payload_len: int = 0
    plain_len: int = 0
    plain_crc32: int = 0
    kdf: int = 0
    salt: bytes = b""
    nonce: bytes = b""

    @property
    def compressed(self) -> bool:
        return bool(self.flags & FLAG_COMPRESSED)

    @property
    def encrypted(self) -> bool:
        return bool(self.flags & FLAG_ENCRYPTED)

    @property
    def has_ecc(self) -> bool:
        return bool(self.flags & FLAG_ECC)


def _preamble_check(head7: bytes) -> int:
    return zlib.crc32(head7) & 0xFF


def _body_len(flags: int) -> int:
    return BODY_BASE_LEN + (CRYPTO_EXTRA_LEN if flags & FLAG_ENCRYPTED else 0)


def pack(message, *, password=None, compress: bool = True,
         ecc_nsym: int = 0) -> bytes:
    """Build a container from a message given as str or bytes."""
    if isinstance(message, str):
        plain = message.encode("utf-8")
    elif isinstance(message, (bytes, bytearray)):
        plain = bytes(message)
    else:
        raise TypeError("message must be str or bytes")

    plain_crc = zlib.crc32(plain) & 0xFFFFFFFF
    payload = plain
    flags = 0

    if compress:
        packed = zlib.compress(plain, 9)
        if len(packed) < len(payload):
            payload = packed
            flags |= FLAG_COMPRESSED

    salt = nonce = b""
    kdf = 0
    if password is not None:
        salt, nonce, payload = crypto.encrypt(payload, password)
        kdf = crypto.KDF_SCRYPT
        flags |= FLAG_ENCRYPTED

    if ecc_nsym:
        if not 1 <= ecc_nsym <= 32:
            raise ValueError("ecc_nsym must be in the range 1..32")
        flags |= FLAG_ECC
    else:
        ecc_nsym = 0

    body = struct.pack(">IIIB3x", len(payload), len(plain), plain_crc, kdf)
    if flags & FLAG_ENCRYPTED:
        body += salt + nonce

    head7 = MAGIC + bytes([VERSION, flags, ecc_nsym])
    preamble = head7 + bytes([_preamble_check(head7)])
    if ecc_nsym:
        # Reed-Solomon is systematic, so the first PREAMBLE_LEN bytes of the
        # encoded block are still the preamble itself.
        preamble = ecc.encode_block(preamble, PREAMBLE_ECC_NSYM)

    return preamble + ecc.encode_block(body, ecc_nsym) + ecc.encode(payload, ecc_nsym)


def parse_preamble(raw: bytes) -> Header:
    """Parse the 8-byte preamble, raising ContainerError on any mismatch."""
    if len(raw) < PREAMBLE_LEN:
        raise ContainerError("not enough data for a preamble")
    if raw[:4] != MAGIC:
        raise ContainerError(
            "container signature not found: the image carries no message, or "
            "the method, key or parameters used for extraction do not match"
        )
    version, flags, ecc_nsym, check = raw[4], raw[5], raw[6], raw[7]
    if check != _preamble_check(raw[:7]):
        raise ContainerError("header is corrupted (check byte mismatch)")
    if version != VERSION:
        raise ContainerError(f"unsupported format version: {version}")
    return Header(version=version, flags=flags, ecc_nsym=ecc_nsym)


def container_size(payload_len: int, flags: int, ecc_nsym: int) -> int:
    """Total container size in bytes."""
    return (PREAMBLE_LEN + (PREAMBLE_ECC_NSYM if ecc_nsym else 0)
            + _body_len(flags) + ecc_nsym
            + ecc.encoded_len(payload_len, ecc_nsym))


def overhead(*, encrypted: bool = False, ecc_nsym: int = 0) -> int:
    """Fixed overhead in bytes, excluding the ECC expansion of the payload.

    This is only the constant part. With error correction the payload itself
    also grows, and the final block is padded to a whole 223 bytes, so this
    number must not be used to work out the largest message that fits - use
    :func:`max_message_bytes` for that.
    """
    flags = FLAG_ENCRYPTED if encrypted else 0
    tag = crypto.TAG_LEN if encrypted else 0
    return (PREAMBLE_LEN + (PREAMBLE_ECC_NSYM if ecc_nsym else 0)
            + _body_len(flags) + ecc_nsym + tag)


def max_message_bytes(capacity_bytes: int, *, encrypted: bool = False,
                      ecc_nsym: int = 0) -> int:
    """Largest message that still fits into ``capacity_bytes`` of container.

    Subtracting a fixed overhead is wrong once error correction is enabled:
    Reed-Solomon expands the payload block by block and pads the last block to
    a full 223 bytes, so the true limit is a step function. It is inverted here
    by binary search over :func:`container_size`, which is exact and monotone.

    Compression can only make the payload smaller, and :func:`pack` keeps the
    compressed form only when it is smaller, so the uncompressed size is the
    worst case and the answer is always safe.
    """
    flags = FLAG_ENCRYPTED if encrypted else 0
    tag = crypto.TAG_LEN if encrypted else 0
    if container_size(tag, flags, ecc_nsym) > capacity_bytes:
        return 0
    low, high = 0, int(capacity_bytes)
    while low < high:
        mid = (low + high + 1) // 2
        if container_size(mid + tag, flags, ecc_nsym) <= capacity_bytes:
            low = mid
        else:
            high = mid - 1
    return low


def _read_preamble(read) -> Header:
    """Read the preamble, repairing it through ECC when necessary."""
    raw = read(PREAMBLE_LEN)
    try:
        header = parse_preamble(raw)
    except ContainerError as first_error:
        try:
            parity = read(PREAMBLE_ECC_NSYM)
            repaired = ecc.decode_block(raw + parity, PREAMBLE_ECC_NSYM)
            return parse_preamble(repaired)
        except Exception:
            raise first_error from None
    if header.has_ecc:
        read(PREAMBLE_ECC_NSYM)      # parity bytes are not needed any more
    return header


def unpack(read, *, password=None) -> tuple[bytes, Header]:
    """Read a container through a sequential ``read(n) -> bytes`` callable.

    Returns the original message bytes together with the parsed header.
    """
    header = _read_preamble(read)
    nsym = header.ecc_nsym if header.has_ecc else 0

    body_len = _body_len(header.flags)
    body = ecc.decode_block(read(body_len + nsym), nsym)
    payload_len, plain_len, plain_crc, kdf = struct.unpack(
        ">IIIB3x", body[:BODY_BASE_LEN])

    salt = nonce = b""
    if header.encrypted:
        extra = body[BODY_BASE_LEN:BODY_BASE_LEN + CRYPTO_EXTRA_LEN]
        salt, nonce = extra[:crypto.SALT_LEN], extra[crypto.SALT_LEN:]

    header = Header(header.version, header.flags, nsym, payload_len, plain_len,
                    plain_crc, kdf, salt, nonce)

    payload = ecc.decode(read(ecc.encoded_len(payload_len, nsym)), nsym, payload_len)

    if header.encrypted:
        if password is None:
            raise CryptoError("the message is encrypted: a password is required")
        payload = crypto.decrypt(payload, password, salt, nonce)

    if header.compressed:
        try:
            payload = zlib.decompress(payload)
        except zlib.error as exc:
            raise ContainerError("zlib decompression failed") from exc

    if len(payload) != plain_len:
        raise ContainerError(
            f"length mismatch: expected {plain_len} bytes, got {len(payload)}")
    if (zlib.crc32(payload) & 0xFFFFFFFF) != plain_crc:
        raise ContainerError("message checksum mismatch (data was altered)")
    return payload, header
