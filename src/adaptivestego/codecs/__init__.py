"""Registry of embedding codecs."""

from __future__ import annotations

from .adaptive_lsb import AdaptiveLSB, AdaptiveMatching, EdgeAdaptiveLSB
from .base import Codec, EmbedParams
from .lsb_matching import LSBMatching
from .random_lsb import RandomLSB
from .sequential_lsb import SequentialLSB
from .stc_lsb import StcLSB, UniwardSTC, WowSTC

_CLASSES = (SequentialLSB, RandomLSB, LSBMatching, EdgeAdaptiveLSB,
            AdaptiveLSB, AdaptiveMatching, StcLSB, WowSTC, UniwardSTC)

CODECS = {cls.name: cls for cls in _CLASSES}

__all__ = ["Codec", "EmbedParams", "CODECS", "get_codec", "codec_names",
           "SequentialLSB", "RandomLSB", "LSBMatching", "AdaptiveLSB",
           "EdgeAdaptiveLSB", "AdaptiveMatching", "StcLSB", "WowSTC",
           "UniwardSTC"]


def codec_names() -> list[str]:
    """Names of every registered codec, in presentation order."""
    return list(CODECS)


def get_codec(name: str) -> Codec:
    """Instantiate a codec by name."""
    try:
        return CODECS[name]()
    except KeyError:
        raise ValueError(
            f"unknown method {name!r}; available: {', '.join(CODECS)}") from None
