# Threat model and limitations

This page lists what the tool does **not** do. For research work that matters
more than the feature list.

## Threat model

**What is protected.** The fact that a message was sent (steganography) and,
separately, its content (cryptography, when a password is given).

**The adversary** sees the image and knows the algorithm (Kerckhoffs's
principle) but not the position key and not the password. Two cases differ:

* a *passive* adversary only tries to decide whether a message is present;
* an *active* adversary processes the image to destroy any message.

**Against an active adversary this method does not work.** Any LSB embedding in
the spatial domain is destroyed by JPEG re-encoding, by rescaling and even by
weak noise. The test suite asserts this explicitly
(`test_jpeg_destroys_lsb_message`).

## Robustness limits

| Processing | Result |
|---|---|
| PNG/BMP left untouched | the message is recovered in full |
| a few corrupted samples | repaired by `--ecc 8` and above, but only for the non-adaptive methods |
| Gaussian noise with sigma >= 0.3 | the message is lost |
| JPEG at any quality | the message is lost |
| rescaling, rotation, cropping | the message is lost |

### Why the adaptive methods are the least robust

The receiver rebuilds the order of positions by recomputing the complexity map
from the stego image itself. That removes the need for side information, but it
also makes the order globally fragile: the order is produced by a sort, so if a
single sample lands in a different quantisation band after an attack, every
subsequent bit shifts and nothing decodes - even when only one bit was actually
damaged. Raising `map_mask_bits` (building the map from higher bits) does not
help; that was measured, not assumed.

**The right fix is syndrome coding** - wet paper codes and syndrome-trellis
codes (STC) - where the message is recovered from a syndrome over all positions
and does not depend on which samples were modified. That is how WOW and
S-UNIWARD work, and it is the next major step for this bench (see
[roadmap.md](roadmap.md)).

## Detectability limits

* `sequential` is trivially detected by chi-square and SPA. It exists only as a
  baseline.
* LSB replacement (`replace`) is vulnerable to SPA and RS analysis regardless of
  the order of positions. `matching` (+/-1) is free of those attacks but not of
  modern neural detectors.
* The classical detectors in `adaptivestego.analysis` are a weak baseline. A claim
  that a method is "less detectable" only holds against an SRNet-class detector
  trained on the same images and the same payload.
* Capacity and detectability are linked: methods may only be compared at an
  **equal** payload in bits per pixel.

## Cryptographic limits

* A password on the command line is visible in the process list. Use
  `--password` without a value (it will be prompted) or `--password-env`.
* Steganography does not replace encryption: without `--password` the content
  is stored in the clear and anyone who knows the method and the position key
  can read it.
* The position key (`--key`) is not an encryption key. It only decides where the
  bits go.

## Reproducibility limits

* The order of positions depends on the complexity map, so every map
  computation is integer arithmetic (see `src/adaptivestego/maps.py`). The one place
  that could involve floating point - the entropy table - is computed with the
  `decimal` module and rounded to integers, which is identical on every
  platform.
* The keyed generator is built on the raw Philox stream and a permutation
  implemented here, because `numpy.random.Generator` methods are explicitly
  allowed to change between releases.
* `python -m adaptivestego selftest` prints a digest of every deterministic
  component. Two machines that print the same digest can exchange stego images.
* Images must be stored in a lossless format. `write_image` refuses to write
  JPEG and verifies the written file byte by byte.
