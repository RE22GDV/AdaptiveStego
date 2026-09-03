#!/usr/bin/env python3
"""Experiment driver: quality, robustness and detectability.

Runs a grid of (image x method x payload x attack) and writes one row per run
to CSV/JSON so that confidence intervals and plots can be produced afterwards.

Two embedding modes:

``research`` (default)
    Exactly ``bpp * pixels`` bits of pseudo-random payload, with no container
    header. This is the mode to use when comparing algorithms, including
    against WOW and S-UNIWARD: the constant signature and checksums of the
    application container would otherwise become part of the stego signal.

``application``
    The full ASG1 container, which is what a user of the tool actually sends.

Every (cover, replicate) pair gets its own embedding key and its own payload,
both derived from the cover content, the replicate index and a master key.
Reusing one key and one payload across images would paint the same spatial
pattern into every stego image, and a neural detector would learn that pattern
instead of learning the embedding algorithm.

Examples::

    python experiments/benchmark.py --synthetic 8 --out results/quick

    python experiments/benchmark.py --images "data/bossbase/*.pgm" --grayscale \
        --limit 200 --payloads 0.05 0.1 0.2 0.4 --seeds 3 --out results/bossbase

The output columns are documented in docs/experiments.md.
"""

from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import hmac
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
from adaptivestego.prng import deterministic_bits, deterministic_bytes  # noqa: E402
from adaptivestego.testing import synthetic_cover  # noqa: E402

DEFAULT_METHODS = ["sequential", "random", "matching", "edge", "adaptive",
                   "adaptive-matching", "stc", "wow", "uniward"]
DEFAULT_PAYLOADS = [0.05, 0.1, 0.2, 0.4]
DEFAULT_ATTACKS = ["identity", "noise:sigma=1", "jpeg:quality=95",
                   "brightness:delta=1", "drop:p=0.001"]
DEFAULT_MASTER_KEY = "adaptivestego-experiment-master-key-v1"


# ---------------------------------------------------------------------------
# per-case key and payload derivation
# ---------------------------------------------------------------------------
def case_material(cover: np.ndarray, seed: int, master_key: str) -> tuple[str, str, str]:
    """Derive an independent placement key and payload tag for one case.

        cover content + shape + replicate seed  ->  case id
        HMAC(master key, "placement/" + case id) -> embedding key
        HMAC(master key, "payload/"   + case id) -> payload key

    The derivation is content addressed, so it survives renaming the files and
    is identical on any machine, and it makes every (cover, replicate) pair use
    a different key and a different payload while the whole experiment stays
    reproducible from one master key.
    """
    case_id = hashlib.sha256(
        cover.tobytes() + repr(cover.shape).encode() + seed.to_bytes(4, "big")
    ).digest()
    master = master_key.encode("utf-8")
    placement = hmac.new(master, b"placement/" + case_id, hashlib.sha256).hexdigest()
    payload = hmac.new(master, b"payload/" + case_id, hashlib.sha256).hexdigest()
    return case_id.hex()[:16], placement, payload


def image_sources(args) -> list[tuple[str, object]]:
    """Where the covers come from, without loading them yet.

    Worker processes load their own image, so nothing large has to be pickled
    and sent across.
    """
    if args.synthetic:
        return [(f"synthetic-{i}", (args.size, i)) for i in range(args.synthetic)]
    paths: list[str] = []
    for pattern in args.images:
        paths.extend(sorted(glob.glob(pattern)))
    if not paths:
        raise SystemExit("no image matched the given patterns")
    if args.limit:
        paths = paths[:args.limit]
    return [(os.path.basename(p), p) for p in paths]


