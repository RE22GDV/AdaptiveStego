"""LSB matching (+/-1 embedding) with keyed random placement.

Unlike LSB replacement it does not lock sample values into the pairs
(2k, 2k+1), so histogram attacks such as chi-square, RS and SPA do not apply.
"""

from __future__ import annotations

from .random_lsb import RandomLSB


class LSBMatching(RandomLSB):
    """Keyed placement combined with +/-1 modification."""

    name = "matching"
    default_mode = "match"
