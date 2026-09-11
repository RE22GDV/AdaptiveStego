"""Desktop interface for adaptivestego, built on tkinter.

Tkinter ships with CPython on Windows and macOS, so the application runs with
no dependencies beyond the library itself. On some Linux distributions the Tk
bindings live in a separate package (``python3-tk`` on Debian and Ubuntu,
``python3-tkinter`` on Fedora); :func:`main` reports that clearly instead of
failing with an import traceback.

Long operations run in a worker thread and report back through a queue, so the
window never freezes while an image is being processed.
"""

from __future__ import annotations

import base64
import csv
import os
import queue
import threading
import time
import traceback

import numpy as np

from . import analysis, forensics, i18n, metrics
from .api import (
    capacity,
    detect,
    embed,
    embed_raw,
    extract,
    extract_raw,
    payload_bits_for_bpp,
)
from .codecs import codec_names, get_codec
from .exceptions import StegoError
from .image_io import LOSSLESS_EXT, read_image, write_image
from .maps import MAP_KINDS
from .testing import synthetic_cover

__all__ = ["main", "AdaptiveStegoApp"]

_ = i18n.translate

IMAGE_FILETYPES = [
    ("Images", "*.png *.bmp *.tif *.tiff *.ppm *.pgm *.jpg *.jpeg"),
    ("PNG", "*.png"),
    ("All files", "*.*"),
]
LOSSLESS_FILETYPES = [
    ("PNG", "*.png"),
    ("BMP", "*.bmp"),
    ("TIFF", "*.tif *.tiff"),
    ("All files", "*.*"),
]
TEXT_FILETYPES = [("Text files", "*.txt"), ("All files", "*.*")]

PREVIEW_SIDE = 170


def container_methods() -> list[str]:
    """Methods that can be used with the self-describing container.

    Syndrome coding needs the payload length in advance, so it has no header
    to discover and only appears in the benchmark, which sets the length.
    """
    return [name for name in codec_names() if not get_codec(name).syndrome_coded]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _to_photo(img: np.ndarray, max_side: int = PREVIEW_SIDE):
    """Convert a numpy image into a tkinter PhotoImage without needing PIL.

    Tk 8.6 accepts base64-encoded PNG data directly, so OpenCV can do the
    encoding and no extra imaging library is required.
    """
    import tkinter as tk

    import cv2

    if img.ndim == 2:
        data = img
    else:
        data = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    h, w = data.shape[:2]
    scale = min(max_side / max(h, w), 1.0)
    if scale < 1.0:
        data = cv2.resize(data, (max(int(w * scale), 1), max(int(h * scale), 1)),
                          interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".png", data)
    if not ok:  # pragma: no cover - encoding a valid array cannot fail
        raise RuntimeError("preview encoding failed")
    return tk.PhotoImage(data=base64.b64encode(buf.tobytes()))


def _change_map(cover: np.ndarray, stego: np.ndarray) -> np.ndarray:
    """Black and white map of the pixels that were modified."""
    diff = np.any(cover != stego, axis=2) if cover.ndim == 3 else cover != stego
    return (diff.astype(np.uint8) * 255)


def _format_bytes(n: int) -> str:
    """Human readable byte count."""
    for unit in ("B", "KiB", "MiB"):
        if n < 1024 or unit == "MiB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} MiB"


