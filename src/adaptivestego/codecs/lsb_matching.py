"""LSB matching (+/-1 embedding) with keyed random placement.

Unlike LSB replacement it does not lock sample values into the pairs
(2k, 2k+1). Chi-square, RS analysis and SPA are all built on that structure,
so they are not designed to detect this method and say very little about it -
which is not the same as the method being undetectable. Modern feature-based
and neural detectors target it directly.
"""

from __future__ import annotations

from .random_lsb import RandomLSB


class LSBMatching(RandomLSB):
    """Keyed placement combined with +/-1 modification."""

    name = "matching"
    default_mode = "match"
