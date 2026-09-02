#!/usr/bin/env python3
"""Generate the figures used in the README.

    python experiments/figures.py

Writes into docs/figures/:
  placement.png     where each method puts the bits
  detectability.png payload against SPA detectability
  ablation.png      detectability per complexity map
  performance.png   embedding and extraction speed against image size
"""

from __future__ import annotations

import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

import stegolab as sl  # noqa: E402
from stegolab.testing import synthetic_cover  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIGURES = os.path.join(ROOT, "docs", "figures")


def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt


def placement_figure(path: str) -> None:
    """Cover image plus the map of modified samples for four methods."""
    plt = _plt()
    cover = synthetic_cover(320, 320, seed=3)
    n_pixels = cover.shape[0] * cover.shape[1]
    payload = bytes(np.random.default_rng(0).integers(
        0, 256, int(n_pixels * 0.2 / 8), dtype=np.uint8))

    methods = ["sequential", "random", "edge", "adaptive"]
    fig, axes = plt.subplots(1, len(methods) + 1, figsize=(14, 3.2), dpi=140)
    axes[0].imshow(cover)
    axes[0].set_title("cover", fontsize=10)
    axes[0].axis("off")

    for ax, method in zip(axes[1:], methods, strict=True):
        stego = sl.embed(cover, payload, method=method, key="figure",
                         compress=False).stego
        changed = np.any(stego != cover, axis=2)
        ax.imshow(changed, cmap="gray", interpolation="nearest")
        ax.set_title(f"{method}\n({changed.mean() * 100:.1f} % of pixels)",
                     fontsize=10)
        ax.axis("off")

    fig.suptitle("Where the message goes at 0.2 bits per pixel "
                 "(white = modified pixel)", fontsize=11, y=0.995)
    fig.tight_layout(rect=(0, 0, 1, 0.90))
    fig.savefig(path)
    plt.close(fig)
    print(f"figure: {path}")


def detectability_figure(csv_path: str, path: str) -> None:
    """Payload against the SPA estimate, with 95% confidence intervals."""
    import pandas as pd

    plt = _plt()
    df = pd.read_csv(csv_path)
    df = df[df["attack"] == "identity"]

    fig, ax = plt.subplots(figsize=(7.4, 4.6), dpi=140)
    for method, group in df.groupby("method"):
        agg = group.groupby("bpp_target")["spa_stego"].agg(
            ["mean", "std", "size"]).reset_index()
        ci = 1.96 * agg["std"] / np.sqrt(agg["size"])
        ax.errorbar(agg["bpp_target"], agg["mean"], yerr=ci, marker="o",
                    capsize=3, label=method)
    ax.axhline(df["spa_cover"].mean(), color="grey", linestyle=":",
               label="clean cover")
    ax.set_xlabel("payload, bits per pixel")
    ax.set_ylabel("SPA estimate (lower is better)")
    ax.set_title("Detectability at an equal payload")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    print(f"figure: {path}")


def ablation_figure(csv_path: str, path: str) -> None:
    """Detectability of the adaptive codec for each complexity map."""
    import pandas as pd

    plt = _plt()
    df = pd.read_csv(csv_path)
    order = df[df["bpp"] == df["bpp"].max()].sort_values("spa")["map"].tolist()

    fig, ax = plt.subplots(figsize=(7.4, 4.6), dpi=140)
    for name in order:
        group = df[df["map"] == name].sort_values("bpp")
        style = {"linewidth": 2.4} if name in ("combined", "uniform") else {}
        ax.errorbar(group["bpp"], group["spa"], yerr=group["spa_ci"], marker="o",
                    capsize=3, label=name, **style)
    ax.set_xlabel("payload, bits per pixel")
    ax.set_ylabel("SPA estimate (lower is better)")
    ax.set_title("Ablation: which complexity map drives the placement")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8, ncol=2)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    print(f"figure: {path}")


def performance_figure(csv_path: str, path: str) -> None:
    """Embedding and extraction time against image size."""
    import pandas as pd

    plt = _plt()
    df = pd.read_csv(csv_path)
    fig, (left, right) = plt.subplots(1, 2, figsize=(11, 4.2), dpi=140)
    for method, group in df.groupby("method"):
        group = group.sort_values("megapixels")
        left.plot(group["megapixels"], group["embed_best_ms"], marker="o",
                  label=method)
        right.plot(group["megapixels"], group["extract_best_ms"], marker="o",
                   label=method)
    for ax, title in ((left, "Embedding"), (right, "Extraction")):
        ax.set_xlabel("image size, megapixels")
        ax.set_ylabel("time, ms")
        ax.set_yscale("log")
        ax.set_title(title)
        ax.grid(alpha=0.3, which="both")
        ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    print(f"figure: {path}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", default=os.path.join(ROOT, "results"))
    args = parser.parse_args(argv)

    os.makedirs(FIGURES, exist_ok=True)
    placement_figure(os.path.join(FIGURES, "placement.png"))

    pairs = [
        ("main.csv", "detectability.png", detectability_figure),
        ("ablation-summary.csv", "ablation.png", ablation_figure),
        ("performance.csv", "performance.png", performance_figure),
    ]
    for name, out, draw in pairs:
        source = os.path.join(args.results, name)
        if os.path.isfile(source):
            draw(source, os.path.join(FIGURES, out))
        else:
            print(f"skipped {out}: {source} is missing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
