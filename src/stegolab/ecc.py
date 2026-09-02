"""Reed-Solomon error correction, used to survive light image distortions.

The payload is split into blocks of ``DATA_CHUNK`` bytes and ``nsym`` parity
symbols are appended to each one, which repairs up to nsym/2 corrupted bytes
per block. The ``reedsolo`` package is an optional dependency.
"""

from __future__ import annotations

from .exceptions import ContainerError, DependencyError

__all__ = ["DATA_CHUNK", "available", "encode", "decode", "encoded_len",
           "encode_block", "decode_block"]

DATA_CHUNK = 223  # 223 + nsym <= 255


def available() -> bool:
    """Whether the optional ``reedsolo`` package is installed."""
    try:
        import reedsolo  # noqa: F401
    except ImportError:
        return False
    return True


def _codec(nsym: int):
    try:
        import reedsolo
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise DependencyError(
            "error correction requires the `reedsolo` package: pip install reedsolo"
        ) from exc
    return reedsolo.RSCodec(nsym)


def encoded_len(n_data: int, nsym: int) -> int:
    """Length of the encoded stream for n_data bytes of data."""
    if nsym <= 0:
        return n_data
    n_chunks = (n_data + DATA_CHUNK - 1) // DATA_CHUNK
    return n_chunks * (DATA_CHUNK + nsym)


def encode(data: bytes, nsym: int) -> bytes:
    """Encode data in fixed-size blocks; the final block is zero padded."""
    if nsym <= 0:
        return data
    rs = _codec(nsym)
    out = bytearray()
    for off in range(0, max(len(data), 1), DATA_CHUNK):
        chunk = data[off:off + DATA_CHUNK]
        chunk = chunk + b"\x00" * (DATA_CHUNK - len(chunk))
        out += bytes(rs.encode(chunk))
    return bytes(out)


def decode(stream: bytes, nsym: int, n_data: int) -> bytes:
    """Decode a stream produced by :func:`encode` and return n_data bytes."""
    if nsym <= 0:
        return stream[:n_data]
    rs = _codec(nsym)
    block = DATA_CHUNK + nsym
    out = bytearray()
    for off in range(0, len(stream), block):
        chunk = stream[off:off + block]
        if len(chunk) < block:
            break
        try:
            out += bytes(rs.decode(chunk)[0])
        except Exception as exc:
            raise ContainerError(
                "error correction failed: too many corrupted bytes in a block"
            ) from exc
    if len(out) < n_data:
        raise ContainerError("encoded stream is shorter than the declared length")
    return bytes(out[:n_data])


def encode_block(data: bytes, nsym: int) -> bytes:
    """Encode a short block (at most 255-nsym bytes) without zero padding."""
    if nsym <= 0:
        return data
    if len(data) > 255 - nsym:
        raise ValueError("block is longer than 255-nsym bytes")
    return bytes(_codec(nsym).encode(data))


def decode_block(block: bytes, nsym: int) -> bytes:
    """Decode a short block produced by :func:`encode_block`."""
    if nsym <= 0:
        return block
    try:
        return bytes(_codec(nsym).decode(block)[0])
    except Exception as exc:
        raise ContainerError("error correction failed for the header block") from exc
