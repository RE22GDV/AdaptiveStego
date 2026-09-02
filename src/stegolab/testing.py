"""Synthetic cover images for tests and demonstrations.

Real experiments run on BOSSBase or ALASKA#2, but unit tests and examples need
a reproducible cover that does not require downloading anything.
"""

from __future__ import annotations

import cv2
import numpy as np

__all__ = ["synthetic_cover"]


def synthetic_cover(height: int = 256, width: int = 256, *, seed: int = 0,
                    channels: int = 3) -> np.ndarray:
    """Build an image with smooth gradients, hard edges and texture.

    This mimics the one property of a photograph that matters here: flat areas
    where any change is visible sit next to textured areas where changes hide.
    """
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float64)

    base = 90 + 60 * np.sin(xx / 37.0) + 40 * np.cos(yy / 53.0)
    base += 50 * ((xx / width) ** 2)                      # smooth gradient

    texture = rng.normal(0, 18, (height, width))
    texture = cv2.GaussianBlur(texture, (0, 0), 1.1)
    band = (yy > height * 0.55).astype(np.float64)        # textured half
    base += texture * band

    base[int(height * 0.15):int(height * 0.35),
         int(width * 0.10):int(width * 0.45)] = 200.0     # flat rectangle

    img = np.clip(base, 0, 255).astype(np.uint8)
    if channels == 1:
        return img
    out = np.stack([img,
                    np.clip(base * 0.92 + 8, 0, 255).astype(np.uint8),
                    np.clip(base * 1.05 - 6, 0, 255).astype(np.uint8)], axis=2)
    return np.ascontiguousarray(out)
