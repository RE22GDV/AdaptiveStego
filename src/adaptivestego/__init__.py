"""AdaptiveStego - a research bench for image steganography and steganalysis.

Quick start::

    import adaptivestego as sl

    img = sl.read_image("cover.png")
    res = sl.embed(img, "secret", method="adaptive", key="my-key")
    sl.write_image("stego.png", res.stego)
    print(sl.extract(sl.read_image("stego.png"), method="adaptive", key="my-key"))

The desktop interface opens with ``python -m adaptivestego gui``.
"""

from . import analysis, container, forensics
from .api import (
    EmbedResult,
    capacity,
    detect,
    detect_file,
    embed,
    embed_file,
    embed_raw,
    extract,
    extract_file,
    extract_raw,
    payload_bits_for_bpp,
    scan,
)
from .codecs import CODECS, EmbedParams, codec_names, get_codec
from .exceptions import (
    CapacityError,
    ContainerError,
    CryptoError,
    DependencyError,
    PasswordRequired,
    StegoError,
)
from .image_io import read_image, write_image
from .maps import MAP_KINDS, complexity_map

__version__ = "0.4.0"

__all__ = [
    "__version__", "container", "analysis", "forensics",
    "embed", "extract", "capacity", "embed_file", "extract_file", "EmbedResult",
    "detect", "detect_file", "scan",
    "embed_raw", "extract_raw", "payload_bits_for_bpp",
    "read_image", "write_image",
    "CODECS", "codec_names", "get_codec", "EmbedParams",
    "complexity_map", "MAP_KINDS",
    "StegoError", "CapacityError", "ContainerError", "CryptoError",
    "DependencyError", "PasswordRequired",
]
