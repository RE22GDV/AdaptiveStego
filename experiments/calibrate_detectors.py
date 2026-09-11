#!/usr/bin/env python3
"""Measure what the detectors do on clean images, and on known payloads.

    python experiments/calibrate_detectors.py --images "data/bossbase/*.pgm" \
        --skip 5000 --limit 200 --jobs 16

Two tables come out of this.

The first is the clean distribution: the thresholds in analysis.py are taken
from it, and they are only meaningful if the images they were measured on are
not the images the tool is later judged on. ``--skip`` exists for that - the
trained model ships having seen the first half of BOSSBase, so calibration and
evaluation use the second.

The second is detection power: the share of images each detector fires on at a
given method and payload, and the share of *clean* images it fires on, which
is the number that decides whether a threshold is worth anything at all. A
detector that fires on 90 % of stego images and 30 % of covers has told you
nothing.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import adaptivestego as sl  # noqa: E402
from adaptivestego import analysis, detector  # noqa: E402
from adaptivestego.prng import deterministic_bits  # noqa: E402

RATES = ("spa_rate", "rs_rate", "ws_rate")


def _natural(path: str):
    stem = os.path.splitext(os.path.basename(path))[0]
    return (0, int(stem), "") if stem.isdigit() else (1, 0, stem)


def _measure(job):
    """Detector outputs for one cover and for one stego made from it."""
    path, method, bpp, grayscale = job
    cover = sl.read_image(path, grayscale=grayscale)
    clean = analysis.quick_report(cover)
    if method is None:
        return clean, None

    n_bits = sl.payload_bits_for_bpp(cover, bpp)
    bits = deterministic_bits(f"payload/{os.path.basename(path)}", "p", n_bits)
    stego = sl.embed_raw(cover, bits, method=method,
                         key=f"place/{os.path.basename(path)}").stego
    return clean, analysis.quick_report(stego)


def _fire_rates(reports: list[dict]) -> dict:
    """Share of images each detector and the combined verdict fires on."""
    n = max(len(reports), 1)
    out = {name: float(sum(r[name] > analysis.RATE_STRONG for r in reports) / n)
           for name in RATES}
    out["chi2"] = float(sum(r["chi2_p_max"] > analysis.CHI2_STRONG
                            for r in reports) / n)
    out["verdict_detected"] = float(
        sum(r["verdict"]["level"] == "detected" for r in reports) / n)
    out["verdict_not_clean"] = float(
        sum(r["verdict"]["level"] != "clean" for r in reports) / n)
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--images", default="data/bossbase/*.pgm")
    parser.add_argument("--skip", type=int, default=5000,
                        help="skip this many images, to stay clear of the "
                             "half the shipped model was trained on")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--methods", nargs="+",
                        default=["sequential", "random", "matching",
                                 "adaptive", "adaptive-matching"])
    parser.add_argument("--payloads", nargs="+", type=float,
                        default=[0.1, 0.25, 0.5])
    parser.add_argument("--grayscale", action="store_true", default=True)
    parser.add_argument("--jobs", type=int, default=0)
    parser.add_argument("--out", default="results/detector-calibration.json")
    args = parser.parse_args(argv)

    paths = sorted(glob.glob(args.images), key=_natural)
    paths = paths[args.skip:args.skip + args.limit]
    if not paths:
        raise SystemExit(f"no images matched {args.images!r}")

    jobs = args.jobs or (os.cpu_count() or 1)
    pool = None
    if jobs > 1:
        import multiprocessing as mp
        pool = mp.Pool(jobs)

    def run(work):
        return list(pool.imap(_measure, work, chunksize=4)) if pool else \
            [_measure(item) for item in work]

    print(f"{len(paths)} images from {args.images} (skipping {args.skip})\n")

    clean_reports = [c for c, _ in run([(p, None, 0.0, args.grayscale)
                                        for p in paths])]
    result = {"images": len(paths), "skip": args.skip, "source": args.images}

    print("clean images")
    print(f"  {'detector':<12}{'mean':>9}{'p95':>9}{'p99':>9}{'max':>9}")
    clean_stats = {}
    for name in RATES + ("hcf_ratio",):
        values = np.array([r[name] for r in clean_reports])
        clean_stats[name] = {
            "mean": float(values.mean()),
            "p1": float(np.percentile(values, 1)),
            "p95": float(np.percentile(values, 95)),
            "p99": float(np.percentile(values, 99)),
            "max": float(values.max()),
        }
        print(f"  {name:<12}{values.mean():9.4f}"
              f"{np.percentile(values, 95):9.4f}"
              f"{np.percentile(values, 99):9.4f}{values.max():9.4f}")
    result["clean"] = clean_stats
    result["clean_fire_rates"] = _fire_rates(clean_reports)
    print(f"\n  false positives at the shipped thresholds: "
          f"{result['clean_fire_rates']['verdict_detected'] * 100:.1f} % "
          f"called detected, "
          f"{result['clean_fire_rates']['verdict_not_clean'] * 100:.1f} % "
          f"not called clean")

    model = detector.load()
    if model is not None:
        scores = np.array([model.score(sl.read_image(p, grayscale=True))
                           for p in paths])
        result["model_clean_positive_rate"] = float(
            np.mean(scores > model.threshold))
        print(f"  trained model calls {result['model_clean_positive_rate'] * 100:.1f} "
              f"% of them stego")

    print(f"\n{'method':<20}{'bpp':>6}{'SPA':>8}{'RS':>8}{'WS':>8}"
          f"{'chi2':>8}{'verdict':>9}{'model':>8}")
    power = {}
    for method in args.methods:
        for bpp in args.payloads:
            work = [(p, method, bpp, args.grayscale) for p in paths]
            stego_reports = [s for _, s in run(work)]
            rates = _fire_rates(stego_reports)
            row = dict(rates)
            if model is not None:
                # Recomputing the stego images here costs one more pass but
                # keeps the worker output small; the alternative is shipping
                # whole images back from every worker.
                hits = 0
                for path in paths:
                    cover = sl.read_image(path, grayscale=args.grayscale)
                    bits = deterministic_bits(
                        f"payload/{os.path.basename(path)}", "p",
                        sl.payload_bits_for_bpp(cover, bpp))
                    stego = sl.embed_raw(
                        cover, bits, method=method,
                        key=f"place/{os.path.basename(path)}").stego
                    hits += model.score(stego) > model.threshold
                row["model"] = hits / len(paths)
            power[f"{method}@{bpp:g}"] = row
            print(f"{method:<20}{bpp:6.2f}{row['spa_rate']:8.2f}"
                  f"{row['rs_rate']:8.2f}{row['ws_rate']:8.2f}"
                  f"{row['chi2']:8.2f}{row['verdict_detected']:9.2f}"
                  f"{row.get('model', float('nan')):8.2f}")
    result["power"] = power

    if pool is not None:
        pool.close()
        pool.join()

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2)
    print(f"\nwritten to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
