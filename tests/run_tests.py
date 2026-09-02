#!/usr/bin/env python3
"""Standalone test runner that does not need pytest.

    python tests/run_tests.py [name-filter]

If pytest is installed, prefer ``pytest -q``. This runner exists so the suite
can also be executed in a bare environment that only has numpy and OpenCV.
"""

from __future__ import annotations

import importlib
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from conftest import Skipped  # noqa: E402 - imported after sys.path setup

MODULES = ["test_container", "test_codecs", "test_metrics_attacks",
           "test_io_cli", "test_gui_i18n"]


def main(argv: list[str]) -> int:
    pattern = argv[0] if argv else ""
    passed = failed = skipped = 0
    failures = []
    t0 = time.time()

    for name in MODULES:
        module = importlib.import_module(name)
        tests = [(n, getattr(module, n)) for n in sorted(dir(module))
                 if n.startswith("test_") and callable(getattr(module, n))]
        for test_name, fn in tests:
            full = f"{name}.{test_name}"
            if pattern and pattern not in full:
                continue
            try:
                fn()
            except Skipped as exc:
                skipped += 1
                print(f"s {full}  ({exc})")
            except Exception:
                failed += 1
                failures.append((full, traceback.format_exc()))
                print(f"F {full}")
            else:
                passed += 1
                print(f". {full}")

    for full, tb in failures:
        print(f"\n{'=' * 70}\nFAIL {full}\n{'-' * 70}\n{tb}")

    print(f"\n{passed} passed, {failed} failed, {skipped} skipped "
          f"за {time.time() - t0:.1f} с")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
