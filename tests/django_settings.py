"""Django settings for the test suite only.

U02 needs a Django environment before U03 ships the real project shell
(`ui` module). Deliberately minimal: auth + contenttypes + accounts.

INV-10 note: SQLite here is allowed — the invariant forbids SQLite **in
production** (D-19). The production settings (U03/U23) are PostgreSQL.
"""

SECRET_KEY = "test-only-not-a-production-secret"

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "accounts",
    "credentials",
    "sources",
    "pipelines",
    "jobs",
    "ui",
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

INSTALLED_APPS += [
    "django.contrib.sessions",
    "django.contrib.messages",
]

# Docs/04 §9: CSRF on every state-changing request (forms under test use it).
# Session + auth middleware so the test Client's force_login attaches
# request.user (login_required / nav_context depend on it).
MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
]

# login_required redirects here (D16).
LOGIN_URL = "/login/"

ROOT_URLCONF = "tests.test_urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": ["src/ui/templates"],
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
