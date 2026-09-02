"""stegolab - a research bench for image steganography and steganalysis.

Quick start::

    import stegolab as sl

    img = sl.read_image("cover.png")
    res = sl.embed(img, "secret", method="adaptive", key="my-key")
    sl.write_image("stego.png", res.stego)
    print(sl.extract(sl.read_image("stego.png"), method="adaptive", key="my-key"))

The desktop interface opens with ``python -m stegolab gui``.
"""

from .api import EmbedResult, capacity, embed, embed_file, extract, extract_file
from .codecs import CODECS, EmbedParams, codec_names, get_codec
from .exceptions import (
    CapacityError,
    ContainerError,
    CryptoError,
    DependencyError,
    StegoError,
)
from .image_io import read_image, write_image
from .maps import MAP_KINDS, complexity_map

__version__ = "0.3.0"

__all__ = [
    "__version__",
    "embed", "extract", "capacity", "embed_file", "extract_file", "EmbedResult",
    "read_image", "write_image",
    "CODECS", "codec_names", "get_codec", "EmbedParams",
    "complexity_map", "MAP_KINDS",
    "StegoError", "CapacityError", "ContainerError", "CryptoError",
    "DependencyError",
]
