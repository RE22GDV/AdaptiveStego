"""Shared test setup: import path and small helpers."""

import os
import sys

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)


class Skipped(Exception):
    """A test was skipped (used by the standalone runner in run_tests.py)."""


def skip(reason: str):
    """Skip a test: through pytest when it is available, else via Skipped."""
    try:
        import pytest
    except ImportError as exc:
        raise Skipped(reason) from exc
    pytest.skip(reason)


def raises(exc_type, fn, *args, **kwargs):
    """Assert that a call raises the expected exception and return it."""
    try:
        fn(*args, **kwargs)
    except exc_type as exc:
        return exc
    except Exception as exc:  # noqa: BLE001 - the exact type matters here
        raise AssertionError(
            f"expected {exc_type.__name__}, got {type(exc).__name__}: {exc}") from exc
    raise AssertionError(f"expected {exc_type.__name__}, nothing was raised")
