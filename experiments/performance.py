#!/usr/bin/env python3
"""Speed and memory benchmark.

Measures how long embedding and extraction take for each method as the image
grows, and how much memory a single operation needs. Adaptive methods pay for
the complexity map, so the interesting number is the gap between them and the
plain LSB baselines.

    python experiments/performance.py --out results/performance
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import sys
import time
import tracemalloc

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

import adaptivestego as sl  # noqa: E402
from adaptivestego.prng import deterministic_bits  # noqa: E402
from adaptivestego.testing import synthetic_cover  # noqa: E402

DEFAULT_SIZES = [256, 512, 1024, 2048]
DEFAULT_METHODS = ["sequential", "random", "matching", "edge", "adaptive",
                   "adaptive-matching", "stc"]


def timeit(fn, repeats: int) -> tuple[float, float]:
    """Run fn repeatedly and return the best and the median time in seconds."""
    samples = []
    for _ in range(repeats):
        start = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - start)
    return min(samples), float(np.median(samples))


def measure(method: str, size: int, bpp: float, repeats: int) -> dict:
    """Measure one (method, size) combination."""
    img = synthetic_cover(size, size, seed=1)
    n_pixels = size * size

    # Raw payloads: the same amount of data for every method, and syndrome
    # coding has no container to use.
    payload = deterministic_bits("perf", f"payload/{size}/{bpp}",
                                 sl.payload_bits_for_bpp(img, bpp))

    def do_embed():
        return sl.embed_raw(img, payload, method=method, key="perf")

    stego = do_embed().stego

    def do_extract():
        return sl.extract_raw(stego, payload.size, method=method, key="perf")

    embed_best, embed_median = timeit(do_embed, repeats)
    extract_best, extract_median = timeit(do_extract, repeats)

    tracemalloc.start()
    do_embed()
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    megapixels = n_pixels / 1e6
    return {
        "method": method,
        "size": size,
        "megapixels": megapixels,
        "bpp": bpp,
        "payload_bits": int(payload.size),
        "embed_best_ms": embed_best * 1000.0,
        "embed_median_ms": embed_median * 1000.0,
        "extract_best_ms": extract_best * 1000.0,
        "extract_median_ms": extract_median * 1000.0,
        "embed_mpx_per_s": megapixels / embed_best,
        "extract_mpx_per_s": megapixels / extract_best,
        "throughput_kb_per_s": (payload.size / 8 / 1024.0) / embed_best,
        "peak_memory_mb": peak / (1024.0 * 1024.0),
        "memory_per_megapixel_mb": peak / (1024.0 * 1024.0) / megapixels,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sizes", nargs="+", type=int, default=DEFAULT_SIZES)
    parser.add_argument("--methods", nargs="+", default=DEFAULT_METHODS)
    parser.add_argument("--bpp", type=float, default=0.2)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--out", default="results/performance")
    args = parser.parse_args(argv)

    rows = []
    for size in args.sizes:
        for method in args.methods:
            row = measure(method, size, args.bpp, args.repeats)
            rows.append(row)
            print(f"{method:<18} {size:>5}px  "
                  f"embed {row['embed_best_ms']:8.1f} ms  "
                  f"extract {row['extract_best_ms']:8.1f} ms  "
                  f"{row['embed_mpx_per_s']:6.2f} Mpx/s  "
                  f"peak {row['peak_memory_mb']:6.1f} MB", flush=True)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(f"{args.out}.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    environment = {
        "python": sys.version.split()[0],
        "numpy": np.__version__,
        "platform": platform.platform(),
        "processor": platform.processor(),
        "machine": platform.machine(),
        "adaptivestego": sl.__version__,
    }
    with open(f"{args.out}.meta.json", "w", encoding="utf-8") as f:
        json.dump({"environment": environment, "argv": sys.argv[1:]}, f,
                  ensure_ascii=False, indent=2)

    try:
        _plot(rows, f"{args.out}.png")
    except ImportError:
        print("matplotlib is not installed, the figure was skipped")
    print(f"wrote {len(rows)} rows to {args.out}.csv")
    return 0


def _plot(rows: list[dict], path: str) -> None:
    """Embedding time against image size, one line per method."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, (left, right) = plt.subplots(1, 2, figsize=(11, 4.4), dpi=150)
    methods = sorted({row["method"] for row in rows})
    for method in methods:
        series = sorted((r for r in rows if r["method"] == method),
                        key=lambda r: r["megapixels"])
        x = [r["megapixels"] for r in series]
        left.plot(x, [r["embed_best_ms"] for r in series], marker="o", label=method)
        right.plot(x, [r["extract_best_ms"] for r in series], marker="o",
                   label=method)
    for ax, title in ((left, "Embedding"), (right, "Extraction")):
        ax.set_xlabel("image size, megapixels")
        ax.set_ylabel("time, ms")
        ax.set_title(title)
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    print(f"figure: {path}")


if __name__ == "__main__":
    raise SystemExit(main())
