# Finding hidden data

`adaptivestego detect -i suspect.png` runs four independent stages. They look
in different places, and a clean result from one says nothing about the
others, so all four run and each reports its own level. The overall level is
the strongest of them.

    1. file structure    bytes outside the image           definite
    2. pixel statistics  LSB replacement, by four detectors  estimate
    3. trained model     LSB matching and adaptive embedding probability
    4. container scan    this tool's own ASG1 container      definite

## 1. File structure

Most of what is called image steganography in the wild never touches a pixel.
Every image format has room for bytes a viewer ignores, and that room is
checked first because finding a ZIP archive after a PNG's IEND chunk settles
the question that no amount of pixel statistics would have settled.

| Check | What it catches |
| --- | --- |
| Bytes after the logical end of the image | `cat secret.zip >> photo.png`, the single most common trick |
| PNG `tEXt` / `zTXt` / `iTXt` chunks | a message parked in metadata |
| PNG chunks not in the specification | a private chunk carrying data |
| PNG chunk checksums | a chunk edited in place |
| JPEG comment segments, oversized APPn | the same idea in JPEG |
| The gap a BMP header may leave before its pixels | a hiding place the format permits outright |
| File signatures found anywhere past the header | an embedded archive, PDF, executable or key |
| Extension against magic bytes | `secret.png` renamed to `holiday.jpg` |

Trailing data is reported with its entropy, which separates a leftover comment
from a payload: compressed or encrypted bytes sit just under 8 bits per byte.

This stage needs no decoding and works on a file that is not a valid image at
all.

## 2. Pixel statistics

Four detectors, each with a different failure mode:

| Detector | Estimates | Sees |
| --- | --- | --- |
| chi-square (Westfeld & Pfitzmann 1999) | probability the lowest plane is levelled | sequential LSB replacement |
| SPA (Dumitrescu, Wu & Wang 2003) | fraction of changed samples | LSB replacement |
| RS (Fridrich, Goljan & Du 2001) | fraction of changed samples | LSB replacement |
| WS (Fridrich & Goljan 2004; Ker & Böhme 2008) | fraction of changed samples | LSB replacement, best at low payloads |
| HCF-COM (Ker 2005) | how far the histogram was smoothed | reported, not scored - see below |

The first four all exploit one structural flaw: LSB *replacement* makes a
pixel's value depend on the bit written into it, so the pairs (2k, 2k+1) drift
together. LSB *matching* has no such flaw - it adds ±1 - and all four are
blind to it by construction. That is not a shortcoming to be tuned away; it is
why stage 3 exists.

### Thresholds

Measured on 150 BOSSBase images that no shipped model was trained on
(`experiments/calibrate_detectors.py --skip 5000`):

| Detector | mean on clean | 99th pct | fires on clean |
| --- | --- | --- | --- |
| SPA | 0.009 | 0.072 | 0.7 % |
| RS | 0.010 | 0.072 | 0.7 % |
| WS | 0.005 | 0.046 | 0.0 % |
| chi-square, p > 0.9 anywhere | – | – | **22 %** |
| chi-square, sequential shape | – | – | 1.3 % |
| HCF ratio < 0.92 | 0.952 | 1.198 | **29 %** |

Two consequences, both visible in the code:

* A rate over **0.08** counts toward the verdict; it is above all three 99th
  percentiles. Two detectors agreeing is called detection, one alone is called
  suspicious.
* **chi-square and HCF are reported but not scored.** A high chi-square
  probability somewhere in the image happens on more than a fifth of clean
  photographs, and an HCF ratio below 0.92 on nearly a third. Only the
  *sequential shape* of chi-square - high at the start of the image, low at
  the end - is specific enough to count.

At these settings 0.7 % of clean BOSSBase images are called detected and 2.0 %
are not called clean.

## 3. The trained detector

SPAM features (Pevný, Bas & Fridrich 2010) with Fisher's linear discriminant:
686 numbers describing local pixel dependencies, and one linear direction
through them. It is the standard pre-neural baseline, it is 18 KB, and it runs
in about 15 ms per 512×512 image.

The shipped model was trained on the **first 5 000** BOSSBase images against
four methods at three payloads. Held-out performance, on images it never saw:

| Method | 0.1 bpp | 0.2 bpp | 0.4 bpp |
| --- | --- | --- | --- |
| random LSB | 0.833 | 0.891 | 0.990 |
| LSB matching | 0.844 | 0.932 | 0.946 |
| adaptive LSB | 0.580 | 0.670 | 0.818 |
| adaptive matching | 0.589 | 0.705 | 0.893 |

(area under the ROC curve; overall 0.803)

Read the LSB matching row against stage 2, which fires on 2–7 % of the same
images - the false-positive rate. That gap is the whole reason the model is
here.

Read the adaptive rows too: at 0.1 bpp the model is close to chance. Content-
adaptive embedding at a low payload is not detected by anything in this
repository, and saying otherwise would be the easiest way to publish something
false. Training SRNet is the next step on the roadmap.

**A model is only valid for what it was trained on.** Every model file carries
its provenance - dataset, method, payload, held-out AUC, and a digest of the
image list - and every prediction reports it. A model trained on 512×512
grayscale photographs says nothing useful about a screenshot.

Train your own:

```bash
python experiments/train_detector.py --images "data/bossbase/*.pgm" \
    --limit 5000 --method matching adaptive-matching random adaptive \
    --bpp 0.1 0.2 0.4 --jobs 16
```

## 4. Container scan

If the data was hidden with this tool, the ASG1 container can simply be found.
Extraction needs the method, the bit depth and the key to match, and none of
them are stored in the image - but the method and the bit depth can be
searched, which is usually the difference between "there is nothing here" and
"there is something here and I had the wrong settings".

```bash
adaptivestego scan -i suspect.png            # every method, every bit depth
adaptivestego scan -i suspect.png --key mine # ...with a key to try
```

The key cannot be searched. That is what it is for.

## Detection before decryption

Extraction is two phases, and they are separately available:

```bash
adaptivestego detect  -i stego.png --key mine   # what is there?
adaptivestego extract -i stego.png --key mine   # ...and read it
```

`detect` never needs a password and never raises when there is nothing there.
It reports the container size, the message size, whether the payload is
compressed, whether error correction is on, and whether a password is needed.
`extract` runs the same phase first, prints what it found, and asks for a
password only once it knows one is required.

For a container packed with `--no-key-material` there is no flag to read, so
the answer is inferred: the payload does not read as a message, and its length
is exactly a plaintext plus a 16-byte GCM tag. The report says which of the
two kinds of answer it is - `encrypted` when the header says so, and
`encryption_suspected` when it was inferred.

## What a clean verdict means

That these tools found nothing. Content-adaptive embedding at a low payload,
and anything hidden by a method not in this repository, can pass all four
stages. The report says what it checked and why it concluded what it did, so
the right response to "clean" is to read the reasons, not to stop looking.
