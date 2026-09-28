"""pipelines.api — Pipelines, Destinations & Routing (U06), published surface.

Three rules shape this module:

* **A pipeline is configuration, not history.** Everything here is soft-deletable
  and never cascades the delivery ledger (INV-4, fixes D-04).
* **Activation is an explicit act.** A pipeline is created as a draft and only
  an operator's `activate()` starts work; that is the answer to the legacy's
  open question of whether backfill should begin by itself.
* **The state machine is enforced here**, not by the caller: `draft → active`,
  `active → paused`, `paused → active`. Anything else raises `InvalidTransition`.

Every value is checked against the vocabulary the schema CHECK constraints
allow *before* the write, so an operator sees `InvalidSetting` naming the field
rather than a database error.
"""

from __future__ import annotations

from core.api import now_utc
from pipelines.errors import (
    DownloadProfileNotFound,
    InvalidSetting,
    InvalidTransition,
    PipelineNameTaken,
    PipelineNotFound,
    PipelineNotRunnable,
)
from pipelines.models import (
    PRIVACY_CHOICES,
    RETENTION_MODES,
    Destination,
    DownloadProfile,
    Pipeline,
    PipelineDestination,
    PipelineSource,
)

__all__ = [
    "activate",
    "add_destination",
    "add_download_profile",
    "attach_destination",
    "attach_source",
    "create_pipeline",
    "delete_pipeline",
    "detach_destination",
    "detach_source",
    "get_pipeline",
    "list_destinations",
    "list_download_profiles",
    "list_pipeline_destinations",
    "list_pipeline_sources",
    "list_pipelines",
    "pause",
    "update_pipeline",
]

_PRIVACY = {value for value, _label in PRIVACY_CHOICES}
_RETENTION = {value for value, _label in RETENTION_MODES}
_STATUSES = {value for value, _label in Pipeline.STATUS_CHOICES}
_MODES = {value for value, _label in PipelineSource.MODE_CHOICES}


def _check(field: str, value, allowed) -> None:
    if value not in allowed:
        raise InvalidSetting(field, value, allowed)


def create_pipeline(
    workspace,
    name: str,
    *,
    description: str = "",
    priority: int = 100,
    download_profile: DownloadProfile | None = None,
    default_privacy: str = "unlisted",
    provenance_marker: bool = True,
    retention_mode: str = "keep",
    retention_n: int = 2,
    retention_hours: int = 24,
) -> Pipeline:
    """Create a pipeline in `draft`. Nothing runs until `activate()`.

    The profile is optional here and attached by reference: a pipeline without
    one is still a valid draft, which is the point of the draft state.
    """
    _check("default_privacy", default_privacy, _PRIVACY)
    _check("retention_mode", retention_mode, _RETENTION)
    if retention_n < 1:
        raise InvalidSetting("retention_n", retention_n, {"an integer >= 1"})
    if retention_hours < 1:
        raise InvalidSetting("retention_hours", retention_hours, {"an integer >= 1"})
    # No `deleted_at` filter: docs/03 §6 declares UNIQUE (workspace, name) on
    # the table, and a soft-deleted row still occupies that name — which is
    # what keeps the delivery ledger's pipeline references unambiguous.
    if Pipeline.objects.filter(workspace=workspace, name=name).exists():
        raise PipelineNameTaken(
            f"A pipeline named {name!r} already exists in this workspace."
        )
    return Pipeline.objects.create(
        workspace=workspace,
        name=name,
        description=description,
        priority=priority,
        download_profile=download_profile,
        default_privacy=default_privacy,
        provenance_marker=provenance_marker,
        retention_mode=retention_mode,
        retention_n=retention_n,
        retention_hours=retention_hours,
    )


def get_pipeline(workspace, pipeline_id) -> Pipeline:
    """Fetch a live pipeline. Soft-deleted rows are invisible by design."""
    try:
        return Pipeline.objects.get(
            workspace=workspace, id=pipeline_id, deleted_at__isnull=True
        )
    except Pipeline.DoesNotExist as exc:
        raise PipelineNotFound(
            f"No pipeline {pipeline_id} in this workspace."
        ) from exc


def list_pipelines(
    workspace, *, status: str | None = None, include_deleted: bool = False
) -> list[Pipeline]:
    """Pipelines in run order: priority ascending, then id."""
    if status is not None:
        _check("status", status, _STATUSES)
    queryset = Pipeline.objects.filter(workspace=workspace)
    if not include_deleted:
        queryset = queryset.filter(deleted_at__isnull=True)
    if status is not None:
        queryset = queryset.filter(status=status)
    return list(queryset.order_by("priority", "id"))


