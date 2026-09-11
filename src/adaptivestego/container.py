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

The password itself never enters the image in any mode. What does travel with
an encrypted message by default is its *key material*: the ENCRYPTED flag, the
scrypt salt and the GCM nonce, which together announce "this is encrypted" to
anyone who parses the container. ``store_key_material=False`` removes all
three - the salt and the nonce are then derived from the password and from the
header fields instead, and the container is byte-for-byte shaped like an
unencrypted one. See docs/security.md for what that changes.

All multi-byte fields are big endian.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

from . import crypto, ecc
from .exceptions import ContainerError, CryptoError, PasswordRequired

__all__ = ["MAGIC", "VERSION", "FLAG_COMPRESSED", "FLAG_ENCRYPTED", "FLAG_ECC",
           "PREAMBLE_LEN", "PREAMBLE_ECC_NSYM", "Header", "Probe", "pack",
           "unpack", "probe", "container_size", "overhead", "max_message_bytes",
           "parse_preamble"]

MAGIC = b"ASG1"
VERSION = 1

FLAG_COMPRESSED = 0b0000_0001
FLAG_ENCRYPTED = 0b0000_0010
FLAG_ECC = 0b0000_0100

PREAMBLE_LEN = 8
PREAMBLE_ECC_NSYM = 8   # fixed parity size for the preamble when ECC is on
BODY_BASE_LEN = 16
CRYPTO_EXTRA_LEN = crypto.SALT_LEN + crypto.NONCE_LEN  # 28

# Above this the payload is indistinguishable from random bytes, which is what
# ciphertext looks like. Used only to turn "this did not decode" into the more
# useful "this did not decode and looks encrypted". Entropy needs a sample to
# be measured on: a 27-byte payload cannot exceed log2(27) bits per byte no
# matter what it holds, so below _ENTROPY_MIN_BYTES the test is not asked.
_ENCRYPTED_ENTROPY = 7.5
_ENTROPY_MIN_BYTES = 256


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


@dataclass(frozen=True)
class Probe:
    """What can be learned about a container without opening it.

    ``encrypted`` is what the header says. ``encryption_suspected`` is the
    weaker statement made about a container that carries no key material and
    whose payload does not read as a message: that is what a container packed
    with ``store_key_material=False`` looks like from the outside, and it is
    also what damaged data looks like.
    """

    found: bool
    header: Header | None = None
    container_bytes: int = 0
    message_bytes: int = 0
    encrypted: bool = False
    encryption_suspected: bool = False
    needs_password: bool = False
    readable: bool = False
    payload_entropy: float = 0.0
    detail: str = ""

    def summary(self) -> dict:
        """A JSON-ready description, without the raw header object."""
        header = self.header
        return {
            "found": self.found,
            "container_bytes": self.container_bytes,
            "message_bytes": self.message_bytes,
            "compressed": bool(header.compressed) if header else False,
            "encrypted": self.encrypted,
            "encryption_suspected": self.encryption_suspected,
            "needs_password": self.needs_password,
            "readable": self.readable,
            "ecc_nsym": header.ecc_nsym if header else 0,
            "version": header.version if header else 0,
            "payload_entropy_bits": round(self.payload_entropy, 3),
            "detail": self.detail,
        }


def _preamble_check(head7: bytes) -> int:
    return zlib.crc32(head7) & 0xFF


def _body_len(flags: int) -> int:
    return BODY_BASE_LEN + (CRYPTO_EXTRA_LEN if flags & FLAG_ENCRYPTED else 0)


def _byte_entropy(data: bytes) -> float:
    """Shannon entropy of the byte histogram, in bits per byte."""
    if not data:
        return 0.0
    import numpy as np

    counts = np.bincount(np.frombuffer(data, dtype=np.uint8), minlength=256)
    p = counts[counts > 0] / float(len(data))
    return float(-(p * np.log2(p)).sum())


