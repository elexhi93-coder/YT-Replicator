"""
project003 — Routing service
=============================
Decides which destination(s) a catalog video should be sent to, based on
rows in the `routing_rules` table.

A rule matches a video iff *all* of its enabled conditions pass:
  - `title_regex`   regex (case-insensitive) the title must match
  - `title_excludes` regex (case-insensitive) the title must NOT match
  - `min_duration` / `max_duration` (seconds; 0 = no bound)
  - `skip_shorts` (drop videos with duration < 60s when set)
  - `skip_live` (drop live streams / premieres when set)
  - `tags_any` JSON list -- match if catalog row has any of these tags

Rules are evaluated per (video, destination) pair, ordered by `priority`
ASC, first-match-wins. A NULL `source_id` rule applies to ALL sources.

The router is intentionally a pure decision function plus one
side-effecting wrapper that writes `upload_ledger` rows -- no networking,
no threading. Callers (UI button, scan hook, future scheduler) own the
trigger semantics.
"""
from __future__ import annotations

import json
import re
import sqlite3
from typing import Iterable, NamedTuple, Optional


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

class Match(NamedTuple):
    """A successful (video, destination) routing decision."""
    destination_id: int
    profile_id: Optional[int]   # None -> caller substitutes default
    rule_id: int
    rule_label: str


class Reject(NamedTuple):
    """A non-match for diagnostics. Used by the test/preview UI."""
    destination_id: int
    rule_id: int
    rule_label: str
    reason: str


class RouteResult(NamedTuple):
    """Per-video routing outcome."""
    video_id: str
    matches: list[Match]
    rejects: list[Reject]


# ---------------------------------------------------------------------------
# Pure rule evaluation
# ---------------------------------------------------------------------------

_SHORTS_THRESHOLD_SEC = 60


def _try_regex(pattern: str) -> Optional[re.Pattern]:
    """Compile a case-insensitive regex; return None on empty or invalid."""
    p = (pattern or "").strip()
    if not p:
        return None
    try:
        return re.compile(p, re.IGNORECASE)
    except re.error:
        return None


def _video_tags(video_row) -> list[str]:
    raw = video_row["tags_json"] if "tags_json" in video_row.keys() else None
    if not raw:
        return []
    try:
        v = json.loads(raw)
        return [str(t).strip().lower() for t in v if str(t).strip()]
    except (TypeError, ValueError, json.JSONDecodeError):
        return []


def _check_rule(rule, video) -> Optional[str]:
    """Return None if the rule matches the video, else a human reason string."""
    title = (video["title"] or "")
    duration = int(video["duration_sec"] or 0)
    live = (video["live_status"] or "not_live")

    if rule["skip_live"] and live in ("is_live", "is_upcoming", "was_live"):
        return f"skip_live (live_status={live})"

    if rule["skip_shorts"] and 0 < duration < _SHORTS_THRESHOLD_SEC:
        return f"skip_shorts (duration={duration}s)"

    min_d = int(rule["min_duration"] or 0)
    if min_d > 0 and duration > 0 and duration < min_d:
        return f"min_duration {min_d}s > {duration}s"

    max_d = int(rule["max_duration"] or 0)
    if max_d > 0 and duration > 0 and duration > max_d:
        return f"max_duration {max_d}s < {duration}s"

    incl = _try_regex(rule["title_regex"])
    if incl is not None and not incl.search(title):
        return f"title_regex /{rule['title_regex']}/ no match"

    excl = _try_regex(rule["title_excludes"])
    if excl is not None and excl.search(title):
        return f"title_excludes /{rule['title_excludes']}/ matched"

    tags_any_raw = (rule["tags_any"] or "").strip()
    if tags_any_raw:
        try:
            wanted = {str(t).strip().lower() for t in json.loads(tags_any_raw) if str(t).strip()}
        except (TypeError, ValueError, json.JSONDecodeError):
            wanted = set()
        if wanted:
            have = set(_video_tags(video))
            if not (wanted & have):
                return f"tags_any {sorted(wanted)} not in video tags"

    return None


# ---------------------------------------------------------------------------
# Routing query
# ---------------------------------------------------------------------------

def evaluate_video(conn: sqlite3.Connection, video) -> RouteResult:
    """Run all enabled rules for the video's source against the video.

    Returns the first-matching rule per destination plus a list of
    rejects for the rules that didn't match (useful for the "test" UI).

    `video` must be a Row with at least: video_id, source_id, title,
    duration_sec, live_status, tags_json.
    """
    rules = conn.execute(
        """SELECT * FROM routing_rules
            WHERE enabled = 1
              AND (source_id = ? OR source_id IS NULL)
            ORDER BY priority ASC, id ASC""",
        (video["source_id"],),
    ).fetchall()

    matches: dict[int, Match] = {}     # destination_id -> first match
    rejects: list[Reject] = []

    for r in rules:
        if r["destination_id"] in matches:
            continue  # earlier higher-priority rule already won this dest
        reason = _check_rule(r, video)
        if reason is None:
            matches[r["destination_id"]] = Match(
                destination_id=int(r["destination_id"]),
                profile_id=r["profile_id"],
                rule_id=int(r["id"]),
                rule_label=r["label"] or f"rule #{r['id']}",
            )
        else:
            rejects.append(Reject(
                destination_id=int(r["destination_id"]),
                rule_id=int(r["id"]),
                rule_label=r["label"] or f"rule #{r['id']}",
                reason=reason,
            ))

    return RouteResult(
        video_id=video["video_id"],
        matches=list(matches.values()),
        rejects=rejects,
    )


