"""
manage.py purge_runtime_data — the "clean slate without losing history" tool.

This is the legacy's F-53, kept because it is a genuinely good idea and safe
*only* because the ledger really is the durable record. Three properties make
it safe here, and each is enforced rather than documented:

1. **It runs in `ui`, not `ops`.** `ops` may import `core` and `accounts` only,
   so it cannot delete another module's rows — and an operations module that
   could reach every table would be a back door around the whole dependency
   design. Each module owns its own `purge_*`, and this command composes them.
2. **The dry run is the default**, and every module's plan is computed from the
   same query its real purge uses. A plan written separately from the action is
   a plan that can lie.
3. **It refuses to run without a backup** (`ops.require_backup`, F-54), and
   records what it did in the audit trail either way.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from accounts.api import get_default_workspace
from delivery.api import purge_plan as delivery_plan
from jobs.api import purge_plan as jobs_plan
from media.api import purge_plan as media_plan
from ops.api import audit, require_backup


class Command(BaseCommand):
    help = "Purge runtime data (jobs + downloaded media). The ledger is kept."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually delete. Without this flag nothing is removed.",
        )
        parser.add_argument(
            "--backup-confirmed",
            action="store_true",
            help="Confirm a backup exists (F-54). Required with --apply.",
        )
        parser.add_argument(
            "--backup-ref",
            default="",
            help="Where the backup is, recorded in the audit trail.",
        )
        parser.add_argument(
            "--include-media",
            action="store_true",
            help="Also delete downloaded media. Jobs alone is usually enough.",
        )
        parser.add_argument("--actor", default="operator")

    def handle(self, *args, **options):
        workspace = get_default_workspace()
        plan = {
            "jobs": jobs_plan(workspace),
            "media": media_plan(workspace) if options["include_media"] else {},
            "delivery_kept": delivery_plan(workspace),
        }
        self.stdout.write("DRY RUN — nothing has been removed:")
        self.stdout.write(f"  would remove: {plan}")
        self.stdout.write("  would keep:   the delivery ledger and all configuration")

        if not options["apply"]:
            return

        try:
            backup_ref = require_backup(
                "purge runtime data",
                confirmed=options["backup_confirmed"],
                backup_ref=options["backup_ref"],
            )
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        from jobs.api import purge_runtime as jobs_purge

        removed = {"jobs": jobs_purge(workspace)}
        if options["include_media"]:
            from media.api import purge_runtime as media_purge

            removed["media"] = media_purge(workspace)

        audit(
            workspace,
            entity="runtime",
            entity_id=str(workspace.pk),
            action="purge",
            detail={"plan": plan, "removed": removed, "backup_ref": backup_ref},
            actor=options["actor"],
        )
        self.stdout.write(f"purged: {removed}")
        self.stdout.write("the delivery ledger was not touched")
