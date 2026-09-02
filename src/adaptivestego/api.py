"""High-level API: message in, image out (and back again)."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np

from . import container, core
from .bitio import bits_to_bytes, bytes_to_bits
from .codecs import EmbedParams, get_codec
from .exceptions import CapacityError, ContainerError, StegoError
from .image_io import read_image, write_image

__all__ = ["EmbedResult", "capacity", "embed", "extract",
           "embed_file", "extract_file", "embed_raw", "extract_raw",
           "payload_bits_for_bpp"]

_PARAM_KEYS = ("bits_per_sample", "key", "map_kind", "band_bits", "mode",
               "channels", "map_mask_bits", "stc_height", "cost_gamma")

# Positions are computed in chunks; the first chunk must comfortably cover the
# container header so that a short message needs a single pass.
_MIN_POSITION_CHUNK = 4096


@dataclass
class EmbedResult:
    """Outcome of one embedding operation."""

    stego: np.ndarray
    method: str
    payload_bytes: int          # container size in bytes
    message_bytes: int          # size of the original message
    capacity_bytes: int
    bpp: float                  # bits per pixel actually used
    max_bpp: float              # capacity of the method, bits per pixel
    changed_samples: int
    change_rate: float          # fraction of image samples that changed
    payload_bits: int = 0       # bits actually written into the image
    raw: bool = False           # True when no container header was used

    def summary(self) -> dict:
        """Everything except the image itself, ready for JSON output."""
        data = asdict(self)
        data.pop("stego")
        return data


def _params(kw: dict) -> EmbedParams:
    known = {k: v for k, v in kw.items() if k in _PARAM_KEYS and v is not None}
    unknown = set(kw) - set(_PARAM_KEYS) - {"password", "ecc_nsym", "compress"}
    if unknown:
        raise TypeError(f"unknown parameters: {', '.join(sorted(unknown))}")
    return EmbedParams(**known)


def _prepare(img: np.ndarray, method: str, kw: dict):
    codec = get_codec(method)
    params = _params(kw)
    return codec, params, codec.candidate_count(img, params)


def _refuse_container(codec) -> None:
    """Syndrome coding cannot be read progressively, so it has no container.

    The ASG1 header is discovered by reading a prefix of the payload, but a
    syndrome is only defined once the whole payload length is known. Rather
    than silently producing something undecodable, say so.
    """
    if getattr(codec, "syndrome_coded", False):
        raise StegoError(
            f"method {codec.name!r} uses syndrome coding, which needs the "
            f"payload length in advance and therefore has no self-describing "
            f"container. Use embed_raw/extract_raw, or --mode research in the "
            f"experiment scripts.")


def capacity(img: np.ndarray, method: str = "adaptive", *, password=None,
             ecc_nsym: int = 0, **kw) -> dict:
    """Report how much data the given method can hide in this image."""
    _codec, params, n_samples = _prepare(img, method, kw)
    bits = core.capacity_bits(n_samples, params.bits_per_sample)
    n_pixels = img.shape[0] * img.shape[1]
    ecc_nsym = int(ecc_nsym or 0)
    fixed = container.overhead(encrypted=password is not None, ecc_nsym=ecc_nsym)
    usable = container.max_message_bytes(bits // 8,
                                         encrypted=password is not None,
                                         ecc_nsym=ecc_nsym)
    return {
        "method": method,
        "capacity_bits": bits,
        "capacity_bytes": bits // 8,
        "container_overhead_bytes": fixed,
        "message_bytes_max": usable,
        "bpp": bits / n_pixels,
        "n_pixels": n_pixels,
        "n_samples": int(img.size),
    }


def embed(img: np.ndarray, message, *, method: str = "adaptive", key=None,
          password=None, compress: bool = True, ecc_nsym: int = 0,
          **kw) -> EmbedResult:
    """Hide a message inside a uint8 image array."""
    codec, params, n_samples = _prepare(img, method, dict(kw, key=key))
    _refuse_container(codec)
    blob = container.pack(message, password=password, compress=compress,
                          ecc_nsym=ecc_nsym)
    bits = bytes_to_bits(blob)

    cap = core.capacity_bits(n_samples, params.bits_per_sample)
    if bits.size > cap:
        raise CapacityError(
            f"the container needs {len(blob)} B ({bits.size} bits) but method "
            f"{method!r} offers only {cap // 8} B ({cap} bits)")

    stego = codec.embed(img, bits, params)
    changed = int(np.count_nonzero(stego != img))
    n_pixels = img.shape[0] * img.shape[1]
    msg_len = len(message.encode("utf-8")) if isinstance(message, str) else len(message)
    return EmbedResult(
        stego=stego, method=method, payload_bytes=len(blob), message_bytes=msg_len,
        capacity_bytes=cap // 8, bpp=bits.size / n_pixels, max_bpp=cap / n_pixels,
        changed_samples=changed, change_rate=changed / img.size,
        payload_bits=int(bits.size), raw=False,
    )


# ---------------------------------------------------------------------------
# research mode
# ---------------------------------------------------------------------------
def payload_bits_for_bpp(img: np.ndarray, bpp: float) -> int:
    """Exact number of payload bits that corresponds to a payload in bpp."""
    return int(round(bpp * img.shape[0] * img.shape[1]))


def embed_raw(img: np.ndarray, bits, *, method: str = "adaptive", key=None,
              **kw) -> EmbedResult:
    """Embed exactly the given bits, with no container and no header.

    This is the mode to use when comparing embedding algorithms. The container
    of :func:`embed` carries a fixed signature, flags and checksums, and those
    constant bytes become part of the stego signal, which is an extra variable
    that has nothing to do with the algorithm under test. Here a payload of
    0.4 bpp means exactly 0.4 bits per pixel of message.

    The receiver must know the number of bits; nothing in the image says it.
    """
    codec, params, n_samples = _prepare(img, method, dict(kw, key=key))
    bits = np.asarray(bits, dtype=np.uint8).ravel()
    if bits.size and bits.max() > 1:
        raise ValueError("raw payload must be an array of bits (0 or 1)")

    cap = core.capacity_bits(n_samples, params.bits_per_sample)
    if bits.size > cap:
        raise CapacityError(
            f"the payload needs {bits.size} bits but method {method!r} offers "
            f"only {cap}")

    stego = codec.embed(img, bits, params)
    changed = int(np.count_nonzero(stego != img))
    n_pixels = img.shape[0] * img.shape[1]
    return EmbedResult(
        stego=stego, method=method, payload_bytes=(bits.size + 7) // 8,
        message_bytes=(bits.size + 7) // 8, capacity_bytes=cap // 8,
        bpp=bits.size / n_pixels, max_bpp=cap / n_pixels,
        changed_samples=changed, change_rate=changed / img.size,
        payload_bits=int(bits.size), raw=True,
    )


def extract_raw(img: np.ndarray, n_bits: int, *, method: str = "adaptive",
                key=None, **kw) -> np.ndarray:
    """Read exactly n_bits bits back out of a raw-mode stego image."""
    codec, params, n_samples = _prepare(img, method, dict(kw, key=key))
    cap = core.capacity_bits(n_samples, params.bits_per_sample)
    if n_bits > cap:
        raise CapacityError(
            f"{n_bits} bits requested but method {method!r} offers only {cap}")
    return codec.extract(img, int(n_bits), params)


def extract(img: np.ndarray, *, method: str = "adaptive", key=None,
            password=None, as_text: bool = True, **kw):
    """Recover a message from a stego image.

    The method, key, bits per sample and map settings must match the ones used
    for embedding: none of them are stored inside the image.

    Positions are produced lazily. The header is read from a small prefix, and
    only then are enough positions computed for the payload it announces, so a
    short message in a large image never orders the whole image.
    """
    codec, params, n_samples = _prepare(img, method, dict(kw, key=key))
    _refuse_container(codec)
    state: dict = {"off": 0, "limit": 0, "positions": None}

    def positions_for(samples: int) -> np.ndarray:
        if state["positions"] is None or samples > state["limit"]:
            limit = min(max(samples, _MIN_POSITION_CHUNK), n_samples)
            state["positions"] = codec.positions(img, params, limit=limit)
            state["limit"] = limit
        return state["positions"]

    def read(n: int) -> bytes:
        want_bits = (state["off"] + n) * 8
        needed = int(math.ceil(want_bits / params.bits_per_sample))
        if needed > n_samples:
            raise ContainerError(
                "the data ends early: the image does not hold a whole message")
        bits = core.extract_bits(img, positions_for(needed), want_bits,
                                 bits_per_sample=params.bits_per_sample)
        chunk = bits[state["off"] * 8:]
        state["off"] += n
        return bits_to_bytes(chunk)

    payload, _header = container.unpack(read, password=password)
    if as_text:
        try:
            return payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ContainerError(
                "the message is not valid UTF-8 (use as_text=False)"
            ) from exc
    return payload


def embed_file(cover_path: str, message, out_path: str, *,
               grayscale: bool = False, **kw) -> EmbedResult:
    """Read a cover image from disk, embed a message and write the result."""
    img = read_image(cover_path, grayscale=grayscale)
    res = embed(img, message, **kw)
    write_image(out_path, res.stego)
    return res


def extract_file(stego_path: str, *, grayscale: bool = False, **kw):
    """Read a stego image from disk and recover the message."""
    return extract(read_image(stego_path, grayscale=grayscale), **kw)
