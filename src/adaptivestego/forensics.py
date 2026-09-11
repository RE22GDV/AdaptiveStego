"""File-level steganography detection: what the bytes say before the pixels do.

The detectors in :mod:`analysis` look at pixel statistics, which is the right
tool for something hidden *in* the image. A great deal of what is called image
steganography in practice never touches a pixel: data is appended after the
end-of-image marker, parked in a metadata chunk, or hidden in the gap a BMP
header is allowed to leave before its pixel array. Every container format has
somewhere to put bytes that viewers ignore.

Those places are cheap to check and they are checked first here, because
finding a ZIP archive after a PNG's IEND chunk settles the question that no
amount of pixel statistics would have settled.

Nothing in this module needs the file to be a valid image, and nothing in it
decodes one: it reads bytes.
"""

from __future__ import annotations

import os
import struct
import zlib
from dataclasses import dataclass, field

import numpy as np

__all__ = ["Finding", "file_report", "full_report", "detect_format",
           "trailing_data", "embedded_signatures", "byte_entropy"]

# Magic numbers, longest first so that a longer match wins.
_FORMATS = [
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpeg"),
    (b"GIF89a", "gif"),
    (b"GIF87a", "gif"),
    (b"BM", "bmp"),
    (b"II*\x00", "tiff"),
    (b"MM\x00*", "tiff"),
    (b"RIFF", "webp"),
    (b"P5", "pgm"),
    (b"P6", "ppm"),
]

# Signatures of things that have no business being inside an image file. The
# offset zero occurrence of an image signature is the image itself, so these
# are only reported when they appear later in the file.
_PAYLOAD_SIGNATURES = [
    (b"PK\x03\x04", "zip archive (or a docx/xlsx/odt, which are zips)"),
    (b"Rar!\x1a\x07", "rar archive"),
    (b"7z\xbc\xaf\x27\x1c", "7-zip archive"),
    (b"\x1f\x8b\x08", "gzip stream"),
    (b"BZh9", "bzip2 stream"),
    (b"\xfd7zXZ\x00", "xz stream"),
    (b"%PDF-", "pdf document"),
    (b"SQLite format 3\x00", "sqlite database"),
    (b"MZ\x90\x00", "windows executable"),
    (b"\x7fELF", "elf executable"),
    (b"-----BEGIN ", "pem key or certificate block"),
    (b"\x89PNG\r\n\x1a\n", "a second png image"),
    (b"\xff\xd8\xff\xe0", "a second jpeg image"),
]

# PNG chunks a plain image needs. Anything else is not proof of anything -
# colour profiles and timestamps are ordinary - but it is where data goes.
_PNG_CRITICAL = {b"IHDR", b"PLTE", b"IDAT", b"IEND"}
_PNG_ORDINARY = {b"sRGB", b"gAMA", b"cHRM", b"pHYs", b"bKGD", b"tRNS", b"sBIT",
                 b"iCCP", b"tIME", b"hIST", b"acTL", b"fcTL", b"fdAT"}
_PNG_TEXT = {b"tEXt", b"zTXt", b"iTXt"}


@dataclass
class Finding:
    """One thing worth reporting about a file, with its weight."""

    kind: str
    detail: str
    severity: str = "note"         # note | suspicious | strong
    bytes_involved: int = 0
    offset: int = -1

    def as_dict(self) -> dict:
        return {"kind": self.kind, "detail": self.detail,
                "severity": self.severity,
                "bytes": self.bytes_involved, "offset": self.offset}


@dataclass
class FileReport:
    """Everything the file structure says, and what it adds up to."""

    path: str
    size: int
    format: str
    extension_matches: bool
    findings: list[Finding] = field(default_factory=list)

    @property
    def level(self) -> str:
        if any(f.severity == "strong" for f in self.findings):
            return "detected"
        if any(f.severity == "suspicious" for f in self.findings):
            return "suspicious"
        return "clean"

    def summary(self) -> dict:
        return {"path": self.path, "size": self.size, "format": self.format,
                "extension_matches": self.extension_matches,
                "level": self.level,
                "findings": [f.as_dict() for f in self.findings]}


def byte_entropy(data: bytes) -> float:
    """Shannon entropy of a byte string, in bits per byte.

    Compressed and encrypted data sit just under 8; text and structured data
    sit well below. It is the cheapest way to tell "this trailer is a comment"
    from "this trailer is a payload".
    """
    if not data:
        return 0.0
    counts = np.bincount(np.frombuffer(data, dtype=np.uint8), minlength=256)
    p = counts[counts > 0] / float(len(data))
    return float(-(p * np.log2(p)).sum())


