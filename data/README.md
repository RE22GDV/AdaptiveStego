# Datasets

Datasets are not committed. This directory holds the scripts that fetch them
and, once fetched, the images themselves - which git ignores.

## BOSSBase 1.01

10 000 uncompressed 512x512 grayscale images, about 1.6 GB compressed. The
standard benchmark for spatial-domain steganography.

```bash
python data/download_bossbase.py
python experiments/benchmark.py --config configs/bossbase.json       # 200 images
python experiments/benchmark.py --config configs/bossbase-full.json  # all 10 000
```

The download script writes `data/bossbase/manifest.json` with the image count
and a digest of the whole collection, so a published result can state exactly
which files produced it.

## ALASKA#2

Tens of thousands of colour images from more than forty cameras, much closer to
real photographs than BOSSBase. Not scripted yet; see docs/roadmap.md.

## Your own photographs

Point the benchmark at any directory of lossless images:

```bash
python experiments/benchmark.py --images "path/to/*.png" --jobs 0 --out results/mine
```

For a dataset of your own, split by camera as well as by image, and remove
duplicates first: two byte-identical covers derive the same experiment key.