# ---------------------------------------------------------------------------
# Side-effecting wrapper: enqueue ledger rows for matches
# ---------------------------------------------------------------------------

class EnqueueStats(NamedTuple):
    matched: int       # rule matches produced
    enqueued: int      # new ledger rows inserted
    skipped: int       # already had a uploaded/queued/uploading ledger row
    no_match: int      # videos with zero matching rules
    download_queued: int = 0  # NEW: download_queue rows newly inserted


def route_and_enqueue(
    conn: sqlite3.Connection,
    source_id: int,
    video_ids: Optional[Iterable[str]] = None,
    triggered_by: str = "cron",
) -> EnqueueStats:
    """For every catalog video in `source_id` (or restricted to `video_ids`),
    evaluate the rules and INSERT OR IGNORE a `queued` ledger row for each
    matching destination.

    Returns stats. Caller is responsible for committing the transaction.

    Idempotent: a (video, destination) pair already in the ledger with
    status in ('queued','uploading','uploaded') is left untouched -- the
    auto-dispatcher / catalog UI's 'mark uploaded' / etc. continue to win.
    """
    where = ["source_id = ?"]
    params: list = [source_id]
    if video_ids is not None:
        ids = [str(v) for v in video_ids]
        if not ids:
            return EnqueueStats(0, 0, 0, 0)
        where.append("video_id IN (" + ",".join("?" * len(ids)) + ")")
        params.extend(ids)
    sql = (
        "SELECT video_id, source_id, title, duration_sec, live_status, "
        "tags_json FROM catalog_videos WHERE " + " AND ".join(where)
        + " AND ignored = 0"
    )
    videos = conn.execute(sql, params).fetchall()

    matched = enqueued = skipped = no_match = 0
    download_queued = 0
    for v in videos:
        # PR6: skip videos that were archived after a successful upload —
        # they were intentionally cleaned off disk and re-downloading them
        # would defeat the purpose of the auto-delete switch.
        try:
            arch = conn.execute(
                "SELECT 1 FROM videos "
                "WHERE youtube_video_id = ? "
                "  AND COALESCE(archived_at, '') <> '' LIMIT 1",
                (v["video_id"],),
            ).fetchone()
        except sqlite3.OperationalError:
            arch = None  # column not yet migrated on a fresh DB
        if arch:
            skipped += 1
            continue
        result = evaluate_video(conn, v)
        if not result.matches:
            no_match += 1
            continue
        matched += len(result.matches)
        # Pick the lowest-priority-number (= top priority) profile_id
        # among matches as the canonical download profile for this video.
        # If multiple destinations want different profiles, the first
        # match wins -- this is consistent with how matches[] is built
        # in evaluate_video (priority ASC, id ASC).
        chosen_profile_id = None
        for m in result.matches:
            if m.profile_id is not None:
                chosen_profile_id = int(m.profile_id)
                break
        any_new_ledger = False
        for m in result.matches:
            existing = conn.execute(
                """SELECT 1 FROM upload_ledger
                    WHERE video_id = ? AND destination_id = ?
                      AND status IN ('queued','uploading','uploaded')
                    LIMIT 1""",
                (v["video_id"], m.destination_id),
            ).fetchone()
            if existing:
                skipped += 1
                continue
            cur = conn.execute(
                """INSERT OR IGNORE INTO upload_ledger
                        (video_id, destination_id, status, source_id,
                         triggered_by, destination_url, error_message)
                   VALUES (?, ?, 'queued', ?, ?, '', '')""",
                (v["video_id"], m.destination_id, source_id, triggered_by),
            )
            if cur.rowcount > 0:
                enqueued += 1
                any_new_ledger = True
            else:
                # UNIQUE(video_id, destination_id) blocked it -- a
                # historical 'failed' or 'removed' row already exists.
                skipped += 1
        # If at least one ledger row was newly enqueued for this video,
        # ensure a download_queue row exists. UNIQUE(video_id) makes
        # this idempotent: re-routing the same video does not duplicate.
        if any_new_ledger:
            cur = conn.execute(
                """INSERT OR IGNORE INTO download_queue
                        (video_id, source_id, profile_id, status,
                         triggered_by)
                   VALUES (?, ?, ?, 'pending', ?)""",
                (v["video_id"], source_id, chosen_profile_id, triggered_by),
            )
            if cur.rowcount > 0:
                download_queued += 1
    return EnqueueStats(matched, enqueued, skipped, no_match, download_queued)
