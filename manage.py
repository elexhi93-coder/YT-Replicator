#!/usr/bin/env python
"""Django management entrypoint (U03).

Thin wrapper: adds `src/` to `sys.path` so top-level imports (`ui.*`,
`accounts.*`, ...) resolve per pyproject `pythonpath`, then delegates to
Django. Used by the worker process (`manage.py runworker`, docs/04 §7)
and one-shot ops commands (`migrate`, `purge_history`).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parent
    src = root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ui.settings")

    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:  # pragma: no cover - missing dependency
        raise ImportError(
            "Django is not installed. Run `pip install -e .` (or install "
            "requirements) inside the virtualenv first."
        ) from exc

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
