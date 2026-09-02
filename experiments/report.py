#!/usr/bin/env python3
"""Summary tables and plots for the output of benchmark.py.

    python experiments/report.py results/quick.csv --out results/quick

Produces:
  * a summary table per (method, payload) with means and 95% intervals;
  * the main figure: payload in bits per pixel against detectability;
  * a quality figure: payload against PSNR;
  * a robustness figure: attack against the fraction of recovered messages.
"""

from __future__ import annotations

import argparse
import os

import numpy as np
import pandas as pd


def ci95(values: np.ndarray) -> float:
    """Half-width of the 95% confidence interval of the mean."""
    data = np.asarray(values, dtype=float)
    data = data[np.isfinite(data)]
    if data.size < 2:
        return 0.0
    return float(1.96 * data.std(ddof=1) / np.sqrt(data.size))


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate the undistorted runs per method and payload."""
    clean = df[df["attack"] == "identity"]
    return clean.groupby(["method", "bpp_target"]).agg(
        n=("psnr_db", "size"),
        psnr_db=("psnr_db", "mean"), psnr_ci=("psnr_db", ci95),
        ssim=("ssim", "mean"), ssim_ci=("ssim", ci95),
        spa_stego=("spa_stego", "mean"), spa_ci=("spa_stego", ci95),
        spa_cover=("spa_cover", "mean"),
        change_rate=("change_rate", "mean"),
        efficiency=("embedding_efficiency", "mean"),
        recovered=("recovered", "mean"),
        t_embed_s=("t_embed_s", "mean"),
        t_extract_s=("t_extract_s", "mean"),
    ).reset_index()


def robustness(df: pd.DataFrame) -> pd.DataFrame:
    """Fraction of fully recovered messages per attack and method."""
    return df.pivot_table(index="attack", columns="method", values="recovered",
                          aggfunc="mean")


def _plot(path: str, draw) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7.2, 4.6), dpi=150)
    draw(ax)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    print(f"figure: {path}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("csv", help="results file written by benchmark.py")
    parser.add_argument("--out", default=None, help="prefix of the output files")
    args = parser.parse_args(argv)
    out = args.out or os.path.splitext(args.csv)[0]

    df = pd.read_csv(args.csv)
    if "error" in df:
        df = df[df["error"].isna() | (df["error"] == "")]

    summary = summarize(df)
    summary.to_csv(f"{out}.summary.csv", index=False)
    print(summary.to_string(index=False, float_format=lambda v: f"{v:.4f}"))

    rob = robustness(df)
    rob.to_csv(f"{out}.robustness.csv")
    print("\nfraction of fully recovered messages after each attack:")
    print(rob.to_string(float_format=lambda v: f"{v:.2f}"))

    def detectability(ax):
        for method, group in summary.groupby("method"):
            group = group.sort_values("bpp_target")
            ax.errorbar(group["bpp_target"], group["spa_stego"],
                        yerr=group["spa_ci"], marker="o", capsize=3, label=method)
        ax.axhline(summary["spa_cover"].mean(), color="grey", linestyle=":",
                   linewidth=1, label="clean cover")
        ax.set_xlabel("payload, bits per pixel")
        ax.set_ylabel("SPA estimate (detectability)")
        ax.set_title("Detectability at an equal payload")

    def quality(ax):
        for method, group in summary.groupby("method"):
            group = group.sort_values("bpp_target")
            ax.errorbar(group["bpp_target"], group["psnr_db"],
                        yerr=group["psnr_ci"], marker="o", capsize=3, label=method)
        ax.set_xlabel("payload, bits per pixel")
        ax.set_ylabel("PSNR, dB")
        ax.set_title("Image quality at an equal payload")

    def robust(ax):
        rob.plot(kind="bar", ax=ax)
        ax.set_ylabel("fraction of recovered messages")
        ax.set_xlabel("attack")
        ax.set_title("Robustness against image processing")
        ax.tick_params(axis="x", labelrotation=20, labelsize=7)

    try:
        _plot(f"{out}.detectability.png", detectability)
        _plot(f"{out}.quality.png", quality)
        _plot(f"{out}.robustness.png", robust)
    except ImportError:
        print("matplotlib is not installed, figures were skipped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
