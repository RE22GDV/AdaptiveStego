# Experimental protocol

## Two embedding modes

| Mode | What is embedded | Use it for |
|---|---|---|
| `research` (default) | exactly `bpp x pixels` pseudo-random bits, no header | comparing algorithms, including against WOW and S-UNIWARD |
| `application` | the full ASG1 container: header, CRC, optional AES-GCM and ECC | measuring the tool as a user would experience it |

The container carries a fixed signature, flags and checksums. Those constant
bytes are part of the stego signal, which is fine for the application and wrong
for an algorithm comparison: it is a variable that belongs to the file format,
not to the embedding method. In research mode 0.4 bpp means exactly `0.4N`
bits of payload, not "whatever is left after subtracting a header".

## Every case gets its own key and its own payload

```
case_id       = SHA-256(cover bytes + shape + replicate index)
embedding key = HMAC-SHA256(master key, "placement/" + case_id)
payload       = HMAC-SHA256(master key, "payload/"   + case_id) -> Philox stream
```

With one fixed key and one fixed payload, every image of the same size receives
the same positions and the same bits, so all stego images share one spatial
pattern. A neural detector trained on such data learns the pattern instead of
the algorithm, and the reported accuracy is meaningless. The methods most
distorted by this would be `random` and `matching`, whose whole point is that
placement is key dependent.

The derivation is content addressed, so it survives renaming the files and is
identical on any machine; the entire dataset regenerates from one `--master-key`.
Two byte-identical covers do map to the same case, which is the correct
behaviour for a deduplicated dataset - remove duplicates before a real run.

## Running

```bash
# quick check that the bench works
python experiments/benchmark.py --synthetic 8 --out results/quick
python experiments/report.py results/quick.csv

# the main run on a dataset
python experiments/benchmark.py --config configs/bossbase.json        # 200 images, smoke
python experiments/benchmark.py --config configs/bossbase-full.json   # all 10 000
python experiments/report.py results/bossbase-full.csv

# ablation over the complexity maps, and speed
python experiments/ablation.py --synthetic 12 --seeds 3 --out results
python experiments/performance.py --out results/performance
python experiments/figures.py

# validate the ported cost models against MATLAB (once, see matlab/README.md)
python experiments/make_cost_vectors.py
matlab -batch "run('matlab/dump_reference_costs.m')"
python experiments/validate_costs.py
```

Images are processed in parallel with `--jobs N` (`0` uses every core), and the
steganalysis of a cover is computed once per image rather than once per case.
`--no-steganalysis` drops the chi-square and SPA columns, which cost about a
quarter of a run and say nothing about the +/-1 methods; the quality and
recovery columns are unaffected.

Measured on 32 processes, 512x512 grayscale covers, nine methods and four
payloads: 62 seconds for 32 covers, so roughly 6 minutes for a 200 image smoke
run and 5.4 hours for all of BOSSBase. The syndrome-coded methods dominate at
about 15 seconds per cover against 0.2 to 2.8 seconds for the ordering codecs.

Every run writes `*.csv` (raw rows) and `*.meta.json` (the full command line,
the library version, the master key, the mode and the seeds). `report.py` adds
`*.summary.csv`, `*.paired.csv`, `*.robustness.csv` and three figures.

## Output columns

| Column | Meaning |
|---|---|
| `image`, `case_id`, `method`, `bpp_target`, `seed`, `mode`, `attack` | key of the row |
| `recovered` | 1 when the payload came back exactly |
| `ber` | bit error rate (1.0 when extraction failed) |
| `payload_bits` | bits actually written into the image |
| `container_bytes` | container size (application mode) |
| `bpp_actual`, `bpp_max` | payload used and the capacity of the method |
| `change_rate` | fraction of samples that changed |
| `psnr_db`, `ssim`, `max_abs_diff` | distortion of the cover |
| `embedding_efficiency` | payload bits per changed sample |
| `spa_cover`, `spa_stego` | SPA estimate before and after embedding |
| `chi2_cover`, `chi2_stego` | chi-square probability before and after |
| `t_embed_s`, `t_extract_s` | embedding and extraction time |

## Statistics

Replicates of the same cover are **not** independent observations: image
content dominates every metric here, so treating `images x replicates` as the
sample size shrinks the intervals and overstates the evidence. `report.py`
therefore

1. averages the replicates within each cover,
2. bootstraps over covers (10 000 resamples) for the confidence interval,
3. compares methods **paired on the cover**, since every method is run on the
   same images, and bootstraps the per-cover differences.

`n_clusters` in the summary is the real sample size; `n_runs` is reported only
to show how much computation stands behind a number. For a large dataset such
as full BOSSBase, one independent embedding realisation per cover is preferable
to several replicates of a few covers.

## Rules that make a run scientific

1. **Equal payload.** Methods are compared only at the same `bpp_target`, in
   research mode, with pseudo-random incompressible payloads.
2. **Data splitting.** Train, validation and test are split **by source
   photograph**, and for a private dataset also by camera. A cover and its
   stego versions must land in the same split, otherwise a detector simply
   memorises the image.
3. **Independent realisations.** Keys and payloads are derived per case, as
   above. Never reuse one key across a dataset.
4. **The protocol is frozen before the final runs.** The methods, payloads,
   metrics and data split do not change after results are seen.
5. **Baselines are mandatory.** `sequential` and `random` are the lower bound,
   `matching` the honest competitor, `uniform` the ablation control, and `wow`
   and `uniward` the published references. The last two share the syndrome
   coder with `stc`, so a comparison against them varies the cost model and
   nothing else.
6. **Hold the coder fixed.** Comparing an ordering codec against a
   syndrome-coded one changes two things at once. The scientific comparison is
   `stc` against `wow` against `uniward`; the ordering codecs are baselines.

## Datasets

| Dataset | What it is | Role |
|---|---|---|
| BOSSBase 1.01 | 10 000 uncompressed 512x512 grayscale images | the classical benchmark |
| ALASKA#2 | tens of thousands of colour images from 40+ cameras | closer to real photographs |
| Own photographs | your own camera or phone | transfer to an unseen camera |

The datasets are not committed. `data/` holds download scripts, and the results
record the checksums of the files that were used.

## Reproducing the environment

`requirements-lock.txt` pins every direct and transitive dependency, and the
`Dockerfile` builds an image from it. Timings depend on the machine; every
other column is deterministic and must match on any installation whose
`python -m adaptivestego selftest` digest agrees with the reference one.
