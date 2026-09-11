"""Tests for the translations and for the desktop interface.

The GUI tests build a real window, so they are skipped automatically when no
display or no Tk installation is available (headless CI, minimal Linux images).
"""

from conftest import skip

from adaptivestego import i18n


def test_every_language_has_every_key():
    english = set(i18n._STRINGS["en"])
    for code in i18n.LANGUAGES:
        keys = set(i18n._STRINGS[code])
        assert not english - keys, (code, sorted(english - keys))
        assert not keys - english, (code, sorted(keys - english))


def test_translations_are_not_left_in_english():
    """Every language must actually translate the tab captions."""
    for code in ("uk", "ru"):
        i18n.set_language(code)
        assert i18n.translate("tab.embed") != i18n._STRINGS["en"]["tab.embed"]
    i18n.set_language("en")


def test_unknown_key_returns_itself():
    i18n.set_language("en")
    assert i18n.translate("nothing.here") == "nothing.here"


def test_unknown_language_falls_back_to_english():
    i18n.set_language("klingon")
    assert i18n.get_language() == "en"


def test_language_switch_changes_output():
    i18n.set_language("ru")
    russian = i18n.translate("tab.extract")
    i18n.set_language("uk")
    ukrainian = i18n.translate("tab.extract")
    i18n.set_language("en")
    assert russian != ukrainian != i18n.translate("tab.extract")


def test_detect_language_returns_supported_code():
    assert i18n.detect_language() in i18n.LANGUAGES


def _tk_root():
    try:
        import tkinter as tk
    except ImportError:
        skip("tkinter is not installed")
    try:
        root = tk.Tk()
    except Exception as exc:            # noqa: BLE001 - no display available
        skip(f"no display available: {exc}")
    root.withdraw()
    return root


def test_gui_builds_and_switches_language():
    from adaptivestego.gui import AdaptiveStegoApp

    root = _tk_root()
    try:
        app = AdaptiveStegoApp(root, language="en")
        assert app.notebook.index("end") == 5
        english = app.notebook.tab(0, "text")

        i18n.set_language("uk")
        app._retranslate()
        assert app.notebook.tab(0, "text") != english

        i18n.set_language("en")
        app._retranslate()
        assert app.notebook.tab(0, "text") == english
    finally:
        root.destroy()
        i18n.set_language("en")


def test_gui_preview_conversion():
    from adaptivestego.gui import _change_map, _to_photo
    from adaptivestego.testing import synthetic_cover

    root = _tk_root()
    try:
        cover = synthetic_cover(64, 64)
        stego = cover.copy()
        stego[0, 0, 0] ^= 1
        photo = _to_photo(cover, max_side=32)
        assert photo.width() <= 32 and photo.height() <= 32
        changes = _change_map(cover, stego)
        assert changes.shape == cover.shape[:2]
        assert changes[0, 0] == 255 and changes[1, 1] == 0
    finally:
        root.destroy()


def test_gui_reports_missing_tkinter_gracefully():
    """Without Tk the entry point must explain how to install it, not crash."""
    import builtins

    from adaptivestego import gui

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "tkinter":
            raise ImportError("no tkinter")
        return real_import(name, *args, **kwargs)

    builtins.__import__ = fake_import
    try:
        assert gui.main() == 3
    finally:
        builtins.__import__ = real_import


def test_params_state_is_translated_for_channels():
    """The "all channels" option must round-trip through the API mapping."""
    from adaptivestego.gui import AdaptiveStegoApp

    root = _tk_root()
    try:
        app = AdaptiveStegoApp(root, language="ru")
        kwargs = app._params_kwargs("embed")
        assert "channels" not in kwargs       # "all" must not become a channel list
        assert kwargs["method"] in ("adaptive",)
    finally:
        root.destroy()
        i18n.set_language("en")


def test_container_methods_exclude_syndrome_coding():
    """The embed tab writes a container, which syndrome coding cannot use."""
    from adaptivestego.codecs import get_codec
    from adaptivestego.gui import container_methods

    names = container_methods()
    assert "stc" not in names
    assert "adaptive" in names
    assert all(not get_codec(name).syndrome_coded for name in names)


def test_embed_tab_offers_the_two_password_modes():
    """The option to keep key material out of the image must reach the API."""
    from adaptivestego.gui import AdaptiveStegoApp

    root = _tk_root()
    try:
        app = AdaptiveStegoApp(root, language="en")
        assert "no_key_material" in app.embed_params
        assert app.embed_params["no_key_material"].get() is False
        # The extract tab has no such option: the mode is not chosen on the
        # way out, it is discovered.
        assert app.extract_params["no_key_material"].get() is False
    finally:
        root.destroy()
        i18n.set_language("en")


def test_probe_description_says_what_was_found():
    """The line shown after detection, before any password is asked for."""
    from adaptivestego import container
    from adaptivestego.gui import AdaptiveStegoApp

    root = _tk_root()
    try:
        app = AdaptiveStegoApp(root, language="en")

        missing = container.Probe(found=False, detail="nothing")
        assert app._describe_probe(missing) == i18n.translate("extract.not_found")

        header = container.Header(version=1, flags=container.FLAG_ENCRYPTED,
                                  ecc_nsym=0, plain_len=40)
        encrypted = container.Probe(found=True, header=header,
                                    container_bytes=120, message_bytes=40,
                                    encrypted=True, needs_password=True)
        text = app._describe_probe(encrypted)
        assert i18n.translate("extract.found_encrypted") in text
        assert "40" in text

        header = container.Header(version=1, flags=0, ecc_nsym=0, plain_len=40)
        suspected = container.Probe(found=True, header=header,
                                    container_bytes=90, message_bytes=40,
                                    encryption_suspected=True,
                                    needs_password=True)
        assert (i18n.translate("extract.found_maybe_encrypted")
                in app._describe_probe(suspected))
    finally:
        root.destroy()
        i18n.set_language("en")


def test_analyze_tab_renders_a_full_report():
    """The analysis pane must lay out every section of a forensics report."""
    import os
    import tempfile

    from adaptivestego import forensics
    from adaptivestego.gui import AdaptiveStegoApp
    from adaptivestego.image_io import write_image
    from adaptivestego.testing import synthetic_cover

    root = _tk_root()
    try:
        app = AdaptiveStegoApp(root, language="en")
        cover = synthetic_cover(64, 64, seed=3)
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "cover.png")
            write_image(path, cover)
            full = forensics.full_report(path, scan_methods=False)
            app._analyze_done({"path": path, "shape": cover.shape,
                               "full": full, "caps": {"adaptive": 1024},
                               "quality": None})

        text = app.analyze_text.get("1.0", "end-1c")
        for key in ("analyze.overall", "analyze.file_structure",
                    "analyze.detect", "analyze.model", "analyze.containers"):
            assert i18n.translate(key) in text, key
    finally:
        root.destroy()
        i18n.set_language("en")
