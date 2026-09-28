"""WSGI entrypoint for the project shell (U03). Used by gunicorn (docs/04 §10.1)."""

from __future__ import annotations

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ui.settings")

application = get_wsgi_application()
