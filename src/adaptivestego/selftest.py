"""Cross-platform determinism self-test.

The adaptive codecs rebuild the order of embedding positions from the image
itself. If two machines computed the complexity map even slightly differently,
the order would diverge and messages would stop decoding. Everything on that
path is therefore integer arithmetic - but "should be deterministic" is worth
very little without a way to check it.

Run ``python -m adaptivestego selftest`` on two machines and compare the digest.
Identical digests mean the two installations are interoperable.
"""

from __future__ import annotations

import hashlib
import platform
import sys

import numpy as np

from . import container
from .api import embed, embed_raw, extract, extract_raw
from .codecs import EmbedParams, codec_names, get_codec
from .maps import MAP_KINDS, complexity_map
from .prng import deterministic_bits, keyed_permutation
from .testing import synthetic_cover

__all__ = ["DIGEST_VERSION", "EXPECTED_DIGEST", "component_digests",
           "run_selftest", "environment"]

# Bump this whenever the reference vectors below are intentionally changed.
DIGEST_VERSION = 2

# Digest produced by a correct build. It is a property of the algorithms, not
# of the machine: any difference means the two installations would not be able
# to exchange stego images.
EXPECTED_DIGEST = "63f7a5cc7f006dde9bf500675083d81dadc3e86109d0236a1b80177e9b229293"

_KEY = "adaptivestego-selftest"
_MESSAGE = "adaptivestego determinism vector 0123456789"
_RAW_BITS = 4096


def _hash(*arrays: np.ndarray) -> str:
    digest = hashlib.sha256()
    for arr in arrays:
        arr = np.ascontiguousarray(arr)
        digest.update(str(arr.dtype).encode())
        digest.update(str(arr.shape).encode())
        digest.update(arr.tobytes())
    return digest.hexdigest()


def component_digests() -> dict[str, str]:
    """Digest of every deterministic building block, keyed by component name."""
    cover = synthetic_cover(128, 128, seed=17)
    gray = synthetic_cover(96, 96, seed=5, channels=1)
    out: dict[str, str] = {"cover": _hash(cover), "cover_gray": _hash(gray)}

    for kind in MAP_KINDS:
        out[f"map/{kind}"] = _hash(complexity_map(cover, kind, mask_bits=1))

    out["prng/permutation"] = _hash(keyed_permutation(10_000, _KEY))

    params = EmbedParams(key=_KEY)
    for name in codec_names():
        out[f"positions/{name}"] = _hash(get_codec(name).positions(cover, params))

    out["container"] = hashlib.sha256(
        container.pack(_MESSAGE, compress=True)).hexdigest()

    for name in codec_names():
        out[f"stego/{name}"] = _hash(_stego_for(cover, name))
    return out


def _stego_for(cover: np.ndarray, name: str) -> np.ndarray:
    """One stego image per method, using whichever payload form it supports."""
    if get_codec(name).syndrome_coded:
        payload = deterministic_bits(_KEY, "selftest/payload", _RAW_BITS)
        return embed_raw(cover, payload, method=name, key=_KEY).stego
    return embed(cover, _MESSAGE, method=name, key=_KEY).stego


def overall_digest(components: dict[str, str] | None = None) -> str:
    """Single digest that summarises every component."""
    components = components or component_digests()
    digest = hashlib.sha256()
    digest.update(f"adaptivestego/selftest/v{DIGEST_VERSION}".encode())
    for name in sorted(components):
        digest.update(name.encode())
        digest.update(components[name].encode())
    return digest.hexdigest()


def environment() -> dict[str, str]:
    """Versions that could plausibly influence the numerical results."""
    import cv2

    return {
        "python": sys.version.split()[0],
        "numpy": np.__version__,
        "opencv": cv2.__version__,
        "platform": platform.platform(),
        "machine": platform.machine(),
    }


def run_selftest(verbose: bool = True) -> dict:
    """Check round-trips and reproducibility. Returns a report dictionary."""
    problems: list[str] = []

    cover = synthetic_cover(128, 128, seed=17)
    for name in codec_names():
        try:
            if get_codec(name).syndrome_coded:
                payload = deterministic_bits(_KEY, "selftest/payload", _RAW_BITS)
                stego = embed_raw(cover, payload, method=name, key=_KEY).stego
                recovered = extract_raw(stego, _RAW_BITS, method=name, key=_KEY)
                if not np.array_equal(recovered, payload):
                    problems.append(f"{name}: round-trip returned different bits")
            else:
                res = embed(cover, _MESSAGE, method=name, key=_KEY)
                if extract(res.stego, method=name, key=_KEY) != _MESSAGE:
                    problems.append(f"{name}: round-trip returned a different message")
        except Exception as exc:                      # noqa: BLE001 - reported
            problems.append(f"{name}: {type(exc).__name__}: {exc}")

    components = component_digests()
    digest = overall_digest(components)
    matches = digest == EXPECTED_DIGEST
    if not matches:
        problems.append("digest differs from the reference value")

    report = {
        "digest": digest,
        "expected": EXPECTED_DIGEST,
        "digest_matches": matches,
        "digest_version": DIGEST_VERSION,
        "round_trips_ok": not any(": " in p and "round-trip" in p for p in problems),
        "problems": problems,
        "environment": environment(),
        "components": components,
    }

    if verbose:
        env = report["environment"]
        print(f"python {env['python']}  numpy {env['numpy']}  "
              f"opencv {env['opencv']}")
        print(f"platform {env['platform']} ({env['machine']})")
        print(f"methods checked: {', '.join(codec_names())}")
        print(f"digest   {digest}")
        print(f"expected {EXPECTED_DIGEST}")
        if matches and not problems:
            print("OK: this installation is interoperable with the reference build")
        else:
            for problem in problems:
                print(f"PROBLEM: {problem}")
            if not matches:
                print("Stego images produced here may not decode elsewhere.")
                print("Differing components:")
                for name in sorted(components):
                    print(f"  {name}: {components[name][:16]}")
    return report
