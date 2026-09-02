"""Attacks on the container: image processing applied after embedding.

Used by the robustness experiments: a stego image is passed through a
distortion, then the bit error rate and the fraction of fully recovered
messages are measured. Every attack is deterministic for a given seed.
"""

from __future__ import annotations

import cv2
import numpy as np

__all__ = ["ATTACKS", "attack_names", "apply_attack", "parse_spec"]


def _u8(x: np.ndarray) -> np.ndarray:
    return np.clip(x, 0, 255).astype(np.uint8)


def identity(img: np.ndarray) -> np.ndarray:
    """No change at all (control case)."""
    return img.copy()


def jpeg(img: np.ndarray, quality: int = 90) -> np.ndarray:
    """Re-encode the image as JPEG and decode it back."""
    data = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    ok, buf = cv2.imencode(".jpg", data, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    if not ok:
        raise RuntimeError("JPEG encoding failed")
    flag = cv2.IMREAD_GRAYSCALE if img.ndim == 2 else cv2.IMREAD_COLOR
    back = cv2.imdecode(buf, flag)
    return back if img.ndim == 2 else cv2.cvtColor(back, cv2.COLOR_BGR2RGB)


def gaussian_noise(img: np.ndarray, sigma: float = 2.0, seed: int = 0) -> np.ndarray:
    """Add zero-mean Gaussian noise."""
    rng = np.random.default_rng(seed)
    return _u8(img.astype(np.float64) + rng.normal(0.0, sigma, img.shape))


def salt_pepper(img: np.ndarray, p: float = 0.01, seed: int = 0) -> np.ndarray:
    """Set a fraction p of the samples to black or white."""
    rng = np.random.default_rng(seed)
    out = img.copy()
    r = rng.random(img.shape)
    out[r < p / 2] = 0
    out[r > 1 - p / 2] = 255
    return out


def resize(img: np.ndarray, scale: float = 0.5) -> np.ndarray:
    """Downscale the image and scale it back to the original size."""
    h, w = img.shape[:2]
    small = cv2.resize(img, (max(int(w * scale), 1), max(int(h * scale), 1)),
                       interpolation=cv2.INTER_AREA)
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)


def crop_pad(img: np.ndarray, keep: float = 0.9) -> np.ndarray:
    """Keep the central region and pad the border back with zeros."""
    h, w = img.shape[:2]
    ch, cw = int(h * keep), int(w * keep)
    y0, x0 = (h - ch) // 2, (w - cw) // 2
    out = np.zeros_like(img)
    out[y0:y0 + ch, x0:x0 + cw] = img[y0:y0 + ch, x0:x0 + cw]
    return out


def brightness(img: np.ndarray, delta: int = 10) -> np.ndarray:
    """Shift every sample by a constant."""
    return _u8(img.astype(np.int16) + int(delta))


def contrast(img: np.ndarray, alpha: float = 1.1) -> np.ndarray:
    """Scale contrast around mid grey."""
    return _u8((img.astype(np.float64) - 128.0) * alpha + 128.0)


def gaussian_blur(img: np.ndarray, sigma: float = 0.6) -> np.ndarray:
    """Blur the image with a Gaussian kernel."""
    return cv2.GaussianBlur(img, (0, 0), sigma)


def median(img: np.ndarray, ksize: int = 3) -> np.ndarray:
    """Median filter, a classic way to wipe out LSB noise."""
    return cv2.medianBlur(img, int(ksize))


def quantize(img: np.ndarray, levels: int = 128) -> np.ndarray:
    """Reduce the number of intensity levels."""
    step = 256 / int(levels)
    return _u8(np.floor(img.astype(np.float64) / step) * step)


def pixel_drop(img: np.ndarray, p: float = 0.01, seed: int = 0) -> np.ndarray:
    """Replace a fraction p of the samples with random values (data loss)."""
    rng = np.random.default_rng(seed)
    out = img.copy()
    mask = rng.random(img.shape) < p
    out[mask] = rng.integers(0, 256, size=int(mask.sum()), dtype=np.uint8)
    return out


ATTACKS = {
    "identity": identity,
    "jpeg": jpeg,
    "noise": gaussian_noise,
    "salt_pepper": salt_pepper,
    "resize": resize,
    "crop": crop_pad,
    "brightness": brightness,
    "contrast": contrast,
    "blur": gaussian_blur,
    "median": median,
    "quantize": quantize,
    "drop": pixel_drop,
}


def attack_names() -> list[str]:
    """Names of every registered attack."""
    return list(ATTACKS)


def parse_spec(spec: str) -> tuple[str, dict]:
    """Parse "jpeg:quality=90" or "noise:sigma=2,seed=1" into name and kwargs."""
    name, _, rest = spec.partition(":")
    name = name.strip()
    if name not in ATTACKS:
        raise ValueError(f"unknown attack {name!r}; available: {', '.join(ATTACKS)}")
    kwargs: dict = {}
    for part in filter(None, (p.strip() for p in rest.split(","))):
        key, _, val = part.partition("=")
        key = key.strip()
        try:
            kwargs[key] = int(val)
        except ValueError:
            kwargs[key] = float(val)
    return name, kwargs


def apply_attack(img: np.ndarray, spec: str) -> np.ndarray:
    """Apply the attack described by a specification string."""
    name, kwargs = parse_spec(spec)
    return ATTACKS[name](img, **kwargs)
