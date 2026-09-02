"""Image loading and saving with the checks steganography actually needs."""

from __future__ import annotations

import os

import cv2
import numpy as np

from .exceptions import StegoError

__all__ = ["LOSSLESS_EXT", "read_image", "write_image", "is_lossless"]

# Formats that preserve the lowest bits. JPEG and lossy WEBP destroy a message.
LOSSLESS_EXT = {".png", ".bmp", ".tif", ".tiff", ".ppm", ".pgm", ".pnm"}


def is_lossless(path: str) -> bool:
    """Whether the file extension denotes a lossless image format."""
    return os.path.splitext(path)[1].lower() in LOSSLESS_EXT


def read_image(path: str, *, grayscale: bool = False) -> np.ndarray:
    """Read an image as uint8 RGB (H, W, 3), or (H, W) when grayscale.

    ``imdecode`` is used instead of ``imread`` because ``imread`` cannot open
    paths containing non-ASCII characters on Windows.
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(f"file not found: {path}")
    try:
        raw = np.fromfile(path, dtype=np.uint8)
    except OSError as exc:
        raise StegoError(f"cannot read file: {path}") from exc
    flag = cv2.IMREAD_GRAYSCALE if grayscale else cv2.IMREAD_COLOR
    img = cv2.imdecode(raw, flag)
    if img is None:
        raise StegoError(f"cannot decode image: {path}")
    if img.ndim == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    return np.ascontiguousarray(img)


def write_image(path: str, img: np.ndarray, *, allow_lossy: bool = False,
                verify: bool = True) -> str:
    """Write an image and verify that the file matches what was written.

    ``cv2.imwrite`` silently returns False on failure and a lossy format
    silently destroys the embedded data, so both cases are checked explicitly.
    """
    ext = os.path.splitext(path)[1].lower()
    if not ext:
        raise StegoError("the destination path has no file extension")
    if not allow_lossy and ext not in LOSSLESS_EXT:
        raise StegoError(
            f"format {ext} does not preserve the lowest bits, the message "
            f"would be lost. Use one of: {', '.join(sorted(LOSSLESS_EXT))}")

    data = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    ok, buf = cv2.imencode(ext, data)
    if not ok:
        raise StegoError(f"cv2.imencode failed for format {ext}")

    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    buf.tofile(path)

    if verify and ext in LOSSLESS_EXT:
        back = read_image(path, grayscale=img.ndim == 2)
        if back.shape != img.shape or not np.array_equal(back, img):
            raise StegoError(
                f"write verification failed: {path} differs from the data "
                f"that was written")
    return path
