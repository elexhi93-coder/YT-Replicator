from django.db import migrations


def create_default_workspace(apps, schema_editor):
    """Seed the single default workspace (docs/03 §11, D11).

    Idempotent: re-running must not duplicate or rename an operator's workspace.
    """
    Workspace = apps.get_model("accounts", "Workspace")
    Workspace.objects.get_or_create(
        slug="default",
        defaults={"name": "Default Workspace", "is_active": True},
    )


def remove_default_workspace(apps, schema_editor):
    """Reverse only the row this migration created (name is the tell)."""
    Workspace = apps.get_model("accounts", "Workspace")
    Workspace.objects.filter(
        slug="default", name="Default Workspace"
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(create_default_workspace, remove_default_workspace),
    ]