def update_pipeline(pipeline: Pipeline, **fields) -> Pipeline:
    """Update the mutable fields. `status` is not among them — use activate/pause.

    `name` is mutable, but uniqueness is still enforced so an update cannot
    collide with another pipeline the same way `create_pipeline` does.
    """
    allowed = {
        "name",
        "description",
        "priority",
        "download_profile",
        "default_privacy",
        "provenance_marker",
        "retention_mode",
        "retention_n",
        "retention_hours",
    }
    unknown = set(fields) - allowed
    if unknown:
        raise InvalidSetting("field", sorted(unknown)[0], allowed)
    if "default_privacy" in fields:
        _check("default_privacy", fields["default_privacy"], _PRIVACY)
    if "retention_mode" in fields:
        _check("retention_mode", fields["retention_mode"], _RETENTION)
    if fields.get("retention_n", 1) < 1:
        raise InvalidSetting("retention_n", fields["retention_n"], {"an integer >= 1"})
    if fields.get("retention_hours", 1) < 1:
        raise InvalidSetting(
            "retention_hours", fields["retention_hours"], {"an integer >= 1"}
        )
    new_name = fields.get("name", pipeline.name)
    if (
        Pipeline.objects.filter(workspace=pipeline.workspace, name=new_name)
        .exclude(pk=pipeline.pk)
        .exists()
    ):
        raise PipelineNameTaken(
            f"A pipeline named {new_name!r} already exists in this workspace."
        )
    for field, value in fields.items():
        setattr(pipeline, field, value)
    pipeline.save()
    return pipeline


def delete_pipeline(pipeline: Pipeline) -> Pipeline:
    """Soft-delete a pipeline. A running pipeline is paused first.

    Nothing is hard-deleted: the ledger in `delivery` keeps referring to these
    rows, and cascading configuration away is exactly the legacy's D-04. A
    paused pipeline is a stopped pipeline, so deleting an active one must not
    leave work queued against it.
    """
    if pipeline.status == Pipeline.STATUS_ACTIVE:
        pipeline.status = Pipeline.STATUS_PAUSED
    pipeline.deleted_at = now_utc()
    pipeline.save(update_fields=["status", "deleted_at", "updated_at"])
    return pipeline


def activate(pipeline: Pipeline) -> Pipeline:
    """`draft → active` or `paused → active`, once the pipeline is runnable.

    Runnability is the whole point of the draft state: a pipeline with no
    source, or with every destination disabled, would activate and then
    silently do nothing. Saying so at activation is better than discovering it
    in a log.
    """
    if pipeline.status == Pipeline.STATUS_ACTIVE:
        raise InvalidTransition(pipeline.status, Pipeline.STATUS_ACTIVE)
    if pipeline.deleted_at is not None:
        raise PipelineNotFound(
            f"Pipeline {pipeline.pk} is deleted and cannot be activated."
        )
    if not pipeline.pipeline_sources.exists():
        raise PipelineNotRunnable("source")
    if not pipeline.pipeline_destinations.filter(enabled=True).exists():
        raise PipelineNotRunnable("enabled destination")
    pipeline.status = Pipeline.STATUS_ACTIVE
    pipeline.save(update_fields=["status", "updated_at"])
    return pipeline


def pause(pipeline: Pipeline) -> Pipeline:
    """`active → paused`. Idempotent on an already-paused pipeline.

    Pausing a draft is refused: a draft has no work to stop, and silently
    treating it as paused would hide a misconfiguration.
    """
    if pipeline.status == Pipeline.STATUS_DRAFT:
        raise InvalidTransition(pipeline.status, Pipeline.STATUS_PAUSED)
    pipeline.status = Pipeline.STATUS_PAUSED
    pipeline.save(update_fields=["status", "updated_at"])
    return pipeline


def attach_source(
    pipeline: Pipeline,
    source,
    *,
    mode: str = PipelineSource.MODE_MONITOR,
    priority: int = 100,
    daily_cap: int | None = None,
) -> PipelineSource:
    """Attach a source, or update its settings if it is already attached.

    Idempotent on `(pipeline, source)`: re-attaching a source an operator is
    re-configuring must edit the row, not raise or duplicate it.
    """
    _check("mode", mode, _MODES)
    if daily_cap is not None and daily_cap < 1:
        raise InvalidSetting("daily_cap", daily_cap, {"an integer >= 1", "null"})
    if source.workspace_id != pipeline.workspace_id:
        raise InvalidSetting(
            "source", source.pk, {"a source in the same workspace"}
        )
    link, _created = PipelineSource.objects.update_or_create(
        pipeline=pipeline,
        source=source,
        defaults={
            "workspace": pipeline.workspace,
            "mode": mode,
            "priority": priority,
            "daily_cap": daily_cap,
        },
    )
    return link


def detach_source(pipeline: Pipeline, source) -> bool:
    """Remove a source from a pipeline. False if it was not attached.

    Deleting the link is safe at any time: the source and its catalog stay, and
    the delivery ledger keeps its history (INV-4).
    """
    deleted, _ = PipelineSource.objects.filter(
        pipeline=pipeline, source=source
    ).delete()
    return bool(deleted)


