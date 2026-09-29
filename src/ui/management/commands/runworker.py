"""
manage.py runworker — the worker process (docs/04 §7).

The web process never downloads or uploads. This command is the other half of
the runtime: it claims a job, does it, and records the result. Run as many as
you like — the claim is a `FOR UPDATE SKIP LOCKED`, so they cooperate rather
than collide.
"""

from __future__ import annotations

import os
import signal
import sys
import uuid

from django.core.management.base import BaseCommand

from worker.api import recover, run_forever


class Command(BaseCommand):
    help = "Run the job worker: claim, dispatch, record."

    def add_arguments(self, parser):
        parser.add_argument(
            "--worker-id",
            default="",
            help="Identity recorded on claimed jobs. Defaults to a random one.",
        )
        parser.add_argument(
            "--iterations",
            type=int,
            default=None,
            help="Stop after N passes. Omit to run until stopped.",
        )
        parser.add_argument(
            "--sleep",
            type=float,
            default=5.0,
            help="Seconds to wait when the queue is empty.",
        )
        parser.add_argument(
            "--no-recover",
            action="store_true",
            help="Skip the restart-recovery sweep on start-up.",
        )

    def handle(self, *args, **options):
        worker_id = options["worker_id"] or f"worker-{uuid.uuid4().hex[:8]}"

        if not options["no_recover"]:
            # Once per process start, before any work: sweep what a dead
            # process left behind. Idempotent, so it is safe either way.
            report = recover()
            self.stdout.write(
                f"recovery: {report.as_dict()}" if report.as_dict() else "recovery: clean"
            )

        def _stop(signum, frame):  # pragma: no cover - signal path
            self.stdout.write("stopping after the current job")
            raise KeyboardInterrupt

        signal.signal(signal.SIGTERM, _stop)
        signal.signal(signal.SIGINT, _stop)

        self.stdout.write(f"{worker_id} running (pid {os.getpid()})")
        try:
            passes = run_forever(
                worker_id,
                sleep_seconds=options["sleep"],
                iterations=options["iterations"],
            )
        except KeyboardInterrupt:  # pragma: no cover - signal path
            self.stdout.write("stopped")
            return
        self.stdout.write(f"{worker_id} finished after {passes} passes")
        sys.stdout.flush()
