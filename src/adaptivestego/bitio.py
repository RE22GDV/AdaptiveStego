"""Bit packing helpers: bytes to bit arrays and back (MSB first)."""

from __future__ import annotations

import numpy as np

__all__ = ["bytes_to_bits", "bits_to_bytes", "bits_capacity_bytes"]


def bytes_to_bits(data: bytes) -> np.ndarray:
    """Convert bytes into a uint8 array of bits, most significant bit first."""
    arr = np.frombuffer(data, dtype=np.uint8)
    return np.unpackbits(arr)


def bits_to_bytes(bits: np.ndarray) -> bytes:
    """Convert a uint8 bit array (MSB first) back into bytes.

    The number of bits must be a multiple of eight.
    """
    bits = np.asarray(bits, dtype=np.uint8)
    if bits.size % 8:
        raise ValueError(f"bit count ({bits.size}) is not a multiple of 8")
    return np.packbits(bits).tobytes()


def bits_capacity_bytes(n_bits: int) -> int:
    """How many whole bytes fit into n_bits."""
    return n_bits // 8