def list_pipeline_sources(
    pipeline: Pipeline, *, mode: str | None = None
) -> list[PipelineSource]:
    """Attached sources in the order work is considered: priority, then id."""
    if mode is not None:
        _check("mode", mode, _MODES)
    queryset = pipeline.pipeline_sources.select_related("source")
    if mode is not None:
        queryset = queryset.filter(mode=mode)
    return list(queryset.order_by("priority", "id"))


def add_destination(
    workspace,
    channel,
    *,
    label: str,
    default_privacy: str = "unlisted",
    daily_max: int = 6,
) -> Destination:
    """Create a workspace-level destination bound to an authorised channel.

    The channel is an `AuthorizedChannel`; this module never decrypts a token —
    obtaining one is `credentials.api.valid_access_token`'s job (INV-12).
    """
    _check("default_privacy", default_privacy, _PRIVACY)
    if daily_max < 1:
        raise InvalidSetting("daily_max", daily_max, {"an integer >= 1"})
    if Destination.objects.filter(workspace=workspace, label=label).exists():
        raise PipelineNameTaken(
            f"A destination labelled {label!r} already exists in this workspace."
        )
    return Destination.objects.create(
        workspace=workspace,
        authorized_channel=channel,
        label=label,
        default_privacy=default_privacy,
        daily_max=daily_max,
    )


def list_destinations(workspace, *, enabled_only: bool = True) -> list[Destination]:
    """Destinations in label order. Soft-deleted rows are never returned."""
    queryset = Destination.objects.filter(workspace=workspace, deleted_at__isnull=True)
    if enabled_only:
        queryset = queryset.filter(enabled=True)
    return list(queryset.order_by("label", "id"))


def attach_destination(
    pipeline: Pipeline,
    destination: Destination,
    *,
    enabled: bool = True,
    priority: int = 100,
    privacy_override: str | None = None,
    retention_mode_override: str | None = None,
) -> PipelineDestination:
    """Attach a destination to a pipeline, or update an existing attachment."""
    if privacy_override is not None:
        _check("privacy_override", privacy_override, _PRIVACY)
    if retention_mode_override is not None:
        _check("retention_mode_override", retention_mode_override, _RETENTION)
    if destination.workspace_id != pipeline.workspace_id:
        raise InvalidSetting(
            "destination", destination.pk, {"a destination in the same workspace"}
        )
    link, _created = PipelineDestination.objects.update_or_create(
        pipeline=pipeline,
        destination=destination,
        defaults={
            "workspace": pipeline.workspace,
            "enabled": enabled,
            "priority": priority,
            "privacy_override": privacy_override,
            "retention_mode_override": retention_mode_override,
        },
    )
    return link


def detach_destination(pipeline: Pipeline, destination: Destination) -> bool:
    """Stop a destination receiving this pipeline's videos. The destination row stays."""
    deleted, _ = PipelineDestination.objects.filter(
        pipeline=pipeline, destination=destination
    ).delete()
    return bool(deleted)


def list_pipeline_destinations(
    pipeline: Pipeline, *, enabled_only: bool = False
) -> list[PipelineDestination]:
    """Destinations attached to a pipeline, in run order."""
    queryset = pipeline.pipeline_destinations.select_related("destination")
    if enabled_only:
        queryset = queryset.filter(enabled=True)
    return list(queryset.order_by("priority", "id"))


def add_download_profile(
    workspace,
    name: str,
    *,
    max_height: int = 0,
    container: str = "mp4",
    sub_langs: list[str] | None = None,
    skip_shorts: bool = False,
    skip_live: bool = True,
) -> DownloadProfile:
    """Create a reusable quality profile. v1 never re-encodes (D15)."""
    if max_height < 0:
        raise InvalidSetting("max_height", max_height, {"0 (no cap) or > 0"})
    if DownloadProfile.objects.filter(workspace=workspace, name=name).exists():
        raise PipelineNameTaken(
            f"A download profile named {name!r} already exists in this workspace."
        )
    return DownloadProfile.objects.create(
        workspace=workspace,
        name=name,
        max_height=max_height,
        container=container,
        sub_langs=list(sub_langs) if sub_langs is not None else ["en"],
        skip_shorts=skip_shorts,
        skip_live=skip_live,
    )


def list_download_profiles(workspace) -> list[DownloadProfile]:
    return list(
        DownloadProfile.objects.filter(workspace=workspace).order_by("name", "id")
    )


def get_download_profile(workspace, profile_id) -> DownloadProfile:
    try:
        return DownloadProfile.objects.get(workspace=workspace, id=profile_id)
    except DownloadProfile.DoesNotExist as exc:
        raise DownloadProfileNotFound(
            f"No download profile {profile_id} in this workspace."
        ) from exc

