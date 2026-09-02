"""Payload encryption: scrypt key derivation plus AES-256-GCM.

Confidentiality and integrity come from the AEAD cipher, not from the fact
that the container is hidden: steganography conceals that a message was sent,
cryptography protects what it says. Neither replaces the other.

The ``cryptography`` package is an optional dependency. Without it every
embedding method still works, only ``--password`` is unavailable.
"""

from __future__ import annotations

import os

from .exceptions import CryptoError, DependencyError

__all__ = ["KDF_SCRYPT", "SALT_LEN", "NONCE_LEN", "TAG_LEN",
           "derive_key", "encrypt", "decrypt", "available"]

KDF_SCRYPT = 1

SALT_LEN = 16
NONCE_LEN = 12
TAG_LEN = 16

# scrypt cost parameters: about 64 MiB of memory, a few tenths of a second.
SCRYPT_N = 2 ** 16
SCRYPT_R = 8
SCRYPT_P = 1
KEY_LEN = 32
# OpenSSL caps scrypt at 32 MiB by default while N=2^16, r=8 needs 64 MiB,
# so the limit has to be raised explicitly.
SCRYPT_MAXMEM = 192 * 1024 * 1024


def available() -> bool:
    """Whether the optional ``cryptography`` package is installed."""
    try:
        import cryptography  # noqa: F401
    except ImportError:
        return False
    return True


def _aesgcm():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise DependencyError(
            "encryption requires the `cryptography` package: "
            "pip install cryptography"
        ) from exc
    return AESGCM


def derive_key(password, salt: bytes, kdf: int = KDF_SCRYPT) -> bytes:
    """Derive a 32-byte key from a password using scrypt from the stdlib."""
    import hashlib

    if kdf != KDF_SCRYPT:
        raise CryptoError(f"unknown key derivation function id: {kdf}")
    if password is None:
        password = b""
    if isinstance(password, str):
        password = password.encode("utf-8")
    return hashlib.scrypt(password, salt=salt, n=SCRYPT_N, r=SCRYPT_R,
                          p=SCRYPT_P, maxmem=SCRYPT_MAXMEM, dklen=KEY_LEN)


def encrypt(plaintext: bytes, password, aad: bytes = b"") -> tuple[bytes, bytes, bytes]:
    """Encrypt a payload. Returns (salt, nonce, ciphertext-with-tag)."""
    aesgcm = _aesgcm()
    salt = os.urandom(SALT_LEN)
    nonce = os.urandom(NONCE_LEN)
    key = derive_key(password, salt)
    blob = aesgcm(key).encrypt(nonce, plaintext, aad)
    return salt, nonce, blob


def decrypt(blob: bytes, password, salt: bytes, nonce: bytes, aad: bytes = b"") -> bytes:
    """Decrypt a payload and verify its authentication tag."""
    aesgcm = _aesgcm()
    key = derive_key(password, salt)
    try:
        return aesgcm(key).decrypt(nonce, blob, aad)
    except Exception as exc:
        raise CryptoError(
            "decryption failed: wrong password or corrupted data"
        ) from exc
