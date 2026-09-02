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
