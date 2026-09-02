#!/usr/bin/env python3
"""Write the test images used to validate the cost model ports.

The images are deterministic and small, and they are committed to the
repository, so the comparison against the reference MATLAB implementation can
be repeated by anyone.

    python experiments/make_cost_vectors.py

Then run matlab/dump_reference_costs.m and experiments/validate_costs.py.
"""

from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

from adaptivestego.image_io import write_image  # noqa: E402
from adaptivestego.testing import synthetic_cover  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VECTOR_DIR = os.path.join(ROOT, "tests", "data", "cost_vectors")


def vectors() -> dict[str, np.ndarray]:
    """The images, each chosen to exercise a different part of the models."""
    smooth = synthetic_cover(64, 64, seed=1, channels=1)

    # Saturated regions: both wet directions must appear in the reference.
    saturated = synthetic_cover(64, 64, seed=7, channels=1).copy()
    saturated[:8, :8] = 0
    saturated[:8, 56:] = 255
    saturated[40, 40] = 0
    saturated[41, 41] = 255

    # Hard edges and perfectly flat areas: the extremes of the cost range,
    # and the place where a reciprocal Holder norm can divide by zero.
    edges = np.full((64, 64), 128, dtype=np.uint8)
    edges[:, 32:] = 200
    edges[16:48, 16:48] = 60
    edges[24:40, 24:40] = 255

    # A little noise, so nothing is exactly constant everywhere.
    rng = np.random.default_rng(11)
    noisy = np.clip(rng.normal(128, 12, (48, 80)), 0, 255).astype(np.uint8)

    return {"smooth": smooth, "saturated": saturated, "edges": edges,
            "noisy": noisy}


def main() -> int:
    os.makedirs(VECTOR_DIR, exist_ok=True)
    for name, image in vectors().items():
        path = os.path.join(VECTOR_DIR, f"{name}.pgm")
        write_image(path, image)
        print(f"{path}  {image.shape}  min={image.min()} max={image.max()}")
    print(f"\n{len(vectors())} vectors in {VECTOR_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
