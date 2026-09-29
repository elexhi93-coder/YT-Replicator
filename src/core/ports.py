from __future__ import annotations

"""
YT-Replicator — Pillar 0 Port Protocols and Contract Types (INV-12).

Specification: `docs/PILLARS/00_INTER_PILLAR_CONTRACTS/03_INTERFACE_CONTRACT.md`.
Module owner: Pillar 7 (`core`). Interface owner: Pillar 0 — these signatures
may not change without a `docs/04` §6 row.

Rules enforced on every method (R1–R6 of §7):
  R1 typed errors only (from core.exceptions)   R2 no database writes
  R3 bounded time (timeout from app_setting)    R4 no raw platform types cross
  R5 parsing is caller work                     R6 no internal retries (jobs owns retry)

Consumers import these via `core.api` only (INV-12).
"""

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterator, Protocol, runtime_checkable

# --- Provenance marker (§9) -------------------------------------------------

# Anchored at end of description; [ref:<11-char source_video_id>:<delivery_id>]
PROVENANCE_MARKER_REGEX = re.compile(
    r"\[ref:(?P<source_video_id>[A-Za-z0-9_-]{11}):(?P<delivery_id>\d+)\]$"
)


def format_provenance_marker(source_video_id: str, delivery_id: int) -> str:
    """Render the exact marker line (§9.1). Generation belongs to `delivery`."""
    return f"[ref:{source_video_id}:{delivery_id}]"


# --- Identity references (§6.11) --------------------------------------------


@dataclass(frozen=True)
class SourceRef:
    source_id: int
    kind: str                      # 'channel' | 'playlist'
    external_id: str
    url: str


@dataclass(frozen=True)
class ChannelRef:
    channel_id: int
    platform: str                  # 'youtube' in v1
    external_channel_id: str


@dataclass(frozen=True)
class VideoRef:
    source_id: int
    video_id: str                  # 11 chars for YouTube


# --- SourceProvider types (§6.1–6.4) ---------------------------------------


@dataclass(frozen=True)
class ResolvedSource:
    kind: str                      # 'channel' | 'playlist'
    external_id: str               # canonical ID, e.g. UC... or PL...
    canonical_url: str             # normalised URL with /videos for channels
    title: str | None              # display title if fetched at resolve time


@dataclass(frozen=True)
class SourceItem:
    video_id: str                  # 11-char YouTube ID (or external ID)
    title: str
    published_at: datetime | None
    duration_sec: int | None
    thumbnail_url: str | None
    live_status: str               # 'not_live' | 'live' | 'was_live'
    availability: str              # 'public' | 'unlisted' | 'private' | 'unknown'


@dataclass(frozen=True)
class SourceItemDetail:
    video_id: str
    description: str | None
    tags: tuple[str, ...]          # immutable tuple, never a mutable list
    category_id: str | None
    view_count: int | None
    like_count: int | None
    hydrated_at: datetime


@dataclass(frozen=True)
class MaterializeRequest:
    video_id: str
    destination_dir: Path          # absolute path inside a resolved storage root
    max_height: int                # e.g. 1080 (from download_profile)
    prefer_format: str             # 'mp4' | 'mkv' | 'best'


@dataclass(frozen=True)
class MaterializedMedia:
    file_path: Path                # complete, seekable file inside destination_dir
    filename: str                  # relative filename (e.g. "{id}.mp4")
    size_bytes: int
    sha256: str                    # declared digest; `media.verify` recomputes (INV-3)
    duration_sec: int | None
    format: str                    # container format actually written


# --- DestinationPlatform types (§6.5–6.8) ----------------------------------


@dataclass(frozen=True)
class AuthState:
    state: str                     # 'valid' | 'expiring' | 'invalid' | 'revoked'
    channel_id: str
    channel_title: str | None
    scopes: tuple[str, ...]
    expires_at: datetime | None
    refreshed_bundle: str | None   # new encrypted bundle if refreshed during probe


@dataclass(frozen=True)
class DestinationVideoDTO:
    destination_video_id: str
    title: str
    description_excerpt: str       # first 500 chars (docs/03 §8)
    published_at: datetime | None
    privacy_status: str            # 'public' | 'unlisted' | 'private'
    duration_sec: int | None
    marker: str | None             # raw marker if found; parsing is caller's work (R5)


@dataclass(frozen=True)
class InventoryBatch:
    items: tuple[DestinationVideoDTO, ...]
    next_cursor: str | None        # None when exhaustion reached


@dataclass(frozen=True)
class UploadRequest:
    source_video_id: str
    media_path: Path               # verified local file
    title: str                     # <= 100 chars (YouTube limit)
    description: str               # <= 5000 chars, with marker appended
    tags: tuple[str, ...]
    category_id: str
    privacy: str                   # 'public' | 'unlisted' | 'private'
    made_for_kids: bool
    contains_synthetic_media: bool
    thumbnail_path: Path | None    # verified local image, or None
    provenance_marker: str         # the exact marker line embedded in description


