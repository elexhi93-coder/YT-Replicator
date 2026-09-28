"""600-line hard file cap (docs/04_ARCHITECTURE.md §4.3, INV-11, U04).

The legacy's own build order offered "put all routes in app.py for simplicity"
(D-26), and that single sentence produced a 7 000-line monolith. This guard
makes the same shortcut impossible.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = (ROOT / "src", ROOT / "tests")
MAX_LINES = 600


def _python_files():
    for scan_root in SCAN_ROOTS:
        if not scan_root.is_dir():
            continue
        for py_file in scan_root.rglob("*.py"):
            if "__pycache__" in py_file.parts:
                continue
            yield py_file


def test_no_python_file_exceeds_600_lines():
    offenders: list[str] = []
    for py_file in _python_files():
        line_count = len(py_file.read_text(encoding="utf-8").splitlines())
        if line_count > MAX_LINES:
            rel = py_file.relative_to(ROOT)
            offenders.append(f"{rel}: {line_count} lines (cap {MAX_LINES})")
    assert not offenders, (
        "File size cap exceeded — refactor into focused single-responsibility "
        "units before proceeding:\n" + "\n".join(offenders)
    )
