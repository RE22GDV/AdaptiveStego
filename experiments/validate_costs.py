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

# Costs an embedder would ever act on. Typical values are between 0.01 and 100;
# anything above this is "never touch this sample" and only differs from the
# wet cost in bookkeeping.
USABLE_COST = 1e3

# Above that threshold the two implementations legitimately disagree in
# relative terms. In a perfectly flat region the wavelet residual is zero up to
# cancellation, so the suitability keeps only a few significant digits, and the
# reciprocal Holder norm of WOW turns that into a large relative difference on
# a number of order 1e9. Any two implementations differing in summation order
# do this; it says nothing about the port.
STRICT_TOLERANCE = 1e-9
LOOSE_TOLERANCE = 1e-4


def load_reference(path: str, shape: tuple[int, int]) -> np.ndarray:
    """Read a float64 matrix written by the MATLAB driver."""
    data = np.fromfile(path, dtype=np.float64)
    if data.size != shape[0] * shape[1]:
        raise ValueError(
            f"{os.path.basename(path)} holds {data.size} values, expected "
            f"{shape[0] * shape[1]} for a {shape[0]}x{shape[1]} image")
    return data.reshape(shape)


def compare(ported: np.ndarray, reference: np.ndarray, wet: float) -> dict:
    """Relative agreement, split by whether a cost is one anybody would use."""
    wet_ported = ported >= wet
    wet_reference = reference >= wet
    wet_agree = bool(np.array_equal(wet_ported, wet_reference))

    live = ~(wet_ported | wet_reference)
    if not live.any():
        return {"usable_relative": 0.0, "extreme_relative": 0.0,
                "wet_agree": wet_agree, "n_usable": 0, "n_extreme": 0}

    relative = (np.abs(ported - reference)
                / np.maximum(np.abs(reference), 1e-12))
    usable = live & (reference <= USABLE_COST)
    extreme = live & (reference > USABLE_COST)
    return {
        "usable_relative": float(relative[usable].max()) if usable.any() else 0.0,
        "extreme_relative": float(relative[extreme].max()) if extreme.any() else 0.0,
        "wet_agree": wet_agree,
        "n_usable": int(usable.sum()),
        "n_extreme": int(extreme.sum()),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tolerance", type=float, default=STRICT_TOLERANCE,
                        help="largest acceptable relative difference for usable costs")
    parser.add_argument("--extreme-tolerance", type=float, default=LOOSE_TOLERANCE,
                        dest="extreme_tolerance",
                        help=f"the same, for costs above {USABLE_COST:g}")
    parser.add_argument("--vectors", default=VECTOR_DIR)
    args = parser.parse_args(argv)

    images = sorted(name for name in os.listdir(args.vectors)
                    if name.endswith(".pgm"))
    if not images:
        raise SystemExit(f"no test images in {args.vectors}; "
                         f"run experiments/make_cost_vectors.py first")

    checked, missing, failures = 0, [], []
    print(f"{'image':<11}{'model':<9}{'dir':<6}"
          f"{'usable':>10}{'rel err':>11}{'extreme':>9}{'rel err':>11}  wet")
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
                ok = (report["usable_relative"] <= args.tolerance
                      and report["extreme_relative"] <= args.extreme_tolerance
                      and report["wet_agree"])
                if not ok:
                    failures.append((stem, model, direction, report))
                print(f"{stem:<11}{model:<9}{direction:<6}"
                      f"{report['n_usable']:10d}{report['usable_relative']:11.2e}"
                      f"{report['n_extreme']:9d}{report['extreme_relative']:11.2e}"
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
            print(f"  {stem}/{model}/{direction}: usable "
                  f"{report['usable_relative']:.3e}, extreme "
                  f"{report['extreme_relative']:.3e}, wet map "
                  f"{'agrees' if report['wet_agree'] else 'differs'}")
        return 1

    print(f"all {checked} comparisons agree: usable costs within "
          f"{args.tolerance:g}, costs above {USABLE_COST:g} within "
          f"{args.extreme_tolerance:g}, wet maps identical")
    print("The reference files can now be committed; the test suite will keep "
          "checking the port against them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