def _embed_case(img, bpp, mode, placement_key, payload_key, method, bits,
                map_kind, ecc_nsym):
    """Embed one payload and return (result, reference payload, bits written)."""
    if mode == "research":
        n_bits = sl.payload_bits_for_bpp(img, bpp)
        payload = deterministic_bits(payload_key, "payload", n_bits)
        result = sl.embed_raw(img, payload, method=method, key=placement_key,
                              bits_per_sample=bits, map_kind=map_kind)
        return result, payload, n_bits

    # Application mode: the largest message that leaves the container at the
    # requested payload, generated deterministically and incompressible.
    n_pixels = img.shape[0] * img.shape[1]
    budget = int(round(bpp * n_pixels)) // 8
    n_bytes = max(sl.container.max_message_bytes(budget, ecc_nsym=ecc_nsym), 1)
    payload = deterministic_bytes(payload_key, "payload", n_bytes)
    result = sl.embed(img, payload, method=method, key=placement_key,
                      compress=False, bits_per_sample=bits, map_kind=map_kind,
                      ecc_nsym=ecc_nsym)
    return result, payload, result.payload_bits


_NO_ANALYSIS = {"chi2_p_max": float("nan"), "spa_rate": float("nan")}


def run_case(name: str, img: np.ndarray, method: str, bpp: float, seed: int,
             attack_specs: list[str], master_key: str, bits: int, map_kind: str,
             ecc_nsym: int, mode: str, detect_cover: dict | None = None,
             steganalysis: bool = True) -> list[dict]:
    """Embed one payload and measure it under every requested attack.

    ``detect_cover`` is the steganalysis of the cover. It depends only on the
    image, so the caller computes it once per image rather than once per case -
    it costs about as much as an embedding and would otherwise be repeated for
    every method, payload and replicate.
    """
    case_id, placement_key, payload_key = case_material(img, seed, master_key)

    start = time.perf_counter()
    try:
        result, payload, n_bits = _embed_case(
            img, bpp, mode, placement_key, payload_key, method, bits,
            map_kind, ecc_nsym)
    except StegoError as exc:
        return [{"image": name, "case_id": case_id, "method": method,
                 "bpp_target": bpp, "seed": seed, "mode": mode,
                 "attack": "identity", "error": str(exc)}]
    embed_time = time.perf_counter() - start

    quality = metrics.quality_report(img, result.stego, result.payload_bits)
    if steganalysis:
        if detect_cover is None:
            detect_cover = analysis.quick_report(img)
        detect_stego = analysis.quick_report(result.stego)
    else:
        detect_cover = detect_stego = _NO_ANALYSIS

    rows = []
    for spec in attack_specs:
        attacked = attacks.apply_attack(result.stego, spec)
        start = time.perf_counter()
        try:
            if mode == "research":
                recovered = sl.extract_raw(attacked, n_bits, method=method,
                                           key=placement_key,
                                           bits_per_sample=bits, map_kind=map_kind)
                ok = bool(np.array_equal(recovered, payload))
                bit_errors = float(np.mean(recovered != payload))
            else:
                recovered = sl.extract(attacked, method=method, key=placement_key,
                                       as_text=False, bits_per_sample=bits,
                                       map_kind=map_kind)
                ok = recovered == payload
                bit_errors = metrics.ber(payload, recovered)
        except Exception:                       # noqa: BLE001 - nothing recovered
            ok, bit_errors = False, 1.0
        extract_time = time.perf_counter() - start

        rows.append({
            "image": name, "case_id": case_id, "method": method,
            "bpp_target": bpp, "seed": seed, "mode": mode, "attack": spec,
            "recovered": int(ok), "ber": bit_errors,
            "payload_bits": result.payload_bits,
            "container_bytes": result.payload_bytes,
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


def run_image(name: str, img: np.ndarray, options: dict) -> list[dict]:
    """Every case for one cover image, sharing one steganalysis of the cover."""
    steganalysis = options["steganalysis"]
    detect_cover = analysis.quick_report(img) if steganalysis else None
    rows = []
    for method in options["methods"]:
        for bpp in options["payloads"]:
            for seed in range(options["seeds"]):
                rows.extend(run_case(
                    name, img, method, bpp, seed, options["attacks"],
                    options["master_key"], options["bits"], options["map_kind"],
                    options["ecc_nsym"], options["mode"], detect_cover,
                    steganalysis))
    return rows


def _worker(task):
    """Entry point for the process pool: load one image and run it."""
    name, source, options = task
    if isinstance(source, str):
        img = sl.read_image(source, grayscale=options["grayscale"])
    else:
        size, seed = source
        img = synthetic_cover(size, size, seed=seed,
                              channels=1 if options["grayscale"] else 3)
    return run_image(name, img, options)


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
    parser.add_argument("--mode", choices=("research", "application"),
                        default="research",
                        help="raw payload (default) or the full ASG1 container")
    parser.add_argument("--methods", nargs="+", default=DEFAULT_METHODS)
    parser.add_argument("--payloads", nargs="+", type=float, default=DEFAULT_PAYLOADS)
    parser.add_argument("--attacks", nargs="+", default=DEFAULT_ATTACKS)
    parser.add_argument("--seeds", type=int, default=1,
                        help="independent embedding realisations per cover")
    parser.add_argument("--master-key", default=DEFAULT_MASTER_KEY, dest="master_key",
                        help="all per-case keys and payloads derive from this")
    parser.add_argument("--bits", type=int, default=1)
    parser.add_argument("--map", dest="map_kind", default="combined")
    parser.add_argument("--ecc", dest="ecc_nsym", type=int, default=0,
                        help="application mode only")
    parser.add_argument("--no-steganalysis", action="store_true",
                        dest="no_steganalysis",
                        help="skip chi-square and SPA; they cost about a quarter "
                             "of a run and say nothing about the +/-1 methods")
    parser.add_argument("--jobs", type=int, default=1,
                        help="processes to run images on; 0 uses every core")
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
    if args.mode == "research" and args.ecc_nsym:
        parser.error("--ecc applies to the application container, not to raw mode")

    sources = image_sources(args)
    options = {
        "methods": args.methods, "payloads": args.payloads,
        "attacks": args.attacks, "seeds": args.seeds,
        "master_key": args.master_key, "bits": args.bits,
        "map_kind": args.map_kind, "ecc_nsym": args.ecc_nsym,
        "mode": args.mode, "grayscale": args.grayscale,
        "steganalysis": not args.no_steganalysis,
    }
    jobs = max(args.jobs or (os.cpu_count() or 1), 1)
    total = len(sources)
    print(f"images: {total}, methods: {len(args.methods)}, "
          f"payloads: {len(args.payloads)}, replicates: {args.seeds}, "
          f"mode: {args.mode}, jobs: {jobs}", file=sys.stderr)

    tasks = [(name, source, options) for name, source in sources]
    rows: list[dict] = []
    done = 0
    if jobs > 1:
        import multiprocessing

        with multiprocessing.Pool(jobs) as pool:
            for result in pool.imap_unordered(_worker, tasks):
                rows.extend(result)
                done += 1
                print(f"\r{done}/{total} images", end="", file=sys.stderr,
                      flush=True)
    else:
        for task in tasks:
            rows.extend(_worker(task))
            done += 1
            print(f"\r{done}/{total} images", end="", file=sys.stderr, flush=True)
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
                   "mode": args.mode, "steganalysis": not args.no_steganalysis,
                   "methods": args.methods,
                   "payloads": args.payloads, "attacks": args.attacks,
                   "seeds": args.seeds, "master_key": args.master_key,
                   "bits": args.bits, "map": args.map_kind, "ecc": args.ecc_nsym,
                   "images": total, "jobs": jobs,
                   "note": "per-case keys and payloads derive from the cover "
                           "content, the replicate index and the master key"},
                  f, ensure_ascii=False, indent=2)
    print(f"wrote {len(rows)} rows to {args.out}.csv", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
