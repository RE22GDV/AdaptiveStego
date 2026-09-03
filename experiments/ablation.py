#!/usr/bin/env python3
"""Ablation over the complexity maps that drive adaptive placement.

Runs the adaptive codec once per map, keeping everything else fixed, and
summarises detectability with cluster bootstrap intervals over covers.

    python experiments/ablation.py --synthetic 12 --seeds 3 --out results

The ``uniform`` map is the control: it removes every content preference, so the
adaptive codec degrades to keyed random placement. If the control does not land
on top of the ``random`` method, the gain attributed to the map is coming from
somewhere else and the experiment is not measuring what it claims to measure.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src"))

from stats import cluster_summary  # noqa: E402

from adaptivestego.maps import MAP_KINDS  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--synthetic", type=int, default=12)
    parser.add_argument("--size", type=int, default=256)
    parser.add_argument("--images", nargs="+")
    parser.add_argument("--grayscale", action="store_true")
    parser.add_argument("--limit", type=int, default=0,
                        help="cap the number of images, as in benchmark.py")
    parser.add_argument("--jobs", type=int, default=0,
                        help="processes to run images on; 0 uses every core")
    parser.add_argument("--seeds", type=int, default=3)
    parser.add_argument("--payloads", nargs="+", type=float,
                        default=[0.1, 0.2, 0.4])
    parser.add_argument("--maps", nargs="+", default=list(MAP_KINDS))
    parser.add_argument("--out", default="results")
    args = parser.parse_args(argv)

    frames = []
    for kind in args.maps:
        prefix = os.path.join(args.out, f"ablation-{kind}")
        command = [sys.executable, os.path.join(HERE, "benchmark.py"),
                   "--methods", "adaptive", "--map", kind,
                   "--attacks", "identity", "--seeds", str(args.seeds),
                   "--payloads", *[str(p) for p in args.payloads],
                   "--out", prefix]
        command += ["--jobs", str(args.jobs)]
        if args.images:
            command += ["--images", *args.images]
            if args.limit:
                command += ["--limit", str(args.limit)]
            if args.grayscale:
                command.append("--grayscale")
        else:
            command += ["--synthetic", str(args.synthetic), "--size", str(args.size)]

        subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
        frame = pd.read_csv(f"{prefix}.csv")
        frame["map"] = kind
        frames.append(frame)
        print(f"done {kind}")

    df = pd.concat(frames, ignore_index=True)
    summary = cluster_summary(df, "spa_stego", ["map", "bpp_target"])
    quality = cluster_summary(df, "ssim", ["map", "bpp_target"]).rename(
        columns={"mean": "ssim"})[["map", "bpp_target", "ssim"]]
    timing = cluster_summary(df, "t_embed_s", ["map", "bpp_target"]).rename(
        columns={"mean": "t_embed_s"})[["map", "bpp_target", "t_embed_s"]]
    summary = (summary.rename(columns={"mean": "spa_stego"})
                      .merge(quality, on=["map", "bpp_target"])
                      .merge(timing, on=["map", "bpp_target"]))

    path = os.path.join(args.out, "ablation-summary.csv")
    summary.to_csv(path, index=False)

    table = summary.pivot(index="map", columns="bpp_target", values="spa_stego")
    print("\nSPA detectability by complexity map (lower is better):")
    print(table.sort_values(table.columns[-1]).to_string(
        float_format=lambda v: f"{v:.4f}"))
    print(f"\nwrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