def detect_format(data: bytes) -> str:
    """Identify the container format from its magic bytes."""
    for magic, name in _FORMATS:
        if data.startswith(magic):
            return name
    return "unknown"


# ---------------------------------------------------------------------------
# per-format structure walks
# ---------------------------------------------------------------------------
def _png_end(data: bytes) -> tuple[int, list[Finding]]:
    """Walk the chunk list; return where the image ends and what was odd."""
    findings: list[Finding] = []
    offset = 8
    seen_end = 0
    while offset + 8 <= len(data):
        (length,) = struct.unpack(">I", data[offset:offset + 4])
        kind = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + length]
        end = offset + 12 + length
        if end > len(data) or length > len(data):
            findings.append(Finding(
                "truncated chunk",
                f"chunk {kind.decode('latin-1')} at {offset} claims {length} "
                f"bytes but the file ends at {len(data)}",
                "suspicious", offset=offset))
            break

        stored_crc = data[offset + 8 + length:end]
        if len(stored_crc) == 4:
            actual = zlib.crc32(kind + payload) & 0xFFFFFFFF
            if struct.unpack(">I", stored_crc)[0] != actual:
                findings.append(Finding(
                    "bad chunk crc",
                    f"chunk {kind.decode('latin-1')} at {offset} does not "
                    f"match its own checksum, so it was edited in place",
                    "strong", length, offset))

        if kind in _PNG_TEXT:
            severity = "suspicious" if length > 512 else "note"
            findings.append(Finding(
                "metadata chunk",
                f"{kind.decode('latin-1')} holds {length} bytes of text "
                f"metadata, a standard place to hide a message",
                severity, length, offset))
        elif kind not in _PNG_CRITICAL and kind not in _PNG_ORDINARY:
            findings.append(Finding(
                "unknown chunk",
                f"chunk {kind.decode('latin-1')!r} is not part of the PNG "
                f"specification and carries {length} bytes",
                "suspicious" if length > 64 else "note", length, offset))

        offset = end
        if kind == b"IEND":
            seen_end = end
            break
    return seen_end or offset, findings


def _jpeg_end(data: bytes) -> tuple[int, list[Finding]]:
    """Walk the marker segments up to EOI."""
    findings: list[Finding] = []
    offset = 2
    while offset + 4 <= len(data):
        if data[offset] != 0xFF:
            break
        marker = data[offset + 1]
        if marker == 0xD9:                       # EOI
            return offset + 2, findings
        if marker == 0xDA:                       # start of scan: entropy coded
            scan = data.find(b"\xff\xd9", offset)
            return (scan + 2, findings) if scan >= 0 else (len(data), findings)
        if 0xD0 <= marker <= 0xD8 or marker == 0x01:
            offset += 2
            continue
        (length,) = struct.unpack(">H", data[offset + 2:offset + 4])
        if marker == 0xFE:                       # COM
            findings.append(Finding(
                "comment segment",
                f"a JPEG comment of {length - 2} bytes, a standard place to "
                f"hide a message",
                "suspicious" if length > 512 else "note", length - 2, offset))
        elif 0xE0 <= marker <= 0xEF and length > 8192:
            findings.append(Finding(
                "oversized application segment",
                f"APP{marker - 0xE0} carries {length - 2} bytes",
                "note", length - 2, offset))
        offset += 2 + length
    return len(data), findings


def _bmp_end(data: bytes) -> tuple[int, list[Finding]]:
    """BMP declares both its own size and where the pixels start."""
    findings: list[Finding] = []
    if len(data) < 34:
        return len(data), findings
    file_size, pixel_offset = struct.unpack("<I4xI", data[2:14])
    (dib_size,) = struct.unpack("<I", data[14:18])
    expected_start = 14 + dib_size
    if pixel_offset > expected_start:
        gap = pixel_offset - expected_start
        findings.append(Finding(
            "header gap",
            f"{gap} bytes sit between the BMP header and the pixel data, "
            f"where nothing needs to be",
            "strong" if gap > 16 else "note", gap, expected_start))
    end = file_size if 0 < file_size <= len(data) else len(data)
    return end, findings


def _gif_end(data: bytes) -> tuple[int, list[Finding]]:
    index = data.rfind(b"\x3b")
    return (index + 1 if index > 0 else len(data)), []


_WALKERS = {"png": _png_end, "jpeg": _jpeg_end, "bmp": _bmp_end, "gif": _gif_end}


def trailing_data(data: bytes, fmt: str) -> tuple[int, bytes, list[Finding]]:
    """Bytes that sit past the logical end of the image."""
    walker = _WALKERS.get(fmt)
    if walker is None:
        return len(data), b"", []
    end, findings = walker(data)
    return end, data[end:], findings


