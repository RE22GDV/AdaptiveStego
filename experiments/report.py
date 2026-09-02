#!/usr/bin/env python3
"""Summary tables and plots for the output of benchmark.py.

    python experiments/report.py results/main.csv --out results/main

Produces:
  * a summary per (method, payload) with cluster bootstrap intervals;
  * a paired comparison of every method against a baseline;
  * the main figure: payload in bits per pixel against detectability;
  * a quality figure and a robustness figure.

Confidence intervals treat one cover as one observation, not one embedding run
(see experiments/stats.py for why).
"""

from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from stats import cluster_summary, paired_comparison  # noqa: E402

METRICS = [("spa_stego", "SPA detectability"), ("psnr_db", "PSNR, dB"),
           ("ssim", "SSIM"), ("change_rate", "changed samples"),
           ("embedding_efficiency", "bits per change"),
           ("t_embed_s", "embed, s"), ("t_extract_s", "extract, s")]


def build_summary(df: pd.DataFrame) -> pd.DataFrame:
    """One row per (method, payload) with a bootstrap interval per metric."""
    clean = df[df["attack"] == "identity"]
    by = ["method", "bpp_target"]
    out = None
    for column, _label in METRICS:
        if column not in clean:
            continue
        part = cluster_summary(clean, column, by).rename(columns={
            "mean": column, "ci_low": f"{column}_lo", "ci_high": f"{column}_hi"})
        keep = [*by, column, f"{column}_lo", f"{column}_hi"]
        if out is None:
            out = part[[*keep, "n_clusters", "n_runs"]]
        else:
            out = out.merge(part[keep], on=by, how="outer")
    return out.sort_values(by).reset_index(drop=True)


def robustness(df: pd.DataFrame) -> pd.DataFrame:
    """Fraction of fully recovered payloads per attack and method."""
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
    parser.add_argument("--baseline", default="random",
                        help="method the others are compared against")
    args = parser.parse_args(argv)
    out = args.out or os.path.splitext(args.csv)[0]

    df = pd.read_csv(args.csv)
    if "error" in df:
        df = df[df["error"].isna() | (df["error"] == "")]

    summary = build_summary(df)
    summary.to_csv(f"{out}.summary.csv", index=False)
    columns = ["method", "bpp_target", "n_clusters", "n_runs", "spa_stego",
               "spa_stego_lo", "spa_stego_hi", "psnr_db", "ssim"]
    print("summary (95% cluster bootstrap over covers):")
    print(summary[[c for c in columns if c in summary]].to_string(
        index=False, float_format=lambda v: f"{v:.4f}"))

    clean = df[df["attack"] == "identity"]
    paired = paired_comparison(clean, "spa_stego", args.baseline,
                               within=["bpp_target"])
    paired.to_csv(f"{out}.paired.csv", index=False)
    print(f"\npaired against {args.baseline!r}, differences in SPA per cover "
          f"(negative means less detectable):")
    print(paired.to_string(index=False, float_format=lambda v: f"{v:.4f}"))

    rob = robustness(df)
    rob.to_csv(f"{out}.robustness.csv")
    print("\nfraction of fully recovered payloads after each attack:")
    print(rob.to_string(float_format=lambda v: f"{v:.2f}"))

    def detectability(ax):
        for method, group in summary.groupby("method"):
            group = group.sort_values("bpp_target")
            lower = group["spa_stego"] - group["spa_stego_lo"]
            upper = group["spa_stego_hi"] - group["spa_stego"]
            ax.errorbar(group["bpp_target"], group["spa_stego"],
                        yerr=[lower, upper], marker="o", capsize=3, label=method)
        ax.axhline(clean["spa_cover"].mean(), color="grey", linestyle=":",
                   linewidth=1, label="clean cover")
        ax.set_xlabel("payload, bits per pixel")
        ax.set_ylabel("SPA estimate (detectability)")
        ax.set_title("Detectability at an equal payload")

    def quality(ax):
        for method, group in summary.groupby("method"):
            group = group.sort_values("bpp_target")
            lower = group["psnr_db"] - group["psnr_db_lo"]
            upper = group["psnr_db_hi"] - group["psnr_db"]
            ax.errorbar(group["bpp_target"], group["psnr_db"],
                        yerr=[lower, upper], marker="o", capsize=3, label=method)
        ax.set_xlabel("payload, bits per pixel")
        ax.set_ylabel("PSNR, dB")
        ax.set_title("Image quality at an equal payload")

    def robust(ax):
        rob.plot(kind="bar", ax=ax)
        ax.set_ylabel("fraction of recovered payloads")
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
