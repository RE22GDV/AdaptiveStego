#!/usr/bin/env python3
"""Train the SPAM+FLD detector on a cover set.

    python experiments/train_detector.py --images "data/bossbase/*.pgm" \
        --limit 2000 --method matching --bpp 0.4 --jobs 16

The split is by *image*: a cover and the stego made from it are always on the
same side of it. Training on one and testing on the other would be measuring
how well the model recognises the picture rather than the embedding, and that
mistake reports an AUC near 1 for a model that detects nothing.

Each image gets its own embedding key and its own random payload, derived the
same way experiments/benchmark.py derives them, so that no fixed pattern is
painted into every stego image for the classifier to latch onto.

The model is written into the package (src/adaptivestego/models/) so that the
analysis commands pick it up, and it carries its provenance: what it was
trained on, against which method, at which payload, and what it scored on the
held-out split.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import hmac
import json
import os
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import adaptivestego as sl  # noqa: E402
from adaptivestego.detector import MODEL_DIR, roc_auc, train_fld  # noqa: E402
from adaptivestego.features import spam_features  # noqa: E402
from adaptivestego.prng import deterministic_bits  # noqa: E402

MASTER_KEY = "adaptivestego-detector-master-key-v1"


def _natural(path: str):
    """Sort 2.pgm before 10.pgm, so that --limit takes a predictable half."""
    stem = os.path.splitext(os.path.basename(path))[0]
    return (0, int(stem), "") if stem.isdigit() else (1, 0, stem)


def _material(path: str) -> tuple[str, str]:
    """Per-image placement key and payload key, from the file content."""
    with open(path, "rb") as handle:
        digest = hashlib.sha256(handle.read()).digest()
    master = MASTER_KEY.encode("utf-8")
    return (hmac.new(master, b"placement/" + digest, hashlib.sha256).hexdigest(),
            hmac.new(master, b"payload/" + digest, hashlib.sha256).hexdigest())


def _one_image(job):
    """Features of one cover and of the stego made from it."""
    path, method, bpp, grayscale = job
    cover = sl.read_image(path, grayscale=grayscale)
    placement, payload_key = _material(path)
    n_bits = sl.payload_bits_for_bpp(cover, bpp)
    bits = deterministic_bits(payload_key, "payload", n_bits)
    stego = sl.embed_raw(cover, bits, method=method, key=placement).stego
    return spam_features(cover), spam_features(stego)


def _assign(paths, methods, payloads):
    """Give every cover one (method, payload), spread evenly over the set.

    One stego per cover, not one per combination: the pairing is what keeps
    the train/test split honest, and a cover that appeared with four different
    payloads would be four chances for the model to memorise that picture.
    """
    combinations = [(m, b) for m in methods for b in payloads]
    return [combinations[index % len(combinations)]
            for index in range(len(paths))]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--images", default="data/bossbase/*.pgm",
                        help="glob for the cover images")
    parser.add_argument("--limit", type=int, default=2000)
    parser.add_argument("--skip", type=int, default=0,
                        help="skip this many images first, so that a model "
                             "and a later experiment can use disjoint halves "
                             "of the same dataset")
    parser.add_argument("--method", nargs="+", default=["matching"],
                        help="embedding methods the model is trained against")
    parser.add_argument("--bpp", nargs="+", type=float, default=[0.4],
                        help="payloads, in bits per pixel")
    parser.add_argument("--grayscale", action="store_true", default=True)
    parser.add_argument("--colour", dest="grayscale", action="store_false")
    parser.add_argument("--test-fraction", type=float, default=0.3)
    parser.add_argument("--jobs", type=int, default=0,
                        help="worker processes; 0 means every core")
    parser.add_argument("--out", default=None,
                        help="model file (default: models/spam-fld.npz)")
    parser.add_argument("--seed", type=int, default=20260912)
    args = parser.parse_args(argv)

    paths = sorted(glob.glob(args.images), key=_natural)
    paths = paths[args.skip:args.skip + args.limit]
    if len(paths) < 50:
        raise SystemExit(f"only {len(paths)} images matched {args.images!r}; "
                         f"this needs a few hundred at least")

    jobs = args.jobs or (os.cpu_count() or 1)
    print(f"{len(paths)} covers, {', '.join(args.method)} at "
          f"{', '.join(str(b) for b in args.bpp)} bpp, {jobs} worker(s)")

    started = time.perf_counter()
    assignment = _assign(paths, args.method, args.bpp)
    work = [(p, method, bpp, args.grayscale)
            for p, (method, bpp) in zip(paths, assignment, strict=True)]
    if jobs > 1:
        import multiprocessing as mp

        with mp.Pool(jobs) as pool:
            pairs = []
            for index, item in enumerate(pool.imap(_one_image, work, chunksize=8), 1):
                pairs.append(item)
                if index % 200 == 0:
                    print(f"\r  {index} / {len(work)}", end="", flush=True)
    else:
        pairs = [_one_image(item) for item in work]
    print(f"\r  {len(pairs)} images in {time.perf_counter() - started:.1f} s")

    cover = np.array([c for c, _ in pairs])
    stego = np.array([s for _, s in pairs])

    # The split is over image indices, so a cover and its stego stay together.
    rng = np.random.default_rng(args.seed)
    order = rng.permutation(len(paths))
    n_test = int(round(args.test_fraction * len(paths)))
    test_index, train_index = order[:n_test], order[n_test:]

    methods = ", ".join(args.method)
    payloads = ", ".join(f"{b:g}" for b in args.bpp)
    meta = {
        "features": "spam686",
        "classifier": "fld",
        "method": methods,
        "bpp": payloads,
        "trained_on": f"{len(train_index)} images from {args.images}",
        "valid_for": (f"{methods} at {payloads} bpp in images like the "
                      f"training set (512x512 grayscale photographs for "
                      f"BOSSBase); a different source, method or payload "
                      f"needs its own model"),
        "n_images": len(paths),
        "seed": args.seed,
        # Which images the model saw, so that an experiment reporting this
        # detector can check it is not being run on its own training set.
        "images_sha256": hashlib.sha256(
            "\n".join(os.path.basename(p) for p in paths).encode()).hexdigest(),
        "images_first": [os.path.basename(p) for p in paths[:3]],
        "images_last": [os.path.basename(p) for p in paths[-3:]],
    }

    model = train_fld(cover[train_index], stego[train_index], meta=meta)

    cover_scores = np.array([model.score_features(f) for f in cover[test_index]])
    stego_scores = np.array([model.score_features(f) for f in stego[test_index]])
    auc = roc_auc(cover_scores, stego_scores)
    accuracy = float(np.mean(np.concatenate([
        cover_scores <= model.threshold, stego_scores > model.threshold])))
    # The error rate steganalysis papers report: the smallest average of the
    # two error rates over all thresholds.
    thresholds = np.unique(np.concatenate([cover_scores, stego_scores]))
    p_error = min(
        0.5 * (np.mean(cover_scores > t) + np.mean(stego_scores <= t))
        for t in thresholds)

    # Per-slice numbers as well: one overall AUC over a mixture of payloads
    # says nothing about where the model actually works, and the low-payload
    # slice is the one that matters.
    slices = {}
    for index in test_index:
        slices.setdefault(assignment[index], []).append(index)
    per_slice = {}
    for (method, bpp), indices in sorted(slices.items()):
        indices = np.array(indices)
        c = np.array([model.score_features(f) for f in cover[indices]])
        s_ = np.array([model.score_features(f) for f in stego[indices]])
        per_slice[f"{method}@{bpp:g}"] = {
            "n": int(len(indices)),
            "auc": float(roc_auc(c, s_)),
            "accuracy": float(np.mean(np.concatenate([c <= model.threshold,
                                                      s_ > model.threshold]))),
        }

    model.meta["test_auc"] = float(auc)
    model.meta["test_accuracy"] = accuracy
    model.meta["test_p_error"] = float(p_error)
    model.meta["n_test"] = int(n_test)
    model.meta["test_by_slice"] = per_slice

    out = args.out or os.path.join(MODEL_DIR, "spam-fld.npz")
    model.save(out)

    print(f"\nheld-out AUC        {auc:.4f}")
    print(f"held-out accuracy   {accuracy:.4f}")
    print(f"min average error   {p_error:.4f}")
    print(f"ridge               {model.meta['ridge']:g}")
    print(f"\nmodel written to {out}")
    print(json.dumps(model.meta, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
