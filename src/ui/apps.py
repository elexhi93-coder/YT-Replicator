"""ui.apps — Django app config for the project shell (U03)."""


from django.apps import AppConfig


class UiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "ui"
