#!/usr/bin/env python3
"""Compare the ported cost models against the reference MATLAB output.

    python experiments/make_cost_vectors.py     # once, writes the test images
    matlab -batch "run('matlab/dump_reference_costs.m')"
    python experiments/validate_costs.py

A port of a published cost function is only worth as much as its agreement
with the original. Claiming "we beat S-UNIWARD" while running a subtly wrong
S-UNIWARD is the easiest way to publish something false, so this comparison
comes before any experiment that uses these models.

Once the reference files exist they are committed, and
tests/test_cost_models.py re-runs the comparison in CI without MATLAB.
"""

from __future__ import annotations

import argparse
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from adaptivestego.cost_models import WET, costs_for  # noqa: E402
from adaptivestego.image_io import read_image  # noqa: E402

VECTOR_DIR = os.path.join(ROOT, "tests", "data", "cost_vectors")
MODELS = ("wow", "uniward")


def load_reference(path: str, shape: tuple[int, int]) -> np.ndarray:
    """Read a float64 matrix written by the MATLAB driver."""
    data = np.fromfile(path, dtype=np.float64)
    if data.size != shape[0] * shape[1]:
        raise ValueError(
            f"{os.path.basename(path)} holds {data.size} values, expected "
            f"{shape[0] * shape[1]} for a {shape[0]}x{shape[1]} image")
    return data.reshape(shape)


def compare(ported: np.ndarray, reference: np.ndarray) -> dict:
    """Relative agreement, ignoring the shared wet entries."""
    wet_ported = ported >= WET
    wet_reference = reference >= WET
    wet_agree = bool(np.array_equal(wet_ported, wet_reference))

    live = ~(wet_ported | wet_reference)
    if not live.any():
        return {"max_relative": 0.0, "max_absolute": 0.0, "wet_agree": wet_agree,
                "n_live": 0}

    difference = np.abs(ported[live] - reference[live])
    scale = np.maximum(np.abs(reference[live]), 1e-12)
    return {
        "max_relative": float((difference / scale).max()),
        "max_absolute": float(difference.max()),
        "wet_agree": wet_agree,
        "n_live": int(live.sum()),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tolerance", type=float, default=1e-9,
                        help="largest acceptable relative difference")
    parser.add_argument("--vectors", default=VECTOR_DIR)
    args = parser.parse_args(argv)

    images = sorted(name for name in os.listdir(args.vectors)
                    if name.endswith(".pgm"))
    if not images:
        raise SystemExit(f"no test images in {args.vectors}; "
                         f"run experiments/make_cost_vectors.py first")

    checked, missing, failures = 0, [], []
    print(f"{'image':<12}{'model':<10}{'direction':<11}"
          f"{'max rel':>12}{'max abs':>12}  wet")
    for name in images:
        stem = os.path.splitext(name)[0]
        cover = read_image(os.path.join(args.vectors, name), grayscale=True)

        for model in MODELS:
            up, down = costs_for(cover, model)
            for direction, ported in (("up", up), ("down", down)):
                path = os.path.join(args.vectors, f"{stem}.{model}.{direction}.f64")
                if not os.path.isfile(path):
                    missing.append(os.path.basename(path))
                    continue

                report = compare(ported, load_reference(path, cover.shape))
                checked += 1
                ok = report["max_relative"] <= args.tolerance and report["wet_agree"]
                if not ok:
                    failures.append((stem, model, direction, report))
                print(f"{stem:<12}{model:<10}{direction:<11}"
                      f"{report['max_relative']:12.3e}{report['max_absolute']:12.3e}"
                      f"  {'ok' if report['wet_agree'] else 'MISMATCH'}")

    print()
    if missing:
        print(f"{len(missing)} reference files are missing, for example "
              f"{missing[0]}.")
        print("Run matlab/dump_reference_costs.m to produce them.")
        if not checked:
            return 2

    if failures:
        print(f"{len(failures)} of {checked} comparisons exceed the tolerance "
              f"of {args.tolerance:g}:")
        for stem, model, direction, report in failures:
            print(f"  {stem}/{model}/{direction}: relative "
                  f"{report['max_relative']:.3e}, wet map "
                  f"{'agrees' if report['wet_agree'] else 'differs'}")
        return 1

    print(f"all {checked} comparisons agree within {args.tolerance:g}")
    print("The reference files can now be committed; the test suite will keep "
          "checking the port against them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