@dataclass(frozen=True)
class UploadOutcome:
    destination_video_id: str
    destination_url: str
    privacy: str
    units_used: int                # platform quota units consumed
    http_status: int
    raw_error_code: str | None     # populated only on error
    thumbnail_uploaded: bool       # False if thumbnail failed after video succeeded


# --- MetadataTransformer types (§6.9–6.10) ---------------------------------


@dataclass(frozen=True)
class TransformInput:
    source_title: str
    source_description: str | None
    source_tags: tuple[str, ...]
    target_language: str | None
    template_name: str | None


@dataclass(frozen=True)
class TransformResult:
    title: str
    description: str
    tags: tuple[str, ...]
    applied: bool                  # False if fallback occurred
    fallback_reason: str | None    # None if applied is True


# --- Port protocols (§3–§5) -------------------------------------------------

ProgressCallback = Callable[[int, int], None]


@runtime_checkable
class SourceProvider(Protocol):
    """Port A — implemented by the `sources` module (YouTube via yt-dlp)."""

    def resolve(self, raw_url: str) -> ResolvedSource: ...

    def scan(
        self, source: SourceRef, since: datetime | None
    ) -> Iterator[SourceItem]: ...

    def hydrate(self, item: VideoRef) -> SourceItemDetail: ...

    def materialize(self, request: MaterializeRequest) -> MaterializedMedia: ...


@runtime_checkable
class DestinationPlatform(Protocol):
    """Port B — implemented by the `youtube` adapter (Pillar 2)."""

    def probe_auth(self, credentials: bytes) -> AuthState:
        """`credentials` is the still-encrypted bundle; decrypting is the
        adapter's job (INV-9), so no decrypted-secret type ever appears in a
        public signature."""
        ...

    def sync_inventory(
        self, channel: ChannelRef, cursor: str | None
    ) -> InventoryBatch: ...

    def upload(
        self, request: UploadRequest, on_progress: ProgressCallback | None
    ) -> UploadOutcome: ...

    def unit_cost_for_upload(self) -> int: ...


@runtime_checkable
class MetadataTransformer(Protocol):
    """Port C — v1 implementation: `PassthroughTransformer` (in `delivery`)."""

    def transform(self, input: TransformInput) -> TransformResult: ...


class PassthroughTransformer:
    """v1 MetadataTransformer: returns input verbatim (IDEA-03 is a v2 decision).

    Contract (§5.1): never raises, pure function; `applied=False` with a
    fallback_reason stating transformation is disabled in v1.
    """

    def transform(self, input: TransformInput) -> TransformResult:
        return TransformResult(
            title=input.source_title,
            description=input.source_description or "",
            tags=input.source_tags,
            applied=False,
            fallback_reason="transformer_disabled",
        )


# --- RetentionOracle (U12, INV-10) -------------------------------------------
#
# The retention evaluator's gates need four facts, each owned by a different
# module: the policy lives on `pipeline`, terminality and `uploaded_at` on the
# `delivery` ledger, the `after_n_jobs` count on `job`, and "is a destination
# copy confirmed present" on `destination_inventory`. `media` may import
# `core` and `accounts` only (docs/04 §2), so it cannot read any of them.
#
# Rather than widen four dependency arrows for four one-line reads, the
# evaluator asks for one read-only snapshot. This is the same inversion the
# Pillar 0 registry already performs for Port A: the consumer names the
# capability it needs, the composition root (`ui.apps.ready`) supplies it.
#
# R2 still applies — this port performs **no database writes**. The evaluator
# owns every write; the oracle only observes.


@dataclass(frozen=True)
class RetentionFacts:
    """Everything the retention gates need that `media` does not own."""

    #: 'keep' | 'immediate' | 'after_n_jobs' | 'after_hours', already resolved
    #: through any per-destination override. 'keep' short-circuits the whole
    #: evaluation (D1) and no other field is then consulted.
    mode: str
    retention_n: int
    retention_hours: int
    #: INV-2: True only when every *enabled* destination of the pipeline has
    #: reached a terminal ledger state. False while anything is still pending,
    #: queued or running — deletion is then strictly forbidden.
    all_destinations_terminal: bool
    #: True when at least one destination inventory row for this video is
    #: present. Guards the last-copy gate: the only local copy is not deleted
    #: while the remote copy is unconfirmed (D3).
    destination_copy_present: bool
    #: Newer *completed jobs of the same pipeline* — jobs, not uploads, so one
    #: video × two destinations counts once (D5).
    newer_completed_jobs: int
    uploaded_at: datetime | None
    #: F-10: `catalog_video.starred` doubles as the retention pin. It lives on
    #: another module's table, so like everything else here it arrives as a
    #: fact rather than a join.
    starred: bool = False
    #: Set when the facts could not be gathered (no job, no policy). The
    #: evaluator refuses to delete on unknown facts, and says so.
    unavailable_reason: str = ""


@runtime_checkable
class RetentionOracle(Protocol):
    """Read-only view of the facts the retention gates depend on."""

    def facts_for(
        self, workspace_id: int, source_video_id: str, job_id: int | None
    ) -> RetentionFacts:
        """Gather the snapshot for one asset, or explain why it cannot."""
        ...

