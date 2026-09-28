"""ui.apps — Django app config for the project shell (U03).

`ready()` is where the process binds its port adapters (Pillar 0 §4). The
`ui` layer is the outermost one, so it is the only place allowed to see both
`core` and `sources` at once: `sources.api` asks `core` for its provider and
never imports the provider itself, which is what keeps the dependency arrow
one-way (docs/04 §2/§3, INV-12).
"""

from django.apps import AppConfig


class UiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "ui"

    def ready(self) -> None:
        # Idempotent: `ready()` may run more than once in a test process, and
        # re-registering simply replaces the factory (core.registry semantics).
        from core.api import register_source_provider
        from sources.api import source_provider_factory

        register_source_provider(source_provider_factory)
