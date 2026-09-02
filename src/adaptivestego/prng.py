"""Deterministic keyed pseudo-random generator used to place message bits.

Requirement: the sequence must be identical on every machine and with every
version of numpy. Otherwise stego images produced today would stop decoding
after a library upgrade.

Only the raw stream of the Philox bit generator is used (its algorithm is
fixed by specification), and the permutation itself is built by our own code
rather than by ``numpy.random.Generator`` methods, whose algorithms are
explicitly allowed to change between releases.
"""

from __future__ import annotations

import hashlib
import hmac

import numpy as np

__all__ = ["derive_stream", "keyed_uniform_u64", "keyed_permutation",
           "stable_argsort_prefix", "deterministic_bytes", "deterministic_bits",
           "normalize_key"]

_DOMAIN = b"adaptivestego/v1/"


def normalize_key(key) -> bytes:
    """Coerce a key (str, bytes or None) into bytes. None means an empty key."""
    if key is None:
        return b""
    if isinstance(key, bytes):
        return key
    if isinstance(key, str):
        return key.encode("utf-8")
    raise TypeError(f"key must be str, bytes or None, got {type(key)!r}")


def derive_stream(key, tag: str) -> np.random.Philox:
    """Create a Philox generator deterministically derived from key and tag."""
    material = hmac.new(normalize_key(key), _DOMAIN + tag.encode("utf-8"),
                        hashlib.sha256).digest()
    counter = np.frombuffer(material, dtype="<u8").copy()  # four uint64 words
    return np.random.Philox(key=12345, counter=counter)


def keyed_uniform_u64(n: int, key, tag: str) -> np.ndarray:
    """Return n pseudo-random uint64 values, reproducible from (key, tag)."""
    if n <= 0:
        return np.empty(0, dtype=np.uint64)
    return derive_stream(key, tag).random_raw(n)


def stable_argsort_prefix(values: np.ndarray, k: int) -> np.ndarray:
    """First k indices of ``np.argsort(values, kind="stable")``.

    Selecting the k smallest values costs O(n) instead of the O(n log n) of a
    full sort, which matters when a short message is hidden in a large image.
    Ties are resolved exactly as a stable sort would resolve them, so the
    result is the true prefix of the full ordering and not an approximation.
    """
    n = values.size
    if k >= n:
        return np.argsort(values, kind="stable").astype(np.int64)
    if k <= 0:
        return np.empty(0, dtype=np.int64)

    pivot = values[np.argpartition(values, k - 1)[k - 1]]
    lower = np.flatnonzero(values < pivot)          # always fewer than k items
    equal = np.flatnonzero(values == pivot)
    chosen = np.concatenate([lower, equal[:k - lower.size]])
    chosen.sort()                                   # restore index order for ties
    return chosen[np.argsort(values[chosen], kind="stable")].astype(np.int64)


def keyed_permutation(n: int, key, tag: str = "positions",
                      limit: int | None = None) -> np.ndarray:
    """Keyed permutation of the indices 0..n-1.

    Implemented as a stable argsort over pseudo-random 64-bit labels: this
    operation is fully specified and does not depend on the internals of
    ``numpy.random.Generator``. With ``limit`` only the first ``limit`` entries
    are produced, which is exactly the prefix of the full permutation.
    """
    if n <= 0:
        return np.empty(0, dtype=np.int64)
    marks = keyed_uniform_u64(n, key, tag)
    if limit is None or limit >= n:
        return np.argsort(marks, kind="stable").astype(np.int64)
    return stable_argsort_prefix(marks, limit)


def deterministic_bytes(key, tag: str, n: int) -> bytes:
    """n pseudo-random bytes, reproducible from (key, tag) on any machine.

    Used to generate experiment payloads. ``numpy.random.Generator`` is not
    suitable here: its methods may change between releases, which would make a
    published dataset impossible to regenerate. The Philox stream is written
    out little-endian explicitly so the result does not depend on the byte
    order of the machine either.
    """
    if n <= 0:
        return b""
    words = derive_stream(key, tag).random_raw((n + 7) // 8)
    return words.astype("<u8").tobytes()[:n]


def deterministic_bits(key, tag: str, n_bits: int) -> np.ndarray:
    """n_bits pseudo-random bits as a uint8 array of zeros and ones."""
    if n_bits <= 0:
        return np.empty(0, dtype=np.uint8)
    raw = np.frombuffer(deterministic_bytes(key, tag, (n_bits + 7) // 8),
                        dtype=np.uint8)
    return np.unpackbits(raw)[:n_bits].copy()
