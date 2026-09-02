# Experimental protocol

## Running

```bash
# quick check that the bench works, on synthetic covers
python experiments/benchmark.py --synthetic 8 --out results/quick
python experiments/report.py results/quick.csv

# the main run on a dataset
python experiments/benchmark.py --images "data/bossbase/*.pgm" --grayscale \
    --payloads 0.05 0.1 0.2 0.4 --seeds 3 --out results/bossbase
python experiments/report.py results/bossbase.csv

# speed and memory
python experiments/performance.py --out results/performance
```

Every run writes `*.csv` (raw rows) and `*.meta.json` (the full command line,
the library version, the key and the seeds). `report.py` adds `*.summary.csv`,
`*.robustness.csv` and three PNG figures.

Reusable configurations live in `configs/`:

```bash
python experiments/benchmark.py --config configs/quick.json
```

## Output columns

| Column | Meaning |
|---|---|
| `image`, `method`, `bpp_target`, `seed`, `attack` | key of the row |
| `recovered` | 1 when the message came back byte for byte |
| `ber` | bit error rate (1.0 when extraction failed) |
| `message_bytes`, `container_bytes` | message and container sizes |
| `bpp_actual`, `bpp_max` | payload used and the capacity of the method |
| `change_rate` | fraction of samples that changed |
| `psnr_db`, `ssim`, `max_abs_diff` | distortion of the cover |
| `embedding_efficiency` | message bits per changed sample |
| `spa_cover`, `spa_stego` | SPA estimate before and after embedding |
| `chi2_cover`, `chi2_stego` | chi-square probability before and after |
| `t_embed_s`, `t_extract_s` | embedding and extraction time |

## Rules that make a run scientific

1. **Equal payload.** Methods are only compared at the same `bpp_target`. The
   message is random bytes so that text entropy cannot influence the result,
   and compression is disabled during experiments.
2. **Data splitting.** Train, validation and test are split **by source
   photograph**, and for a private dataset also by camera. A cover and its stego
   version must end up in the same split, otherwise a detector simply memorises
   the image.
3. **Repeats.** At least three seeds; tables report the mean and the 95%
   confidence interval (`report.py` computes both).
4. **The protocol is frozen before the final runs.** The list of methods,
   payloads, metrics and the data split do not change after results are seen.
5. **Baselines are mandatory.** `sequential` and `random` are the lower bound,
   `matching` is the honest competitor. A publication also needs a comparison
   against WOW and S-UNIWARD (the Binghamton DDE Lab implementations).

## Datasets

| Dataset | What it is | Role |
|---|---|---|
| BOSSBase 1.01 | 10 000 uncompressed 512x512 grayscale images | the classical benchmark |
| ALASKA#2 | tens of thousands of colour images from 40+ cameras | closer to real photographs |
| Own photographs | your own camera or phone | transfer to an unseen camera |

The datasets themselves are not committed. `data/` holds download scripts, and
the results record the checksums of the files that were used.

## Ablation study

Each factor is varied on its own:

* the map: `--map sobel | laplacian | variance | entropy | highfreq | chroma | combined`;
* the value of keyed placement: `--method sequential` against `--method random`;
* embedding depth: `--bits 1` against `--bits 2`;
* channels: `--channels 2` against all three;
* map coarseness: `--band-bits 2..10` and `--map-mask-bits`;
* how a bit is written: `--mode replace` against `--mode match`.

```bash
for map in sobel variance entropy highfreq combined; do
  python experiments/benchmark.py --synthetic 20 --methods adaptive \
      --map $map --payloads 0.1 0.2 0.4 --seeds 3 --out results/ablation-$map
done
```
