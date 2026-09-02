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

* [ ] **Syndrome coding (STC).** The main technical item. STC removes the
      decoder's dependence on the adaptive ranking and enables minimum-distortion
      embedding: the cost map exists only on the encoder side, the message is
      read as a syndrome over a fixed raster order, and a damaged sample no
      longer shifts the whole stream. STC is not itself an error-correcting
      code - after an attack the syndrome still changes, so robustness to local
      corruption comes from ECC on top and has to be measured experimentally.
* [ ] Turn the priority map into per-sample costs. STC needs a cost for each
      direction - rho+ for +1 and rho- for -1 - with the direction forbidden at
      0 and at 255 given wet cost. The order of samples becomes a fixed raster
      order, and the cost map is used by the encoder only.
* [ ] Verify the STC implementation, not just its round-trip: the syndrome must
      satisfy H y = m, and on short vectors (n <= 20) exhaustive search must
      confirm that the solution really is of minimum cost. Also test the 0 and
      255 boundaries, several trellis heights, embedding efficiency and the
      achieved total distortion.
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
