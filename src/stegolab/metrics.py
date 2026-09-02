"""Quality, recovery and capacity metrics."""

from __future__ import annotations

import numpy as np

__all__ = ["mse", "psnr", "ssim", "max_abs_diff", "change_rate",
           "embedding_efficiency", "ber", "quality_report"]


def _f(img: np.ndarray) -> np.ndarray:
    return np.asarray(img, dtype=np.float64)


def mse(cover: np.ndarray, stego: np.ndarray) -> float:
    """Mean squared error between two images."""
    d = _f(cover) - _f(stego)
    return float(np.mean(d * d))


def psnr(cover: np.ndarray, stego: np.ndarray, peak: float = 255.0) -> float:
    """Peak signal-to-noise ratio in dB; infinite for identical images."""
    err = mse(cover, stego)
    if err == 0.0:
        return float("inf")
    return float(10.0 * np.log10(peak * peak / err))


def _ssim_channel(a: np.ndarray, b: np.ndarray, peak: float) -> float:
    """Single-channel SSIM with an 11x11 Gaussian window (Wang et al., 2004)."""
    import cv2

    c1, c2 = (0.01 * peak) ** 2, (0.03 * peak) ** 2
    win, sigma = (11, 11), 1.5
    mu_a = cv2.GaussianBlur(a, win, sigma)
    mu_b = cv2.GaussianBlur(b, win, sigma)
    mu_aa, mu_bb, mu_ab = mu_a * mu_a, mu_b * mu_b, mu_a * mu_b
    var_a = cv2.GaussianBlur(a * a, win, sigma) - mu_aa
    var_b = cv2.GaussianBlur(b * b, win, sigma) - mu_bb
    cov = cv2.GaussianBlur(a * b, win, sigma) - mu_ab
    num = (2 * mu_ab + c1) * (2 * cov + c2)
    den = (mu_aa + mu_bb + c1) * (var_a + var_b + c2)
    return float(np.mean(num / den))


def ssim(cover: np.ndarray, stego: np.ndarray, peak: float = 255.0) -> float:
    """Structural similarity averaged over the colour channels."""
    a, b = _f(cover), _f(stego)
    if a.shape != b.shape:
        raise ValueError(f"shape mismatch: {a.shape} vs {b.shape}")
    if a.ndim == 2:
        return _ssim_channel(a, b, peak)
    return float(np.mean([_ssim_channel(a[:, :, c], b[:, :, c], peak)
                          for c in range(a.shape[2])]))


def max_abs_diff(cover: np.ndarray, stego: np.ndarray) -> int:
    """Largest absolute change of any single sample."""
    return int(np.max(np.abs(_f(cover) - _f(stego))))


def change_rate(cover: np.ndarray, stego: np.ndarray) -> float:
    """Fraction of samples that changed."""
    return float(np.count_nonzero(cover != stego) / cover.size)


def embedding_efficiency(n_bits: int, cover: np.ndarray, stego: np.ndarray) -> float:
    """Message bits carried per changed sample; higher is better."""
    changed = int(np.count_nonzero(cover != stego))
    return float(n_bits / changed) if changed else float("inf")


def ber(original: bytes, recovered: bytes) -> float:
    """Bit error rate; missing bytes count as fully erroneous."""
    a = np.frombuffer(original, dtype=np.uint8)
    b = np.frombuffer(recovered, dtype=np.uint8)
    n = max(a.size, b.size)
    if n == 0:
        return 0.0
    a = np.pad(a, (0, n - a.size))
    b = np.pad(b, (0, n - b.size))
    return float(np.unpackbits(np.bitwise_xor(a, b)).mean())


def quality_report(cover: np.ndarray, stego: np.ndarray,
                   n_bits: int | None = None) -> dict:
    """Distortion metrics for one cover/stego pair."""
    report = {
        "mse": mse(cover, stego),
        "psnr_db": psnr(cover, stego),
        "ssim": ssim(cover, stego),
        "max_abs_diff": max_abs_diff(cover, stego),
        "change_rate": change_rate(cover, stego),
    }
    if n_bits is not None:
        report["bits"] = int(n_bits)
        report["bpp"] = n_bits / (cover.shape[0] * cover.shape[1])
        report["embedding_efficiency"] = embedding_efficiency(n_bits, cover, stego)
    return report
