"""
worker.api — the worker's published surface (U14).

`worker` publishes no domain data of its own: it owns the *loop*. Everything
else lives in the modules it calls. So this surface is small — and it exists
so that a caller (the `runworker` management command, the dashboard's "run one
pass" button) never reaches into `worker.loop` or `worker.recovery` directly
(INV-12: cross-module access is only through `<module>.api`).
"""

from __future__ import annotations

from worker.loop import IterationResult, run_forever, run_once
from worker.recovery import (
    DEFAULT_CLAIM_TIMEOUT_MINUTES,
    RecoveryReport,
    recover,
)

__all__ = [
    "DEFAULT_CLAIM_TIMEOUT_MINUTES",
    "IterationResult",
    "RecoveryReport",
    "recover",
    "run_forever",
    "run_once",
]