def embedded_signatures(data: bytes, skip: int = 16) -> list[Finding]:
    """Look for file signatures that appear somewhere after the header."""
    findings = []
    for magic, description in _PAYLOAD_SIGNATURES:
        index = data.find(magic, skip)
        if index >= 0:
            findings.append(Finding(
                "embedded file",
                f"the signature of a {description} appears at offset {index}",
                "strong", len(data) - index, index))
    return findings


# ---------------------------------------------------------------------------
# the file report
# ---------------------------------------------------------------------------
def file_report(path: str) -> FileReport:
    """Everything the container format gives away, without decoding pixels."""
    with open(path, "rb") as handle:
        data = handle.read()

    fmt = detect_format(data)
    extension = os.path.splitext(path)[1].lower().lstrip(".")
    aliases = {"jpg": "jpeg", "jpeg": "jpeg", "tif": "tiff", "tiff": "tiff"}
    expected = aliases.get(extension, extension)
    matches = fmt == expected or (fmt == "unknown" and not expected)

    report = FileReport(path=path, size=len(data), format=fmt,
                        extension_matches=matches)

    if not matches and fmt != "unknown":
        report.findings.append(Finding(
            "extension mismatch",
            f"the file is named .{extension} but its contents are {fmt}",
            "suspicious"))

    end, trailer, findings = trailing_data(data, fmt)
    report.findings.extend(findings)

    if trailer:
        entropy = byte_entropy(trailer)
        severity = "strong" if len(trailer) > 64 else "suspicious"
        report.findings.append(Finding(
            "appended data",
            f"{len(trailer)} bytes follow the end of the image at offset "
            f"{end}, entropy {entropy:.2f} bits/byte"
            + (" - compressed or encrypted" if entropy > 7.0 else ""),
            severity, len(trailer), end))

    report.findings.extend(embedded_signatures(data))
    return report


def full_report(path: str, *, key=None, password=None, grayscale: bool = False,
                scan_methods: bool = True, use_model: bool = True) -> dict:
    """File structure, pixel statistics, a trained model and a container scan.

    The order is deliberate: the cheap checks that give a definite answer run
    first, the statistics that give a probabilistic one run next, and the scan
    that tries this tool's own methods runs last. Each part reports its own
    level, and the overall level is the strongest of them, because these are
    different hiding places and finding nothing in one says nothing about the
    others.
    """
    from . import analysis, detector
    from .api import detect, scan
    from .image_io import read_image

    file_part = file_report(path)
    result = {"file": file_part.summary()}
    levels = [file_part.level]

    try:
        img = read_image(path, grayscale=grayscale)
    except Exception as exc:                     # not a decodable image
        result["pixels"] = {"error": str(exc)}
        result["level"] = file_part.level
        return result

    # A grayscale image stored as PNG comes back as three identical channels.
    # Collapsing it is not cosmetic: every detector below would otherwise run
    # three times on the same data and average three identical answers.
    if img.ndim == 3 and all(np.array_equal(img[:, :, 0], img[:, :, c])
                             for c in range(1, img.shape[2])):
        img = img[:, :, 0]

    result["image"] = {"height": int(img.shape[0]), "width": int(img.shape[1]),
                       "channels": 1 if img.ndim == 2 else int(img.shape[2])}
    pixels = analysis.quick_report(img)
    result["pixels"] = pixels
    levels.append(pixels["verdict"]["level"])

    # The trained detector is the only part of this that sees LSB matching,
    # and it is also the only part whose answer depends on where it was
    # trained, so it is reported separately and always with its provenance.
    model = detector.load() if use_model else None
    if model is not None:
        prediction = model.predict(img)
        result["model"] = prediction
        if prediction["probability"] > 0.9:
            levels.append("detected")
        elif prediction["stego"]:
            levels.append("suspicious")
    else:
        result["model"] = None

    if scan_methods:
        hits = scan(img, key=key, password=password)
        result["containers"] = hits
        if any(hit["readable"] for hit in hits):
            levels.append("detected")
        elif hits:
            levels.append("suspicious")
        # A container found by name is worth stating separately from a
        # statistical suspicion: it is not an estimate, the header is there.
        result["container_found"] = bool(hits)
    else:
        try:
            probe = detect(img, key=key, password=password)
            result["containers"] = [probe.summary()] if probe.found else []
            result["container_found"] = probe.found
            if probe.found:
                levels.append("detected" if probe.readable else "suspicious")
        except Exception as exc:                 # pragma: no cover - defensive
            result["containers"] = [{"error": str(exc)}]
            result["container_found"] = False

    order = {"clean": 0, "suspicious": 1, "detected": 2}
    result["level"] = max(levels, key=lambda name: order.get(name, 0))
    return result
