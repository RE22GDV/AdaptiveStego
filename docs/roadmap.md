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
* [ ] RS analysis and calibrated features (SPAM, SRM) as a stronger baseline
* [ ] parallel execution over images (multiprocessing)

## Stage 3 - the scientific part

* [ ] **Syndrome coding (STC).** The main technical item: it would let the
      adaptive method survive localised damage and brings the bench in line with
      modern algorithms. Today the position order is globally fragile
      (see [limitations.md](limitations.md)).
* [ ] A WOW / S-UNIWARD style cost function and a comparison against them at an
      equal payload (Binghamton DDE Lab implementations).
* [ ] SRNet as the detector: trained on cover/stego pairs, reported as accuracy,
      ROC-AUC and P_E. An RTX 4090 is enough for BOSSBase.
* [ ] Runs on BOSSBase 1.01 and ALASKA#2 with splits by image and by camera.
* [ ] Ablation over maps, channels, embedding depth and quantisation.
* [ ] Three seeds, confidence intervals, significance testing.

## Stage 4 - publication

* [ ] the hypothesis and the protocol frozen before the final runs
* [ ] tables and the main figure: payload (bpp) against detection probability
* [ ] code, configurations, seeds and model weights published with the paper
* [ ] a DOI through Zenodo and a filled-in `CITATION.cff`

## Possible directions afterwards

* a learned embedding map trained against a steganalyser
  (encoder / decoder / steganalyser in an adversarial setup);
* embedding in a transform domain (DCT/DWT) for robustness against JPEG;
* identifying the algorithm and estimating the payload size, not only detecting
  that a message exists.
