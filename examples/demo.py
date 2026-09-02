#!/usr/bin/env python3
"""Show where each method puts the bits of a message.

    python examples/demo.py [--cover path.png] [--out examples]

Creates a cover image (or takes the given one), hides the same message with
every method and saves a map of the modified samples for each of them. The
difference is easy to see: sequential LSB fills the image from the top
regardless of its content, while the adaptive methods follow the edges and
textures and leave flat areas alone.
"""

from __future__ import annotations

import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

import adaptivestego as sl  # noqa: E402
from adaptivestego import analysis, metrics  # noqa: E402
from adaptivestego.testing import synthetic_cover  # noqa: E402

METHODS = ["sequential", "random", "matching", "edge", "adaptive",
           "adaptive-matching"]


def change_map(cover: np.ndarray, stego: np.ndarray) -> np.ndarray:
    """Black and white map: white marks the pixels that were modified."""
    diff = np.any(cover != stego, axis=2) if cover.ndim == 3 else cover != stego
    return (diff.astype(np.uint8) * 255)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cover", help="your own cover (synthetic by default)")
    parser.add_argument("--out", default="examples", help="output directory")
    parser.add_argument("--bpp", type=float, default=0.2,
                        help="payload in bits per pixel")
    parser.add_argument("--key", default="demo-key")
    args = parser.parse_args(argv)

    os.makedirs(args.out, exist_ok=True)
    if args.cover:
        cover = sl.read_image(args.cover)
    else:
        cover = synthetic_cover(320, 320, seed=3)
        sl.write_image(os.path.join(args.out, "cover.png"), cover)

    n_pixels = cover.shape[0] * cover.shape[1]
    n_bytes = max(int(n_pixels * args.bpp / 8) - 64, 1)
    message = bytes(np.random.default_rng(0).integers(0, 256, n_bytes, dtype=np.uint8))

    print(f"cover {cover.shape}, message {n_bytes} B "
          f"(about {args.bpp} bits per pixel), key {args.key!r}")
    print(f"clean cover: SPA={analysis.sample_pair_analysis(cover):.4f}")
    print(f"\n{'method':18s} {'PSNR':>7s} {'SSIM':>8s} {'SPA':>7s} "
          f"{'changed':>9s}  recovered")

    for method in METHODS:
        result = sl.embed(cover, message, method=method, key=args.key,
                          compress=False)
        recovered = sl.extract(result.stego, method=method, key=args.key,
                               as_text=False) == message
        sl.write_image(os.path.join(args.out, f"stego-{method}.png"), result.stego)
        sl.write_image(os.path.join(args.out, f"changes-{method}.png"),
                       change_map(cover, result.stego))
        print(f"{method:18s} {metrics.psnr(cover, result.stego):7.2f} "
              f"{metrics.ssim(cover, result.stego):8.5f} "
              f"{analysis.sample_pair_analysis(result.stego):7.4f} "
              f"{result.change_rate:9.4f}  {'yes' if recovered else 'NO'}")

    print(f"\nchange maps: {os.path.join(args.out, 'changes-*.png')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
