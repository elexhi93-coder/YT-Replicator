"""ui.settings — the project's Django settings (U03).

Production shape: PostgreSQL via `DATABASE_URL`, signed session cookies off
the default `SECRET_KEY` env (fail-fast when missing in production),
`secure/httponly/samesite=Lax` sessions (docs/04 §9). Tests keep using
`tests/django_settings.py` (SQLite, in-memory); this module is the shipped
runtime, not the test harness.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parent


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip() or default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


DEBUG = _env_bool("DJANGO_DEBUG", False)

SECRET_KEY = _env("DJANGO_SECRET_KEY", "")
if not SECRET_KEY and not DEBUG:
    raise ValueError(
        "DJANGO_SECRET_KEY is required in production. "
        "Set it to a long random value (e.g. `python -c "
        "\"import secrets; print(secrets.token_urlsafe(50))\"`)."
    )
if not SECRET_KEY:  # development fallback only; never used in production
    SECRET_KEY = "dev-only-not-a-production-secret"  # nosec B105

ALLOWED_HOSTS = [
    h.strip() for h in _env("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()
]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "accounts",
    "credentials",
    "sources",
    "ui",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "ui.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "ui.context_processors.nav_context",
            ],
        },
    },
]

WSGI_APPLICATION = "ui.wsgi.application"


def _database_config() -> dict:
    url = _env("DATABASE_URL", "")
    if not url:
        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": _env("POSTGRES_DB", "replicator"),
            "USER": _env("POSTGRES_USER", "replicator"),
            "PASSWORD": _env("POSTGRES_PASSWORD", ""),
            "HOST": _env("POSTGRES_HOST", "db"),
            "PORT": _env("POSTGRES_PORT", "5432"),
        }
    parsed = urlparse(url)
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": parsed.path.lstrip("/"),
        "USER": parsed.username or "",
        "PASSWORD": parsed.password or "",
        "HOST": parsed.hostname or "",
        "PORT": str(parsed.port or "5432"),
    }


DATABASES = {"default": _database_config()}

USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/login/"

# docs/04 §9 — sessions: secure, httponly, samesite=Lax; rotate on login.
SESSION_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = not DEBUG