def _looks_encrypted(header: Header, payload: bytes) -> bool:
    """Whether an unreadable payload is consistent with derived-mode encryption.

    Two independent signs, because either one alone misses half the cases. The
    structural one is exact and works on a payload of any size: AES-GCM adds
    its 16-byte tag and nothing else, so an uncompressed container whose
    payload is exactly the stated message length plus a tag is very unlikely
    to be anything else. The statistical one covers the compressed case, where
    the payload length says nothing, but it needs enough bytes to measure.
    """
    if not header.compressed and len(payload) == header.plain_len + crypto.TAG_LEN:
        return True
    return (len(payload) >= _ENTROPY_MIN_BYTES
            and _byte_entropy(payload) >= _ENCRYPTED_ENTROPY)


def _derivation_context(flags: int, ecc_nsym: int, payload_len: int,
                        plain_len: int, plain_crc: int) -> bytes:
    """Context that pins derived key material to this particular message.

    Every field is one the receiver reads out of the header before it tries to
    decrypt, and together they must differ between any two messages sent under
    one password - see the note in crypto.py. Two messages of the same length
    collide only if their CRC32 also collides, which does not happen by
    accident but can be arranged by someone who chooses the plaintexts.
    """
    return MAGIC + struct.pack(">BBBIII", VERSION, flags, ecc_nsym,
                               payload_len, plain_len, plain_crc)


def pack(message, *, password=None, compress: bool = True, ecc_nsym: int = 0,
         store_key_material: bool = True) -> bytes:
    """Build a container from a message given as str or bytes.

    With ``store_key_material=False`` the salt and the nonce are derived from
    the password rather than written into the header, and the ENCRYPTED flag
    stays clear, so nothing in the container reveals that a password was used.
    """
    if isinstance(message, str):
        plain = message.encode("utf-8")
    elif isinstance(message, (bytes, bytearray)):
        plain = bytes(message)
    else:
        raise TypeError("message must be str or bytes")

    if not store_key_material and password is None:
        raise ValueError(
            "store_key_material=False only applies to an encrypted container: "
            "there is no key material to leave out without a password")

    plain_crc = zlib.crc32(plain) & 0xFFFFFFFF
    payload = plain
    flags = 0

    if compress:
        packed = zlib.compress(plain, 9)
        if len(packed) < len(payload):
            payload = packed
            flags |= FLAG_COMPRESSED

    if ecc_nsym:
        if not 1 <= ecc_nsym <= 32:
            raise ValueError("ecc_nsym must be in the range 1..32")
        flags |= FLAG_ECC
    else:
        ecc_nsym = 0

    salt = nonce = b""
    kdf = 0
    if password is not None:
        kdf = crypto.KDF_SCRYPT
        if store_key_material:
            flags |= FLAG_ENCRYPTED
            salt, nonce, payload = crypto.encrypt(payload, password)
        else:
            # The context has to be built before the ciphertext exists, so it
            # uses the length the ciphertext is going to have: the plaintext
            # plus the GCM tag.
            context = _derivation_context(flags, ecc_nsym,
                                          len(payload) + crypto.TAG_LEN,
                                          len(plain), plain_crc)
            payload = crypto.encrypt_derived(payload, password, context)
            kdf = 0          # the kdf field would be a give-away of its own

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


def _shape(encrypted: bool, store_key_material: bool) -> tuple[int, int]:
    """(header flags, extra payload bytes) for the requested encryption mode."""
    if not encrypted:
        return 0, 0
    if store_key_material:
        return FLAG_ENCRYPTED, crypto.TAG_LEN
    return 0, crypto.TAG_LEN


def overhead(*, encrypted: bool = False, ecc_nsym: int = 0,
             store_key_material: bool = True) -> int:
    """Fixed overhead in bytes, excluding the ECC expansion of the payload.

    This is only the constant part. With error correction the payload itself
    also grows, and the final block is padded to a whole 223 bytes, so this
    number must not be used to work out the largest message that fits - use
    :func:`max_message_bytes` for that.
    """
    flags, tag = _shape(encrypted, store_key_material)
    return (PREAMBLE_LEN + (PREAMBLE_ECC_NSYM if ecc_nsym else 0)
            + _body_len(flags) + ecc_nsym + tag)


