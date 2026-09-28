from __future__ import annotations

"""
YT-Replicator — Typed Application Settings with Documented Defaults (U01).

Two kinds of settings exist, and this module owns the first kind only:

1. **Deployment settings** (this file): read from environment variables at
   process start. They describe *where* things live and *how wide* the safety
   margins are. Overridable per environment; every default is safe for
   development with zero configuration.
2. **Runtime settings** (`app_setting` table, docs/03 §11): operator-tunable
   cadences seeded from `APP_SETTING_DEFAULTS` below so that exactly one place
   in the codebase defines what "15 minutes" means.

Environment variables (all optional in development):

| Variable                | Default        | Why it exists                                |
|-------------------------|----------------|----------------------------------------------|
| `PLATFORM_MASTER_KEY`   | *(none)*       | AES-256-GCM key for secrets (INV-1). Read by `core.crypto`; missing key is a hard error, never a default. |
| `MEDIA_ROOT`            | `media`        | Deployment media path; seeded into the default `storage_root` (docs/03 §11). |
| `DISK_FREE_FLOOR_GB`    | `10`           | Worker admission gate: refuse to start a download below this free space (docs/04 §7.1). |
| `LOG_LEVEL`             | `INFO`         | Minimum level for `replicator.*` loggers.    |
| `DATABASE_URL`          | *(Django env)* | Consumed by Django settings (ui), not here.  |

Nothing in this module performs I/O beyond reading `os.environ`.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

# --- Runtime settings (app_setting table) -----------------------------------
# docs/03 §11: seeded rows, each with the reason it exists. Kept here so the
# seed migration and any fallback code share one definition.
APP_SETTING_DEFAULTS: dict[str, Any] = {
    "monitor_poll_minutes": 15,             # D9 — default scan cadence
    "reconcile_hours": 6,                   # D9 fallback reconciliation cadence
    "retention_backstop_days": 7,           # D6 — ceiling no retention mode may exceed
    "hydrate_interval_seconds": 1,          # legacy-proven rate-limit discipline
    "hydrate_abort_on_429_minutes": 5,      # brief cooling-off after a 429
    "claim_timeout_minutes": 15,            # stale-claim recovery window
    "upload_chunk_bytes": 1048576,          # resumable upload chunk size (F-22)
    "quota_timezone": "America/Los_Angeles",  # D-03 fix, explicit in one place
}

# --- Deployment defaults ----------------------------------------------------

DEFAULT_MEDIA_ROOT = "media"
DEFAULT_DISK_FREE_FLOOR_GB = 10
DEFAULT_LOG_LEVEL = "INFO"


def _env_int(name: str, default: int, env: Mapping[str, str]) -> int:
    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        raise ValueError(
            f"Environment variable {name}={raw!r} is not an integer. "
            f"Expected a whole number, e.g. {name}={default}."
        )


def _env_str(name: str, default: str, env: Mapping[str, str]) -> str:
    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip()


@dataclass(frozen=True)
class Settings:
    """Immutable snapshot of deployment settings, loaded from the environment."""

    media_root: Path
    disk_free_floor_gb: int
    log_level: str

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        """Build Settings from `env` (defaults to `os.environ`). Pure and testable."""
        source = os.environ if env is None else env
        return cls(
            media_root=Path(_env_str("MEDIA_ROOT", DEFAULT_MEDIA_ROOT, source)),
            disk_free_floor_gb=_env_int(
                "DISK_FREE_FLOOR_GB", DEFAULT_DISK_FREE_FLOOR_GB, source
            ),
            log_level=_env_str("LOG_LEVEL", DEFAULT_LOG_LEVEL, source).upper(),
        )


_cached: Settings | None = None


def get_settings() -> Settings:
    """Return the process-wide Settings snapshot (loaded on first call)."""
    global _cached
    if _cached is None:
        _cached = Settings.from_env()
    return _cached


def reset_settings_cache() -> None:
    """Drop the cached snapshot so the next `get_settings()` re-reads the
    environment. Used by tests; never call it from application code."""
    global _cached
    _cached = None
