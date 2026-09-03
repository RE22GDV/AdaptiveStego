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

from adaptivestego.cost_models import costs_for, wet_cost  # noqa: E402
from adaptivestego.image_io import read_image  # noqa: E402

VECTOR_DIR = os.path.join(ROOT, "tests", "data", "cost_vectors")
MODELS = ("wow", "uniward")

# Costs are compared after clamping here. Typical costs are between 0.01 and
# 100, so this changes nothing an embedder would act on, and above it the
# numbers carry no information: in a flat region the wavelet residual is zero
# up to cancellation, and the reciprocal Holder norm of WOW turns that into a
# cost of order 1e9 whose digits differ between builds of the same code. The
# meaningful statement about such a sample is only that both implementations
# consider it unusable, which clamping asserts.
COST_CAP = 1e3
STRICT_TOLERANCE = 1e-9


def load_reference(path: str, shape: tuple[int, int]) -> np.ndarray:
    """Read a float64 matrix written by the MATLAB driver."""
    data = np.fromfile(path, dtype=np.float64)
    if data.size != shape[0] * shape[1]:
        raise ValueError(
            f"{os.path.basename(path)} holds {data.size} values, expected "
            f"{shape[0] * shape[1]} for a {shape[0]}x{shape[1]} image")
    return data.reshape(shape)


def compare(ported: np.ndarray, reference: np.ndarray, wet: float) -> dict:
    """Relative agreement of the costs, clamped at COST_CAP."""
    wet_ported = ported >= wet
    wet_reference = reference >= wet
    wet_agree = bool(np.array_equal(wet_ported, wet_reference))

    live = ~(wet_ported | wet_reference)
    if not live.any():
        return {"relative": 0.0, "wet_agree": wet_agree, "n_live": 0,
                "n_capped": 0}

    capped_ported = np.minimum(ported, COST_CAP)
    capped_reference = np.minimum(reference, COST_CAP)
    relative = (np.abs(capped_ported - capped_reference)
                / np.maximum(np.abs(capped_reference), 1e-12))
    return {
        "relative": float(relative[live].max()),
        "wet_agree": wet_agree,
        "n_live": int(live.sum()),
        "n_capped": int((live & (reference > COST_CAP)).sum()),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tolerance", type=float, default=STRICT_TOLERANCE,
                        help="largest acceptable relative difference")
    parser.add_argument("--vectors", default=VECTOR_DIR)
    args = parser.parse_args(argv)

    images = sorted(name for name in os.listdir(args.vectors)
                    if name.endswith(".pgm"))
    if not images:
        raise SystemExit(f"no test images in {args.vectors}; "
                         f"run experiments/make_cost_vectors.py first")

    checked, missing, failures = 0, [], []
    print(f"{'image':<11}{'model':<9}{'dir':<6}{'live':>8}"
          f"{'capped':>8}{'rel err':>12}  wet")
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

                report = compare(ported, load_reference(path, cover.shape),
                                 wet_cost(model))
                checked += 1
                ok = report["relative"] <= args.tolerance and report["wet_agree"]
                if not ok:
                    failures.append((stem, model, direction, report))
                print(f"{stem:<11}{model:<9}{direction:<6}{report['n_live']:8d}"
                      f"{report['n_capped']:8d}{report['relative']:12.2e}"
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
                  f"{report['relative']:.3e}, wet map "
                  f"{'agrees' if report['wet_agree'] else 'differs'}")
        return 1

    print(f"all {checked} comparisons agree within {args.tolerance:g}, "
          f"costs clamped at {COST_CAP:g}, wet maps identical")
    print("The reference files can now be committed; the test suite will keep "
          "checking the port against them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