def max_message_bytes(capacity_bytes: int, *, encrypted: bool = False,
                      ecc_nsym: int = 0,
                      store_key_material: bool = True) -> int:
    """Largest message that still fits into ``capacity_bytes`` of container.

    Subtracting a fixed overhead is wrong once error correction is enabled:
    Reed-Solomon expands the payload block by block and pads the last block to
    a full 223 bytes, so the true limit is a step function. It is inverted here
    by binary search over :func:`container_size`, which is exact and monotone.

    Compression can only make the payload smaller, and :func:`pack` keeps the
    compressed form only when it is smaller, so the uncompressed size is the
    worst case and the answer is always safe.
    """
    flags, tag = _shape(encrypted, store_key_material)
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


def _read_container(read) -> tuple[Header, bytes]:
    """Read the header and the raw payload, without interpreting the payload.

    This is the detection half of extraction: it establishes that a container
    is there and what it claims about itself, which is knowable without a
    password.
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
    payload = ecc.decode(read(ecc.encoded_len(payload_len, nsym)), nsym,
                         payload_len)
    return header, payload


def _finish(header: Header, payload: bytes) -> bytes:
    """Decompress and check a payload that is already in the clear."""
    if header.compressed:
        try:
            payload = zlib.decompress(payload)
        except zlib.error as exc:
            raise ContainerError("zlib decompression failed") from exc

    if len(payload) != header.plain_len:
        raise ContainerError(
            f"length mismatch: expected {header.plain_len} bytes, got "
            f"{len(payload)}")
    if (zlib.crc32(payload) & 0xFFFFFFFF) != header.plain_crc32:
        raise ContainerError("message checksum mismatch (data was altered)")
    return payload


def _open_payload(header: Header, payload: bytes, password) -> bytes:
    """Turn a raw payload into the message, decrypting it when necessary.

    Three cases, and which one applies is decided here rather than by the
    caller: the header says encrypted, the header says nothing but a password
    was offered (so the key material may have been derived), or there is no
    encryption at all.
    """
    if header.encrypted:
        if password is None:
            raise PasswordRequired(
                "the message is encrypted: a password is required", certain=True)
        return _finish(header, crypto.decrypt(payload, password, header.salt,
                                              header.nonce))

    decryption_failed = False
    if password is not None:
        context = _derivation_context(header.flags, header.ecc_nsym,
                                      header.payload_len, header.plain_len,
                                      header.plain_crc32)
        try:
            return _finish(header, crypto.decrypt_derived(payload, password,
                                                          context))
        except CryptoError:
            # Either the password is wrong or this container was never
            # encrypted and the password is simply redundant. Reading it as
            # plaintext below settles which.
            decryption_failed = True

    try:
        return _finish(header, payload)
    except ContainerError:
        if decryption_failed:
            raise CryptoError(
                "decryption failed: wrong password, or the message was not "
                "encrypted and is damaged") from None
        if password is None and _looks_encrypted(header, payload):
            raise PasswordRequired(
                "a container is present but its payload does not read as a "
                "message and looks like ciphertext: it was probably packed "
                "with the key material derived from a password rather than "
                "stored. Supply the password.", certain=False) from None
        raise


def unpack(read, *, password=None) -> tuple[bytes, Header]:
    """Read a container through a sequential ``read(n) -> bytes`` callable.

    Returns the original message bytes together with the parsed header.
    """
    header, payload = _read_container(read)
    return _open_payload(header, payload, password), header


def probe(read, *, password=None) -> Probe:
    """Report what is in the stream without requiring it to be readable.

    Never raises for a stream that simply holds no container: absence of a
    message is an answer, not an error.
    """
    try:
        header, payload = _read_container(read)
    except ContainerError as exc:
        return Probe(found=False, detail=str(exc))

    entropy = _byte_entropy(payload)
    size = container_size(header.payload_len, header.flags, header.ecc_nsym)
    common = {
        "found": True,
        "header": header,
        "container_bytes": size,
        "message_bytes": header.plain_len,
        "encrypted": header.encrypted,
        "payload_entropy": entropy,
    }

    try:
        _open_payload(header, payload, password)
    except PasswordRequired as exc:
        return Probe(**common, needs_password=True,
                     encryption_suspected=not exc.certain, detail=str(exc))
    except (CryptoError, ContainerError) as exc:
        return Probe(**common, needs_password=header.encrypted,
                     encryption_suspected=(not header.encrypted
                                           and _looks_encrypted(header, payload)),
                     detail=str(exc))
    return Probe(**common, readable=True, detail="the message was read in full")
