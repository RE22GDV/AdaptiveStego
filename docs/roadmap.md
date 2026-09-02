# Roadmap

## Stage 1 - a working foundation (done)

* [x] library separated from the interface; the original script kept in `legacy/`
* [x] UTF-8 instead of `ord(ch):08b`, lengths in bytes, arbitrary `bytes` payloads
* [x] the ASG1 container: magic, version, flags, header CRC, message CRC
* [x] zlib, AES-256-GCM with scrypt, Reed-Solomon
* [x] keyed placement that is reproducible across machines and numpy versions
* [x] adaptive embedding driven by a complexity map, with no side information
* [x] argparse CLI, honest capacity checks and verified file writes
* [x] a test suite that runs both under pytest and standalone

## Stage 2 - the research bench (mostly done)

* [x] six embedding methods behind one registry
* [x] PSNR, SSIM, BER, embedding efficiency and timing
* [x] twelve attacks with deterministic seeds
* [x] classical steganalysis: chi-square, SPA, bit-plane statistics
* [x] `benchmark.py` writing CSV/JSON, `report.py` producing tables and figures
* [x] `performance.py` measuring speed and memory
* [x] desktop interface in English, Ukrainian and Russian
* [x] `selftest` digest proving two installations are interoperable
* [x] research mode: raw payloads with no container, for algorithm comparison
* [x] per-case embedding keys and payloads derived from the cover content
* [x] cluster bootstrap and paired comparisons instead of pseudo-replicated CIs
* [x] exact capacity accounting, including the Reed-Solomon block expansion
* [ ] RS analysis and calibrated features (SPAM, SRM) as a stronger baseline
* [ ] validate the chi-square and SPA implementations against published vectors
* [ ] parallel execution over images (multiprocessing)

## Stage 3 - the scientific part

Order of work, because several items depend on the ones before them:
STC and its verification, then a cost pipeline comparable with WOW and
S-UNIWARD, then a smoke run on 100-200 BOSSBase images, then freezing the
protocol, then the full dataset, and only then training a detector on it.

* [x] **Syndrome coding (STC).** Implemented in `stc.py` and exposed as the
      `stc` method. The cost map exists only on the encoder side, the message
      is the syndrome over a fixed raster order, and the decoder needs nothing
      but the dimensions, the key and the trellis height. It is not an
      error-correcting code: after an attack the syndrome still changes, so
      robustness comes from ECC on top and remains to be measured.
* [x] Per-direction costs in `costs.py`: rho+ and rho- from the complexity map,
      with the forbidden direction at 0 and 255 given wet cost and ties in
      direction broken by a keyed coin.
* [x] Verification beyond round-trip: the syndrome constraint is checked
      directly, linearity of H is checked, and on vectors short enough to
      enumerate the trellis result is compared against brute force over all
      2^n candidates - with and without wet samples. Boundary values, several
      trellis heights, embedding efficiency and the achieved distortion all
      have their own tests.
* [ ] Measure whether ECC on top of syndrome coding restores the message after
      localised damage. This is the open question the previous item raises.
* [ ] Let syndrome coding carry the application container by transmitting the
      payload length separately (today `stc` is research mode only).
* [ ] A WOW / S-UNIWARD style cost function and a comparison against them at an
      equal payload (Binghamton DDE Lab implementations).
* [ ] SRNet as the detector: trained on cover/stego pairs, reported as accuracy,
      ROC-AUC and P_E. An RTX 4090 is enough for BOSSBase.
* [ ] Runs on BOSSBase 1.01 and ALASKA#2 with splits by image and by camera.
* [ ] Ablation over maps, channels, embedding depth and quantisation.
* [ ] One independent embedding realisation per cover on the full dataset;
      cluster bootstrap and paired tests for the final comparisons.

## Stage 4 - publication

* [ ] the hypothesis and the protocol frozen before the final runs
* [ ] tables and the main figure: payload (bpp) against detection probability
* [ ] code, configurations, master keys and model weights published with the paper
* [ ] the environment frozen through `requirements-lock.txt` and the `Dockerfile`
* [ ] `CITATION.cff` completed with the author's full name, affiliation and ORCID
* [ ] a DOI through Zenodo

## Possible directions afterwards

* a learned embedding map trained against a steganalyser
  (encoder / decoder / steganalyser in an adversarial setup);
* embedding in a transform domain (DCT/DWT) for robustness against JPEG;
* identifying the algorithm and estimating the payload size, not only detecting
  that a message exists.