# ---------------------------------------------------------------------------
# the application
# ---------------------------------------------------------------------------
class AdaptiveStegoApp:
    """Main window with one tab per task."""

    def __init__(self, root, language: str | None = None):
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.ttk = ttk
        self.root = root

        i18n.set_language(language or i18n.load_preference())

        self._labels: list[tuple[object, str, str]] = []   # widget, key, option
        self._tabs: list[tuple[int, str]] = []             # tab index, key
        self._photos: dict[str, object] = {}               # keep references
        self._queue: queue.Queue = queue.Queue()
        self._bench_stop = threading.Event()
        self._bench_rows: list[dict] = []
        self._cover_cache: tuple[str, np.ndarray] | None = None

        root.title(_("app.title"))
        root.geometry("1100x880")
        root.minsize(960, 720)

        self._build_header()
        self._build_notebook()
        self._build_status()

        self.root.after(100, self._drain_queue)

    # -- small widget helpers ---------------------------------------------
    def _label(self, widget, key: str, option: str = "text"):
        """Register a widget so its text follows the selected language."""
        widget.configure(**{option: _(key)})
        self._labels.append((widget, key, option))
        return widget

    def _retranslate(self) -> None:
        self.root.title(_("app.title"))
        for widget, key, option in self._labels:
            try:
                widget.configure(**{option: _(key)})
            except Exception:  # pragma: no cover - destroyed widget
                continue
        for index, key in self._tabs:
            self.notebook.tab(index, text=_(key))
        self._refresh_bench_columns()
        self.set_status(_("common.ready"))

    # -- layout ------------------------------------------------------------
    def _build_header(self) -> None:
        ttk, tk = self.ttk, self.tk
        bar = ttk.Frame(self.root, padding=(10, 8, 10, 0))
        bar.pack(fill="x")

        title = ttk.Label(bar, text="AdaptiveStego", font=("", 15, "bold"))
        title.pack(side="left")

        self.language_var = tk.StringVar(value=i18n.get_language())
        combo = ttk.Combobox(bar, textvariable=self.language_var, width=12,
                             state="readonly",
                             values=list(i18n.available_languages().values()))
        combo.set(i18n.available_languages()[i18n.get_language()])
        combo.pack(side="right")
        combo.bind("<<ComboboxSelected>>", self._on_language_change)
        self._label(ttk.Label(bar), "common.language").pack(side="right", padx=(0, 6))

    def _build_notebook(self) -> None:
        ttk = self.ttk
        self.notebook = ttk.Notebook(self.root, padding=8)
        self.notebook.pack(fill="both", expand=True)

        for index, (key, builder) in enumerate([
            ("tab.embed", self._build_embed_tab),
            ("tab.extract", self._build_extract_tab),
            ("tab.analyze", self._build_analyze_tab),
            ("tab.benchmark", self._build_benchmark_tab),
            ("tab.about", self._build_about_tab),
        ]):
            frame = ttk.Frame(self.notebook, padding=8)
            self.notebook.add(frame, text=_(key))
            self._tabs.append((index, key))
            builder(frame)

    def _build_status(self) -> None:
        ttk, tk = self.ttk, self.tk
        bar = ttk.Frame(self.root, padding=(10, 0, 10, 8))
        bar.pack(fill="x")
        self.status_var = tk.StringVar(value=_("common.ready"))
        ttk.Label(bar, textvariable=self.status_var).pack(side="left")
        self.progress = ttk.Progressbar(bar, mode="determinate", length=220)
        self.progress.pack(side="right")

    def set_status(self, text: str) -> None:
        self.status_var.set(text)

    # -- reusable parameter block -----------------------------------------
    def _build_params(self, parent, prefix: str, *, with_ecc: bool):
        """Build the shared method/key/password block used by two tabs."""
        ttk, tk = self.ttk, self.tk
        box = ttk.LabelFrame(parent, padding=8)
        self._label(box, "common.options")

        state = {
            "method": tk.StringVar(value="adaptive"),
            "key": tk.StringVar(),
            "password": tk.StringVar(),
            "bits": tk.IntVar(value=1),
            "map": tk.StringVar(value="combined"),
            "band_bits": tk.IntVar(value=6),
            "ecc": tk.IntVar(value=0),
            "compress": tk.BooleanVar(value=True),
            "no_key_material": tk.BooleanVar(value=False),
            "grayscale": tk.BooleanVar(value=False),
            "channels": tk.StringVar(value=_("common.channels_all")),
        }

        rows = [
            ("common.method", ttk.Combobox(box, textvariable=state["method"],
                                           values=container_methods(),
                                           state="readonly", width=20)),
            ("common.key", ttk.Entry(box, textvariable=state["key"], width=22)),
            ("common.password", ttk.Entry(box, textvariable=state["password"],
                                          width=22, show="*")),
            ("common.bits", ttk.Combobox(box, textvariable=state["bits"],
                                         values=[1, 2, 3, 4], state="readonly",
                                         width=20)),
            ("common.map", ttk.Combobox(box, textvariable=state["map"],
                                        values=list(MAP_KINDS), state="readonly",
                                        width=20)),
            ("common.band_bits", ttk.Spinbox(box, from_=1, to=10, width=20,
                                             textvariable=state["band_bits"])),
            ("common.channels", ttk.Combobox(
                box, textvariable=state["channels"], state="readonly", width=20,
                values=[_("common.channels_all"), "0", "1", "2", "0,1", "0,2", "1,2"])),
        ]
        if with_ecc:
            rows.append(("common.ecc", ttk.Spinbox(box, from_=0, to=32, width=20,
                                                   textvariable=state["ecc"])))

        for row, (key, widget) in enumerate(rows):
            self._label(ttk.Label(box), key).grid(row=row, column=0, sticky="w",
                                                  pady=2, padx=(0, 8))
            widget.grid(row=row, column=1, sticky="ew", pady=2)

        row = len(rows)
        if with_ecc:
            self._label(ttk.Checkbutton(box, variable=state["no_key_material"]),
                        "common.no_key_material").grid(
                            row=row, column=0, columnspan=2, sticky="w",
                            pady=(6, 0))
            row += 1
            self._label(ttk.Label(box, foreground="#666", wraplength=230,
                                  justify="left"),
                        "common.no_key_material_hint").grid(
                            row=row, column=0, columnspan=2, sticky="w")
            row += 1
            self._label(ttk.Checkbutton(box, variable=state["compress"]),
                        "common.compress").grid(row=row, column=0, columnspan=2,
                                                sticky="w", pady=(6, 0))
            row += 1
        self._label(ttk.Checkbutton(box, variable=state["grayscale"]),
                    "common.grayscale").grid(row=row, column=0, columnspan=2,
                                             sticky="w")
        box.columnconfigure(1, weight=1)
        setattr(self, f"{prefix}_params", state)
        return box

    def _params_kwargs(self, prefix: str) -> dict:
        """Turn the widget state into keyword arguments for the API."""
        state = getattr(self, f"{prefix}_params")
        channels = state["channels"].get()
        kwargs = {
            "method": state["method"].get(),
            "key": state["key"].get() or None,
            "bits_per_sample": int(state["bits"].get()),
            "map_kind": state["map"].get(),
            "band_bits": int(state["band_bits"].get()),
        }
        if channels and channels != _("common.channels_all"):
            kwargs["channels"] = tuple(int(c) for c in channels.split(","))
        password = state["password"].get()
        if password:
            kwargs["password"] = password
        return kwargs

    # -- embed tab ---------------------------------------------------------
    def _build_embed_tab(self, parent) -> None:
        ttk, tk = self.ttk, self.tk
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(2, weight=1)

        self._label(ttk.Label(parent, font=("", 11, "bold")),
                    "embed.title").grid(row=0, column=0, columnspan=2,
                                        sticky="w", pady=(0, 8))

        files = ttk.Frame(parent)
        files.grid(row=1, column=0, columnspan=2, sticky="ew")
        files.columnconfigure(1, weight=1)

        self.embed_cover_var = tk.StringVar()
        self.embed_out_var = tk.StringVar()
        self._label(ttk.Label(files), "common.cover").grid(row=0, column=0, sticky="w")
        ttk.Entry(files, textvariable=self.embed_cover_var).grid(
            row=0, column=1, sticky="ew", padx=6)
        self._label(ttk.Button(files, command=self._pick_cover),
                    "common.browse").grid(row=0, column=2)

        self._label(ttk.Label(files), "common.output").grid(row=1, column=0,
                                                            sticky="w", pady=4)
        ttk.Entry(files, textvariable=self.embed_out_var).grid(
            row=1, column=1, sticky="ew", padx=6, pady=4)
        self._label(ttk.Button(files, command=self._pick_embed_output),
                    "common.save_as").grid(row=1, column=2, pady=4)

        self.embed_capacity_var = tk.StringVar(value="-")
        self._label(ttk.Label(files), "embed.capacity").grid(row=2, column=0,
                                                             sticky="w")
        ttk.Label(files, textvariable=self.embed_capacity_var).grid(
            row=2, column=1, sticky="w", padx=6)

        body = ttk.Frame(parent)
        body.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=8)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)

        message_box = ttk.LabelFrame(body, padding=8)
        self._label(message_box, "embed.message")
        message_box.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        message_box.columnconfigure(0, weight=1)
        message_box.rowconfigure(1, weight=1)

        self.embed_source = tk.StringVar(value="text")
        source_row = ttk.Frame(message_box)
        source_row.grid(row=0, column=0, sticky="w")
        self._label(ttk.Radiobutton(source_row, variable=self.embed_source,
                                    value="text", command=self._sync_embed_source),
                    "embed.from_text").pack(side="left")
        self._label(ttk.Radiobutton(source_row, variable=self.embed_source,
                                    value="file", command=self._sync_embed_source),
                    "embed.from_file").pack(side="left", padx=8)

        self.embed_text = tk.Text(message_box, height=7, wrap="word", undo=True)
        self.embed_text.grid(row=1, column=0, sticky="nsew", pady=6)

        file_row = ttk.Frame(message_box)
        file_row.grid(row=2, column=0, sticky="ew")
        file_row.columnconfigure(0, weight=1)
        self.embed_msgfile_var = tk.StringVar()
        self.embed_msgfile_entry = ttk.Entry(file_row,
                                             textvariable=self.embed_msgfile_var,
                                             state="disabled")
        self.embed_msgfile_entry.grid(row=0, column=0, sticky="ew")
        self.embed_msgfile_btn = self._label(
            ttk.Button(file_row, command=self._pick_message_file, state="disabled"),
            "common.browse")
        self.embed_msgfile_btn.grid(row=0, column=1, padx=6)

        side = ttk.Frame(body)
        side.grid(row=0, column=1, sticky="ns")
        self._build_params(side, "embed", with_ecc=True).pack(fill="x")
        self._label(ttk.Button(side, command=self._run_embed),
                    "embed.button").pack(fill="x", pady=8)

        preview = ttk.Frame(parent)
        preview.grid(row=3, column=0, columnspan=2, sticky="ew")
        self.embed_preview_cover = ttk.Label(preview)
        self.embed_preview_cover.grid(row=1, column=0, padx=(0, 10))
        self.embed_preview_changes = ttk.Label(preview)
        self.embed_preview_changes.grid(row=1, column=1, padx=10)
        self._label(ttk.Label(preview), "embed.preview_cover").grid(row=0, column=0,
                                                                    sticky="w")
        self._label(ttk.Label(preview), "embed.preview_changes").grid(row=0, column=1,
                                                                      sticky="w")
        self.embed_result_var = tk.StringVar()
        ttk.Label(preview, textvariable=self.embed_result_var,
                  justify="left").grid(row=1, column=2, sticky="nw", padx=10)
        self._label(ttk.Label(preview, foreground="#666"),
                    "embed.preview_hint").grid(row=2, column=0, columnspan=3,
                                               sticky="w", pady=(4, 0))

    def _sync_embed_source(self) -> None:
        use_file = self.embed_source.get() == "file"
        self.embed_text.configure(state="disabled" if use_file else "normal")
        state = "normal" if use_file else "disabled"
        self.embed_msgfile_entry.configure(state=state)
        self.embed_msgfile_btn.configure(state=state)

    def _pick_cover(self) -> None:
        from tkinter import filedialog

        path = filedialog.askopenfilename(filetypes=IMAGE_FILETYPES)
        if not path:
            return
        self.embed_cover_var.set(path)
        if not self.embed_out_var.get():
            stem, _ext = os.path.splitext(path)
            self.embed_out_var.set(f"{stem}-stego.png")
        self._update_capacity()

    def _pick_embed_output(self) -> None:
        from tkinter import filedialog

        path = filedialog.asksaveasfilename(defaultextension=".png",
                                            filetypes=LOSSLESS_FILETYPES)
        if path:
            self.embed_out_var.set(path)

    def _pick_message_file(self) -> None:
        from tkinter import filedialog

        path = filedialog.askopenfilename(filetypes=TEXT_FILETYPES)
        if path:
            self.embed_msgfile_var.set(path)

    def _load_cover(self) -> np.ndarray:
        path = self.embed_cover_var.get()
        gray = bool(self.embed_params["grayscale"].get())
        cache_key = f"{path}|{gray}"
        if self._cover_cache and self._cover_cache[0] == cache_key:
            return self._cover_cache[1]
        img = read_image(path, grayscale=gray)
        self._cover_cache = (cache_key, img)
        return img

    def _update_capacity(self) -> None:
        if not self.embed_cover_var.get():
            return
        try:
            img = self._load_cover()
            kwargs = self._params_kwargs("embed")
            info = capacity(
                img, password=kwargs.pop("password", None),
                ecc_nsym=int(self.embed_params["ecc"].get()),
                store_key_material=not bool(
                    self.embed_params["no_key_material"].get()),
                **kwargs)
            self.embed_capacity_var.set(
                f"{_format_bytes(info['message_bytes_max'])} "
                f"({info['bpp']:.2f} bpp, {img.shape[1]}x{img.shape[0]})")
            self._photos["cover"] = _to_photo(img)
            self.embed_preview_cover.configure(image=self._photos["cover"])
        except Exception as exc:                          # noqa: BLE001
            self.embed_capacity_var.set(f"{_('common.error')}: {exc}")

    def _run_embed(self) -> None:
        from tkinter import messagebox

        if not self.embed_cover_var.get():
            messagebox.showwarning(_("common.error"), _("embed.no_cover"))
            return
        if not self.embed_out_var.get():
            messagebox.showwarning(_("common.error"), _("embed.no_output"))
            return

        if self.embed_source.get() == "file":
            path = self.embed_msgfile_var.get()
            if not path or not os.path.isfile(path):
                messagebox.showwarning(_("common.error"), _("embed.no_message"))
                return
            with open(path, encoding="utf-8") as f:
                message = f.read()
        else:
            message = self.embed_text.get("1.0", "end-1c")
        if not message:
            messagebox.showwarning(_("common.error"), _("embed.no_message"))
            return

        kwargs = self._params_kwargs("embed")
        kwargs["ecc_nsym"] = int(self.embed_params["ecc"].get())
        kwargs["compress"] = bool(self.embed_params["compress"].get())
        hide_key_material = bool(self.embed_params["no_key_material"].get())
        if hide_key_material:
            if not kwargs.get("password"):
                messagebox.showwarning(_("common.error"),
                                       _("embed.no_key_material_needs_password"))
                return
            kwargs["store_key_material"] = False
        out_path = self.embed_out_var.get()

        def work():
            cover = self._load_cover()
            result = embed(cover, message, **kwargs)
            write_image(out_path, result.stego)
            report = metrics.quality_report(cover, result.stego,
                                            result.payload_bytes * 8)
            return {"result": result, "report": report, "cover": cover,
                    "path": out_path}

        self._run_async(work, self._embed_done)

    def _embed_done(self, data: dict) -> None:
        result, report = data["result"], data["report"]
        self._photos["changes"] = _to_photo(_change_map(data["cover"], result.stego))
        self.embed_preview_changes.configure(image=self._photos["changes"])
        self.embed_result_var.set(
            f"{_('embed.saved_to')}: {os.path.basename(data['path'])}\n"
            f"container: {_format_bytes(result.payload_bytes)}\n"
            f"payload: {result.bpp:.4f} bpp\n"
            f"changed: {result.change_rate * 100:.3f} %\n"
            f"PSNR: {report['psnr_db']:.2f} dB\n"
            f"SSIM: {report['ssim']:.5f}")
        self.set_status(_("embed.done"))

    # -- extract tab -------------------------------------------------------
    def _build_extract_tab(self, parent) -> None:
        ttk, tk = self.ttk, self.tk
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(3, weight=1)

        self._label(ttk.Label(parent, font=("", 11, "bold")),
                    "extract.title").grid(row=0, column=0, columnspan=2,
                                          sticky="w", pady=(0, 8))
        self._label(ttk.Label(parent, foreground="#666"),
                    "extract.hint").grid(row=1, column=0, columnspan=2, sticky="w")

        files = ttk.Frame(parent)
        files.grid(row=2, column=0, columnspan=2, sticky="ew", pady=8)
        files.columnconfigure(1, weight=1)
        self.extract_image_var = tk.StringVar()
        self._label(ttk.Label(files), "common.stego").grid(row=0, column=0, sticky="w")
        ttk.Entry(files, textvariable=self.extract_image_var).grid(
            row=0, column=1, sticky="ew", padx=6)
        self._label(ttk.Button(files, command=self._pick_stego),
                    "common.browse").grid(row=0, column=2)

        self.extract_info_var = tk.StringVar()
        ttk.Label(files, textvariable=self.extract_info_var,
                  foreground="#20548a").grid(row=1, column=0, columnspan=3,
                                             sticky="w", pady=(6, 0))

        body = ttk.Frame(parent)
        body.grid(row=3, column=0, columnspan=2, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)

        text_box = ttk.LabelFrame(body, padding=8)
        self._label(text_box, "common.result")
        text_box.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        text_box.columnconfigure(0, weight=1)
        text_box.rowconfigure(0, weight=1)
        self.extract_text = tk.Text(text_box, height=14, wrap="word")
        self.extract_text.grid(row=0, column=0, sticky="nsew")

        buttons = ttk.Frame(text_box)
        buttons.grid(row=1, column=0, sticky="w", pady=(6, 0))
        self._label(ttk.Button(buttons, command=self._save_extracted),
                    "extract.save").pack(side="left")
        self._label(ttk.Button(buttons, command=self._copy_extracted),
                    "common.copy").pack(side="left", padx=6)

        side = ttk.Frame(body)
        side.grid(row=0, column=1, sticky="ns")
        self._build_params(side, "extract", with_ecc=False).pack(fill="x")
        self._label(ttk.Button(side, command=self._run_extract),
                    "extract.button").pack(fill="x", pady=8)

    def _pick_stego(self) -> None:
        from tkinter import filedialog

        path = filedialog.askopenfilename(filetypes=IMAGE_FILETYPES)
        if path:
            self.extract_image_var.set(path)

    def _run_extract(self) -> None:
        """Phase one: find out what is in the image.

        Extraction is split in two so that the program can say what it found
        before it needs a password, and ask for one only when there is
        something there that needs it. Detection needs no password at all.
        """
        from tkinter import messagebox

        path = self.extract_image_var.get()
        if not path:
            messagebox.showwarning(_("common.error"), _("extract.no_image"))
            return
        kwargs = self._params_kwargs("extract")
        gray = bool(self.extract_params["grayscale"].get())
        self._extract_job = {"path": path, "kwargs": kwargs, "gray": gray}

        def work():
            img = read_image(path, grayscale=gray)
            return {"img": img, "probe": detect(img, **kwargs)}

        self._run_async(work, self._extract_detected)

    def _describe_probe(self, probe) -> str:
        """The detection result as one line of plain language."""
        if not probe.found:
            return _("extract.not_found")
        parts = [_("extract.found_size").format(
            container=_format_bytes(probe.container_bytes),
            message=_format_bytes(probe.message_bytes))]
        if probe.header is not None and probe.header.compressed:
            parts.append(_("extract.found_compressed"))
        if probe.encrypted:
            parts.append(_("extract.found_encrypted"))
        elif probe.encryption_suspected:
            parts.append(_("extract.found_maybe_encrypted"))
        if probe.header is not None and probe.header.ecc_nsym:
            parts.append(_("extract.found_ecc").format(n=probe.header.ecc_nsym))
        return " | ".join(parts)

    def _extract_detected(self, data: dict) -> None:
        """Phase two: ask for a password if one is needed, then decrypt."""
        from tkinter import messagebox, simpledialog

        probe = data["probe"]
        job = self._extract_job
        self.extract_info_var.set(self._describe_probe(probe))

        if not probe.found:
            self.set_status(_("extract.empty"))
            messagebox.showinfo(_("extract.not_found_title"),
                                _("extract.not_found_hint"))
            return

        kwargs = dict(job["kwargs"])
        if probe.needs_password and not kwargs.get("password"):
            password = simpledialog.askstring(
                _("extract.password_title"),
                _("extract.password_prompt_certain") if probe.encrypted
                else _("extract.password_prompt_suspected"),
                show="*", parent=self.root)
            if not password:
                self.set_status(_("extract.cancelled"))
                return
            kwargs["password"] = password

        img = data["img"]

        def work():
            try:
                return {"text": extract(img, **kwargs), "binary": False}
            except StegoError:
                # Not text, but the container opened: show it as bytes rather
                # than calling a successful extraction a failure.
                raw = extract(img, as_text=False, **kwargs)
                return {"text": repr(raw[:512]), "binary": True}

        self._run_async(work, self._extract_done)

    def _extract_done(self, data: dict) -> None:
        self.extract_text.delete("1.0", "end")
        self.extract_text.insert("1.0", data["text"])
        self.set_status(_("extract.binary") if data["binary"] else _("extract.done"))

    def _save_extracted(self) -> None:
        from tkinter import filedialog

        text = self.extract_text.get("1.0", "end-1c")
        if not text:
            return
        path = filedialog.asksaveasfilename(defaultextension=".txt",
                                            filetypes=TEXT_FILETYPES)
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            self.set_status(f"{_('embed.saved_to')}: {path}")

    def _copy_extracted(self) -> None:
        text = self.extract_text.get("1.0", "end-1c")
        self.root.clipboard_clear()
        self.root.clipboard_append(text)

    # -- analyse tab -------------------------------------------------------
    def _build_analyze_tab(self, parent) -> None:
        ttk, tk = self.ttk, self.tk
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(3, weight=1)

        self._label(ttk.Label(parent, font=("", 11, "bold")),
                    "analyze.title").grid(row=0, column=0, sticky="w", pady=(0, 8))

        files = ttk.Frame(parent)
        files.grid(row=1, column=0, sticky="ew")
        files.columnconfigure(1, weight=1)
        self.analyze_image_var = tk.StringVar()
        self.analyze_cover_var = tk.StringVar()
        self._label(ttk.Label(files), "common.image").grid(row=0, column=0, sticky="w")
        ttk.Entry(files, textvariable=self.analyze_image_var).grid(
            row=0, column=1, sticky="ew", padx=6)
        self._label(ttk.Button(files, command=lambda: self._pick_into(
            self.analyze_image_var)), "common.browse").grid(row=0, column=2)

        self._label(ttk.Label(files), "analyze.compare").grid(row=1, column=0,
                                                              sticky="w", pady=4)
        ttk.Entry(files, textvariable=self.analyze_cover_var).grid(
            row=1, column=1, sticky="ew", padx=6, pady=4)
        self._label(ttk.Button(files, command=lambda: self._pick_into(
            self.analyze_cover_var)), "common.browse").grid(row=1, column=2, pady=4)

        controls = ttk.Frame(parent)
        controls.grid(row=2, column=0, sticky="ew", pady=8)
        self._label(ttk.Button(controls, command=self._run_analyze),
                    "analyze.button").pack(side="left")
        self.analyze_scan_var = tk.BooleanVar(value=True)
        self._label(ttk.Checkbutton(controls, variable=self.analyze_scan_var),
                    "analyze.deep_scan").pack(side="left", padx=(12, 0))
        self._label(ttk.Label(controls), "common.key").pack(side="left",
                                                            padx=(12, 4))
        self.analyze_key_var = tk.StringVar()
        ttk.Entry(controls, textvariable=self.analyze_key_var,
                  width=16).pack(side="left")

        self.analyze_text = tk.Text(parent, wrap="none", height=18,
                                    font=("Courier New", 9))
        self.analyze_text.grid(row=3, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(parent, orient="vertical",
                               command=self.analyze_text.yview)
        scroll.grid(row=3, column=1, sticky="ns")
        self.analyze_text.configure(yscrollcommand=scroll.set)

    def _pick_into(self, var) -> None:
        from tkinter import filedialog

        path = filedialog.askopenfilename(filetypes=IMAGE_FILETYPES)
        if path:
            var.set(path)

    def _run_analyze(self) -> None:
        from tkinter import messagebox

        path = self.analyze_image_var.get()
        if not path:
            messagebox.showwarning(_("common.error"), _("extract.no_image"))
            return
        cover_path = self.analyze_cover_var.get()

        deep = bool(self.analyze_scan_var.get())
        key = self.analyze_key_var.get() or None

        def work():
            img = read_image(path)
            # One call does the whole chain: file structure, statistics, the
            # trained model and the container scan, each reporting its own
            # level. The GUI only lays out what comes back.
            full = forensics.full_report(path, key=key, scan_methods=deep)
            caps = {name: capacity(img, method=name)["message_bytes_max"]
                    for name in container_methods()}
            quality = None
            if cover_path and os.path.isfile(cover_path):
                cover = read_image(cover_path)
                if cover.shape == img.shape:
                    quality = metrics.quality_report(cover, img)
            return {"path": path, "shape": img.shape, "full": full,
                    "caps": caps, "quality": quality}

        self._run_async(work, self._analyze_done)

    _LEVEL_KEYS = {"clean": "analyze.level_clean",
                   "suspicious": "analyze.level_suspicious",
                   "detected": "analyze.level_detected"}

    def _analyze_done(self, data: dict) -> None:
        full = data["full"]
        report = full["pixels"]
        lines = [f"{os.path.basename(data['path'])}  "
                 f"{data['shape'][1]}x{data['shape'][0]}", ""]

        lines.append(f"== {_('analyze.overall')}: "
                     f"{_(self._LEVEL_KEYS[full['level']])} ==")
        lines.append("")

        # -- what the file structure says -------------------------------
        file_part = full["file"]
        lines.append(f"== {_('analyze.file_structure')} ==")
        lines.append(f"{_('analyze.format'):<34}{file_part['format']}")
        lines.append(f"{_('analyze.file_size'):<34}"
                     f"{_format_bytes(file_part['size'])}")
        if file_part["findings"]:
            for finding in file_part["findings"]:
                lines.append(f"  [{finding['severity']}] {finding['kind']}: "
                             f"{finding['detail']}")
        else:
            lines.append(f"  {_('analyze.file_clean')}")

        # -- the statistical detectors ----------------------------------
        lines += ["", f"== {_('analyze.detect')} =="]
        lines.append(f"{_('analyze.chi2'):<34}{report['chi2_p_max']:.4f}")
        lines.append(f"{_('analyze.spa'):<34}{report['spa_rate']:.4f}")
        lines.append(f"{_('analyze.rs'):<34}{report['rs_rate']:.4f}")
        lines.append(f"{_('analyze.ws'):<34}{report['ws_rate']:.4f}")
        lines.append(f"{_('analyze.hcf'):<34}{report['hcf_ratio']:.4f}")
        lines.append(f"{_('analyze.ones'):<34}{report['ones_ratio']:.4f}")
        lines.append(f"{_('analyze.autocorr'):<34}{report['autocorr_lag1']:+.4f}")

        verdict = report["verdict"]
        lines.append("")
        lines.append(f"{_('analyze.statistics_say')}: "
                     f"{_(self._LEVEL_KEYS[verdict['level']])}")
        for reason in verdict["reasons"]:
            lines.append(f"  + {reason}")
        for note in verdict.get("notes", []):
            lines.append(f"  . {note}")

        # -- the trained model ------------------------------------------
        model = full.get("model")
        lines += ["", f"== {_('analyze.model')} =="]
        if model is None:
            lines.append(f"  {_('analyze.model_missing')}")
        else:
            lines.append(f"{_('analyze.model_probability'):<34}"
                         f"{model['probability']:.3f}")
            lines.append(f"{_('analyze.model_trained')}:")
            lines.append(f"  {model['model']}")
            lines.append(f"{_('analyze.model_scope')}:")
            lines.append(f"  {model['valid_for']}")

        # -- containers --------------------------------------------------
        lines += ["", f"== {_('analyze.containers')} =="]
        hits = full.get("containers") or []
        if not hits:
            lines.append(f"  {_('analyze.containers_none')}")
        for hit in hits:
            state = (_("analyze.container_readable") if hit.get("readable")
                     else _("analyze.container_locked"))
            lines.append(f"  {hit.get('method')} / {hit.get('bits_per_sample')} "
                         f"bit: {_format_bytes(hit.get('container_bytes', 0))}, "
                         f"{state}")

        lines.append("")
        lines.append(_("analyze.verdict_hint"))

        if data["quality"]:
            quality = data["quality"]
            lines += ["", f"== {_('analyze.quality')} ==",
                      f"{'PSNR':<34}{quality['psnr_db']:.2f} dB",
                      f"{'SSIM':<34}{quality['ssim']:.5f}",
                      f"{'max abs diff':<34}{quality['max_abs_diff']}",
                      f"{'changed samples':<34}{quality['change_rate'] * 100:.3f} %"]

        lines += ["", f"== {_('analyze.capacity_table')} =="]
        for name, size in data["caps"].items():
            lines.append(f"{name:<34}{_format_bytes(size)}")

        self.analyze_text.delete("1.0", "end")
        self.analyze_text.insert("1.0", "\n".join(lines))
        self.set_status(_("common.ready"))

    # -- benchmark tab -----------------------------------------------------
    def _build_benchmark_tab(self, parent) -> None:
        ttk, tk = self.ttk, self.tk
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(3, weight=1)

        self._label(ttk.Label(parent, font=("", 11, "bold")),
                    "bench.title").grid(row=0, column=0, columnspan=2,
                                        sticky="w", pady=(0, 8))

        controls = ttk.Frame(parent)
        controls.grid(row=1, column=0, columnspan=2, sticky="ew")

        self.bench_source = tk.StringVar(value="synthetic")
        self._label(ttk.Radiobutton(controls, variable=self.bench_source,
                                    value="synthetic"),
                    "bench.synthetic").grid(row=0, column=0, sticky="w")
        self._label(ttk.Radiobutton(controls, variable=self.bench_source,
                                    value="folder"),
                    "bench.folder").grid(row=0, column=1, sticky="w", padx=8)
        self.bench_folder_var = tk.StringVar()
        ttk.Entry(controls, textvariable=self.bench_folder_var, width=32).grid(
            row=0, column=2, padx=6)
        self._label(ttk.Button(controls, command=self._pick_bench_folder),
                    "common.browse").grid(row=0, column=3)

        self.bench_count = tk.IntVar(value=4)
        self.bench_size = tk.IntVar(value=192)
        self.bench_payloads = tk.StringVar(value="0.05, 0.1, 0.2, 0.4")
        for col, (key, widget) in enumerate([
            ("bench.count", ttk.Spinbox(controls, from_=1, to=200, width=6,
                                        textvariable=self.bench_count)),
            ("bench.size", ttk.Spinbox(controls, from_=64, to=1024, increment=64,
                                       width=6, textvariable=self.bench_size)),
            ("bench.payloads", ttk.Entry(controls, textvariable=self.bench_payloads,
                                         width=20)),
        ]):
            self._label(ttk.Label(controls), key).grid(row=1, column=col * 2,
                                                       sticky="w", pady=6)
            widget.grid(row=1, column=col * 2 + 1, sticky="w", padx=6)

        buttons = ttk.Frame(parent)
        buttons.grid(row=2, column=0, columnspan=2, sticky="w", pady=4)
        self.bench_run_btn = self._label(ttk.Button(buttons, command=self._run_bench),
                                         "bench.run")
        self.bench_run_btn.pack(side="left")
        self._label(ttk.Button(buttons, command=self._bench_stop.set),
                    "bench.stop").pack(side="left", padx=6)
        self._label(ttk.Button(buttons, command=self._export_bench),
                    "bench.export").pack(side="left")

        columns = ("method", "bpp", "psnr", "ssim", "spa", "time", "recovered")
        self.bench_tree = ttk.Treeview(parent, columns=columns, show="headings",
                                       height=14)
        for col in columns:
            self.bench_tree.column(col, width=110, anchor="center")
        self.bench_tree.grid(row=3, column=0, sticky="nsew", pady=6)
        scroll = ttk.Scrollbar(parent, orient="vertical",
                               command=self.bench_tree.yview)
        scroll.grid(row=3, column=1, sticky="ns")
        self.bench_tree.configure(yscrollcommand=scroll.set)
        self._refresh_bench_columns()

        self._label(ttk.Label(parent, foreground="#666"),
                    "bench.hint").grid(row=4, column=0, sticky="w")

    def _refresh_bench_columns(self) -> None:
        if not hasattr(self, "bench_tree"):
            return
        headings = {
            "method": "bench.col_method", "bpp": "bench.col_bpp",
            "psnr": "bench.col_psnr", "ssim": "bench.col_ssim",
            "spa": "bench.col_spa", "time": "bench.col_time",
            "recovered": "bench.col_recovered",
        }
        for col, key in headings.items():
            self.bench_tree.heading(col, text=_(key))

    def _pick_bench_folder(self) -> None:
        from tkinter import filedialog

        path = filedialog.askdirectory()
        if path:
            self.bench_folder_var.set(path)
            self.bench_source.set("folder")

    def _run_bench(self) -> None:
        from tkinter import messagebox

        try:
            payloads = [float(p) for p in
                        self.bench_payloads.get().replace(";", ",").split(",")
                        if p.strip()]
        except ValueError:
            messagebox.showwarning(_("common.error"), _("bench.payloads"))
            return
        if not payloads:
            return

        if self.bench_source.get() == "folder":
            folder = self.bench_folder_var.get()
            paths = sorted(
                os.path.join(folder, name) for name in os.listdir(folder)
                if os.path.splitext(name)[1].lower() in LOSSLESS_EXT
            )[:int(self.bench_count.get())] if os.path.isdir(folder) else []
            if not paths:
                messagebox.showwarning(_("common.error"), _("bench.folder"))
                return
            images = [(os.path.basename(p), read_image(p)) for p in paths]
        else:
            size = int(self.bench_size.get())
            images = [(f"synthetic-{i}", synthetic_cover(size, size, seed=i))
                      for i in range(int(self.bench_count.get()))]

        methods = codec_names()
        self._bench_stop.clear()
        self._bench_rows = []
        for item in self.bench_tree.get_children():
            self.bench_tree.delete(item)
        total = len(images) * len(methods) * len(payloads)
        self.progress.configure(maximum=total, value=0)

        def work():
            # Raw payloads, exactly bpp x pixels bits, so the container header
            # does not become part of what is being compared, and so syndrome
            # coding can take part at all.
            from .prng import deterministic_bits

            rows = []
            done = 0
            for name, img in images:
                for bpp in payloads:
                    n_bits = payload_bits_for_bpp(img, bpp)
                    payload = deterministic_bits(f"gui/{name}/{bpp}", "payload",
                                                 n_bits)
                    for method in methods:
                        if self._bench_stop.is_set():
                            return {"rows": rows, "cancelled": True}
                        start = time.perf_counter()
                        result = embed_raw(img, payload, method=method,
                                           key="benchmark")
                        elapsed = (time.perf_counter() - start) * 1000.0
                        try:
                            recovered = np.array_equal(
                                extract_raw(result.stego, n_bits, method=method,
                                            key="benchmark"), payload)
                        except Exception:             # noqa: BLE001
                            recovered = False
                        rows.append({
                            "method": method, "bpp": bpp,
                            "psnr": metrics.psnr(img, result.stego),
                            "ssim": metrics.ssim(img, result.stego),
                            "spa": analysis.sample_pair_analysis(result.stego),
                            "time_ms": elapsed, "recovered": bool(recovered),
                        })
                        done += 1
                        self._queue.put(("progress", done))
            return {"rows": rows, "cancelled": False}

        self._run_async(work, self._bench_done)

    def _bench_done(self, data: dict) -> None:
        rows = data["rows"]
        grouped: dict[tuple[str, float], list[dict]] = {}
        for row in rows:
            grouped.setdefault((row["method"], row["bpp"]), []).append(row)

        self._bench_rows = []
        for (method, bpp), group in sorted(grouped.items(), key=lambda kv: (kv[0][1],
                                                                           kv[0][0])):
            summary = {
                "method": method,
                "bpp": bpp,
                "psnr_db": float(np.mean([r["psnr"] for r in group])),
                "ssim": float(np.mean([r["ssim"] for r in group])),
                "spa": float(np.mean([r["spa"] for r in group])),
                "embed_ms": float(np.mean([r["time_ms"] for r in group])),
                "recovered": float(np.mean([r["recovered"] for r in group])),
                "n": len(group),
            }
            self._bench_rows.append(summary)
            self.bench_tree.insert("", "end", values=(
                method, f"{bpp:g}", f"{summary['psnr_db']:.2f}",
                f"{summary['ssim']:.5f}", f"{summary['spa']:.4f}",
                f"{summary['embed_ms']:.1f}",
                f"{summary['recovered'] * 100:.0f} %"))
        self.set_status(_("bench.cancelled") if data["cancelled"] else _("bench.done"))

    def _export_bench(self) -> None:
        from tkinter import filedialog

        if not self._bench_rows:
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv",
                                            filetypes=[("CSV", "*.csv")])
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(self._bench_rows[0]))
            writer.writeheader()
            writer.writerows(self._bench_rows)
        self.set_status(f"{_('embed.saved_to')}: {path}")

    # -- about tab ---------------------------------------------------------
    def _build_about_tab(self, parent) -> None:
        ttk, tk = self.ttk, self.tk
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(5, weight=1)

        self._label(ttk.Label(parent, font=("", 12, "bold")),
                    "about.title").grid(row=0, column=0, sticky="w")
        self._label(ttk.Label(parent, wraplength=820, justify="left"),
                    "about.description").grid(row=1, column=0, sticky="w", pady=6)

        warning = ttk.LabelFrame(parent, padding=8)
        self._label(warning, "about.warning_title")
        warning.grid(row=2, column=0, sticky="ew", pady=6)
        self._label(ttk.Label(warning, wraplength=800, justify="left"),
                    "about.warning").pack(anchor="w")

        self._label(ttk.Label(parent, foreground="#666", wraplength=820,
                              justify="left"),
                    "about.selftest_hint").grid(row=3, column=0, sticky="w")
        self._label(ttk.Button(parent, command=self._run_selftest),
                    "about.selftest").grid(row=4, column=0, sticky="w", pady=6)

        self.about_text = tk.Text(parent, height=14, wrap="word",
                                  font=("Courier New", 9))
        self.about_text.grid(row=5, column=0, sticky="nsew")
        self._show_environment()

    def _show_environment(self) -> None:
        from . import __version__
        from .selftest import environment

        env = environment()
        lines = [f"adaptivestego {__version__}"]
        lines += [f"{key:<12}{value}" for key, value in env.items()]
        self.about_text.delete("1.0", "end")
        self.about_text.insert("1.0", "\n".join(lines))

    def _run_selftest(self) -> None:
        from .selftest import run_selftest

        def work():
            return run_selftest(verbose=False)

        def done(report):
            lines = [f"digest   {report['digest']}",
                     f"expected {report['expected']}",
                     f"match    {report['digest_matches']}", ""]
            lines += [f"{key:<12}{value}"
                      for key, value in report["environment"].items()]
            if report["problems"]:
                lines += [""] + [f"! {p}" for p in report["problems"]]
            self.about_text.delete("1.0", "end")
            self.about_text.insert("1.0", "\n".join(lines))
            self.set_status(_("common.ready"))

        self._run_async(work, done)

    # -- language ----------------------------------------------------------
    def _on_language_change(self, _event=None) -> None:
        names = i18n.available_languages()
        chosen = self.language_var.get()
        for code, name in names.items():
            if name == chosen:
                i18n.set_language(code)
                i18n.save_preference(code)
                break
        self._retranslate()

    # -- background work ---------------------------------------------------
    def _run_async(self, work, on_success) -> None:
        """Run ``work`` in a thread and call ``on_success`` in the UI thread."""
        self.set_status(_("common.working"))

        def runner():
            try:
                self._queue.put(("done", (on_success, work())))
            except Exception as exc:                      # noqa: BLE001
                self._queue.put(("error", (exc, traceback.format_exc())))

        threading.Thread(target=runner, daemon=True).start()

    def _drain_queue(self) -> None:
        from tkinter import messagebox

        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "progress":
                    self.progress.configure(value=payload)
                elif kind == "done":
                    callback, data = payload
                    callback(data)
                    self.progress.configure(value=0)
                elif kind == "error":
                    exc, tb = payload
                    self.progress.configure(value=0)
                    self.set_status(f"{_('common.error')}: {exc}")
                    messagebox.showerror(_("common.error"),
                                         f"{type(exc).__name__}: {exc}")
                    if not isinstance(exc, StegoError):
                        print(tb)
        except queue.Empty:
            pass
        self.root.after(100, self._drain_queue)


def main(argv=None) -> int:
    """Entry point for ``python -m adaptivestego gui``."""
    try:
        import tkinter as tk
    except ImportError:
        print("The graphical interface needs the Tk bindings for Python.\n"
              "Debian/Ubuntu: sudo apt install python3-tk\n"
              "Fedora:        sudo dnf install python3-tkinter\n"
              "Arch:          sudo pacman -S tk\n"
              "The command line interface works without them: "
              "python -m adaptivestego --help")
        return 3

    root = tk.Tk()
    try:
        root.call("tk", "scaling", 1.2)
    except tk.TclError:  # pragma: no cover - platform dependent
        pass
    AdaptiveStegoApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
