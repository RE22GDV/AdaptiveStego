#!/usr/bin/env python3
"""Experiment driver: quality, robustness and detectability.

Runs a grid of (image x method x payload x attack) and writes one row per run
to CSV/JSON so that confidence intervals and plots can be produced afterwards.

Examples::

    # quick run on synthetic covers
    python experiments/benchmark.py --synthetic 8 --out results/quick

    # a real dataset
    python experiments/benchmark.py --images "data/bossbase/*.pgm" --grayscale \
        --limit 200 --payloads 0.05 0.1 0.2 0.4 --seeds 3 --out results/bossbase

The output columns are documented in docs/experiments.md.
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

import adaptivestego as sl  # noqa: E402
from adaptivestego import analysis, attacks, metrics  # noqa: E402
from adaptivestego.exceptions import StegoError  # noqa: E402
from adaptivestego.testing import synthetic_cover  # noqa: E402

DEFAULT_METHODS = ["sequential", "random", "matching", "edge", "adaptive",
                   "adaptive-matching"]
DEFAULT_PAYLOADS = [0.05, 0.1, 0.2, 0.4]
DEFAULT_ATTACKS = ["identity", "noise:sigma=1", "jpeg:quality=95",
                   "brightness:delta=1", "drop:p=0.001"]


def payload_bytes(img: np.ndarray, bpp: float) -> int:
    """Message size in bytes that corresponds to a payload in bits per pixel."""
    n_pixels = img.shape[0] * img.shape[1]
    return max(int(n_pixels * bpp / 8) - 64, 1)   # leave room for the header


def random_message(n_bytes: int, seed: int) -> bytes:
    """Incompressible message: the payload must not depend on text entropy."""
    return bytes(np.random.default_rng(seed).integers(0, 256, n_bytes, dtype=np.uint8))


def load_images(args) -> list[tuple[str, np.ndarray]]:
    """Load the cover images requested on the command line."""
    if args.synthetic:
        return [(f"synthetic-{i}", synthetic_cover(args.size, args.size, seed=i))
                for i in range(args.synthetic)]
    paths: list[str] = []
    for pattern in args.images:
        paths.extend(sorted(glob.glob(pattern)))
    if not paths:
        raise SystemExit("no image matched the given patterns")
    if args.limit:
        paths = paths[:args.limit]
    return [(os.path.basename(p), sl.read_image(p, grayscale=args.grayscale))
            for p in paths]


def run_case(name: str, img: np.ndarray, method: str, bpp: float, seed: int,
             attack_specs: list[str], key: str, bits: int, map_kind: str,
             ecc_nsym: int) -> list[dict]:
    """Embed one message and measure it under every requested attack."""
    n_bytes = payload_bytes(img, bpp)
    message = random_message(n_bytes, seed)

    start = time.perf_counter()
    try:
        result = sl.embed(img, message, method=method, key=key, compress=False,
                          bits_per_sample=bits, map_kind=map_kind,
                          ecc_nsym=ecc_nsym)
    except StegoError as exc:
        return [{"image": name, "method": method, "bpp_target": bpp, "seed": seed,
                 "attack": "identity", "error": str(exc)}]
    embed_time = time.perf_counter() - start

    quality = metrics.quality_report(img, result.stego, result.payload_bytes * 8)
    detect_cover = analysis.quick_report(img)
    detect_stego = analysis.quick_report(result.stego)

    rows = []
    for spec in attack_specs:
        attacked = attacks.apply_attack(result.stego, spec)
        start = time.perf_counter()
        try:
            recovered = sl.extract(attacked, method=method, key=key, as_text=False,
                                   bits_per_sample=bits, map_kind=map_kind)
            ok, bit_errors = recovered == message, metrics.ber(message, recovered)
        except Exception:                       # noqa: BLE001 - nothing recovered
            ok, bit_errors = False, 1.0
        extract_time = time.perf_counter() - start

        rows.append({
            "image": name, "method": method, "bpp_target": bpp, "seed": seed,
            "attack": spec, "recovered": int(ok), "ber": bit_errors,
            "message_bytes": n_bytes, "container_bytes": result.payload_bytes,
            "bpp_actual": result.bpp, "bpp_max": result.max_bpp,
            "change_rate": result.change_rate,
            "psnr_db": quality["psnr_db"], "ssim": quality["ssim"],
            "max_abs_diff": quality["max_abs_diff"],
            "embedding_efficiency": quality["embedding_efficiency"],
            "spa_cover": detect_cover["spa_rate"],
            "spa_stego": detect_stego["spa_rate"],
            "chi2_cover": detect_cover["chi2_p_max"],
            "chi2_stego": detect_stego["chi2_p_max"],
            "t_embed_s": embed_time, "t_extract_s": extract_time,
            "error": "",
        })
    return rows


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", help="JSON file holding any of the options below")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--images", nargs="+", help="glob patterns for cover images")
    source.add_argument("--synthetic", type=int, help="number of synthetic covers")
    parser.add_argument("--size", type=int, default=256,
                        help="side length of the synthetic covers")
    parser.add_argument("--limit", type=int, default=0, help="cap the image count")
    parser.add_argument("--grayscale", action="store_true")
    parser.add_argument("--methods", nargs="+", default=DEFAULT_METHODS)
    parser.add_argument("--payloads", nargs="+", type=float, default=DEFAULT_PAYLOADS)
    parser.add_argument("--attacks", nargs="+", default=DEFAULT_ATTACKS)
    parser.add_argument("--seeds", type=int, default=1, help="repeats per case")
    parser.add_argument("--key", default="benchmark-key")
    parser.add_argument("--bits", type=int, default=1)
    parser.add_argument("--map", dest="map_kind", default="combined")
    parser.add_argument("--ecc", dest="ecc_nsym", type=int, default=0)
    parser.add_argument("--out", default="results/benchmark",
                        help="prefix of the output files")

    known, _rest = parser.parse_known_args(argv)
    if known.config:
        with open(known.config, encoding="utf-8") as f:
            config = json.load(f)
        unknown = set(config) - {action.dest for action in parser._actions}
        if unknown:
            raise SystemExit(f"unknown configuration keys: {sorted(unknown)}")
        parser.set_defaults(**config)          # the command line still wins
    args = parser.parse_args(argv)
    if not args.images and not args.synthetic:
        parser.error("one of --images, --synthetic or --config is required")

    images = load_images(args)
    total = len(images) * len(args.methods) * len(args.payloads) * args.seeds
    print(f"images: {len(images)}, configurations: {total}", file=sys.stderr)

    rows: list[dict] = []
    done = 0
    for name, img in images:
        for method in args.methods:
            for bpp in args.payloads:
                for seed in range(args.seeds):
                    rows.extend(run_case(name, img, method, bpp, seed, args.attacks,
                                         args.key, args.bits, args.map_kind,
                                         args.ecc_nsym))
                    done += 1
                    print(f"\r{done}/{total}", end="", file=sys.stderr, flush=True)
    print(file=sys.stderr)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    fields = sorted({key for row in rows for key in row})
    with open(f"{args.out}.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    with open(f"{args.out}.meta.json", "w", encoding="utf-8") as f:
        json.dump({"argv": sys.argv[1:], "n_rows": len(rows),
                   "adaptivestego_version": sl.__version__,
                   "methods": args.methods, "payloads": args.payloads,
                   "attacks": args.attacks, "seeds": args.seeds,
                   "key": args.key, "bits": args.bits, "map": args.map_kind,
                   "ecc": args.ecc_nsym, "images": len(images)},
                  f, ensure_ascii=False, indent=2)
    print(f"wrote {len(rows)} rows to {args.out}.csv", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
