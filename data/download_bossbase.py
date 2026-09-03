#!/usr/bin/env python3
"""Fetch BOSSBase 1.01 and verify what arrived.

    python data/download_bossbase.py                 # download and extract
    python data/download_bossbase.py --verify-only   # check an existing copy

BOSSBase 1.01 is 10 000 uncompressed 512x512 grayscale images, about 1.6 GB
compressed. It is the standard benchmark for spatial-domain steganography, and
the experiments in this repository expect it under data/bossbase/.

The dataset is not redistributed here. This script only fetches it from the
Binghamton DDE Lab, and it writes a manifest of what it got so that a published
result can name the exact files it used.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(ROOT, "data", "bossbase")
ARCHIVE_URL = "http://dde.binghamton.edu/download/ImageDB/BOSSbase_1.01.zip"
EXPECTED_IMAGES = 10_000


def download(url: str, destination: str) -> str:
    """Stream the archive to disk, reporting progress."""
    print(f"downloading {url}")
    print(f"        to {destination}")

    def report(block: int, block_size: int, total: int) -> None:
        if total <= 0:
            return
        done = min(block * block_size, total)
        percent = 100.0 * done / total
        print(f"\r  {done / 1e6:7.1f} / {total / 1e6:.1f} MB  ({percent:5.1f} %)",
              end="", flush=True)

    urllib.request.urlretrieve(url, destination, report)  # noqa: S310
    print()
    return destination


def extract(archive: str, target: str) -> None:
    """Unpack the archive, flattening whatever directory it uses."""
    import zipfile

    os.makedirs(target, exist_ok=True)
    print(f"extracting into {target}")
    with zipfile.ZipFile(archive) as zf:
        members = [m for m in zf.namelist() if m.lower().endswith(".pgm")]
        for index, member in enumerate(members, 1):
            name = os.path.basename(member)
            with zf.open(member) as source, open(os.path.join(target, name), "wb") as out:
                out.write(source.read())
            if index % 500 == 0:
                print(f"\r  {index} / {len(members)}", end="", flush=True)
    print(f"\r  {len(members)} images")


def manifest(target: str) -> dict:
    """Record what is actually on disk, so a result can name its inputs."""
    names = sorted(n for n in os.listdir(target) if n.lower().endswith(".pgm"))
    digest = hashlib.sha256()
    sizes = []
    for name in names:
        path = os.path.join(target, name)
        with open(path, "rb") as f:
            data = f.read()
        digest.update(hashlib.sha256(data).digest())
        sizes.append(len(data))
    return {
        "n_images": len(names),
        "total_bytes": sum(sizes),
        "collection_sha256": digest.hexdigest(),
        "first": names[:3],
        "last": names[-3:],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--target", default=TARGET)
    parser.add_argument("--url", default=ARCHIVE_URL)
    parser.add_argument("--archive", default=None,
                        help="use an archive already on disk instead of downloading")
    parser.add_argument("--verify-only", action="store_true",
                        help="only check and describe what is already extracted")
    args = parser.parse_args(argv)

    if not args.verify_only:
        archive = args.archive
        if archive is None:
            os.makedirs(os.path.dirname(args.target), exist_ok=True)
            archive = os.path.join(os.path.dirname(args.target), "BOSSbase_1.01.zip")
            if not os.path.isfile(archive):
                download(args.url, archive)
            else:
                print(f"using the archive already at {archive}")
        extract(archive, args.target)

    if not os.path.isdir(args.target):
        print(f"nothing at {args.target}", file=sys.stderr)
        return 1

    report = manifest(args.target)
    path = os.path.join(args.target, "manifest.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(f"\n{report['n_images']} images, "
          f"{report['total_bytes'] / 1e9:.2f} GB")
    print(f"collection digest {report['collection_sha256']}")
    print(f"manifest written to {path}")
    if report["n_images"] != EXPECTED_IMAGES:
        print(f"\nwarning: expected {EXPECTED_IMAGES} images", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
