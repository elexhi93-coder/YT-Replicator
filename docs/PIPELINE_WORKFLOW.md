# Pipeline Workflow

## Domain model

A **Pipeline** is a required first-class object. It connects one or more YouTube **Sources** to one or more YouTube **Destinations**, and owns the settings for discovery, backfill, priorities, and upload behavior.

A Source is the origin channel and its video catalog. A Destination is the YouTube channel the application is authorized to upload to. Source catalog state and upload history are separate: removing a Source or Pipeline must not erase the durable record of prior uploads.

## Video states

Keep these concepts distinct:

- **Cataloged:** metadata is known (video ID, title, thumbnail, publish date, duration, and available public statistics). The video file has not necessarily been downloaded.
- **Queued / Downloading:** the worker has selected the video and is acquiring its media file.
- **Uploading:** the media is being sent to a particular Destination.
- **Uploaded:** YouTube confirmed success; store the destination video ID and URL.
- **Failed / Skipped:** record the reason and leave the item visible for retry or operator action.

Local media files are temporary implementation artifacts. The upload ledger is durable and survives file cleanup.

## Pipeline stages

### Stage 1: Initial catalog and backfill

1. The operator configures a Pipeline, its Source(s), Destination(s), priorities, and upload settings.
2. Scan each Source and store its video metadata without downloading the full video list.
3. Sync each Destination's YouTube uploads inventory.
4. Compare source videos with upload history for that Source-Destination pair.
5. Present or queue only missing videos, following the configured order and rate limits.
6. For each candidate: download, upload to the Destination, record the result, and remove the local file only after confirmed success.

The upload ledger is keyed by Workspace, source video ID, and destination ID. Store the resulting YouTube video ID/URL and status. Do not cascade-delete ledger rows when a Pipeline or Source is removed.

For videos uploaded before YT-Replicator tracked them, exact matching may not be possible. Use an explicit reconciliation flow; title/date/thumbnail similarity can suggest matches but should not silently suppress uploads on its own.

### Stage 2: Ongoing monitoring

After the initial backlog is resolved according to the Pipeline's completion policy, monitor Sources for new videos. Target near-real-time detection, with a reliable periodic scan as reconciliation/fallback. The detection mechanism and interval still need to be selected; the legacy implementation's 15-minute polling is not a requirement.

When a new video appears, catalog it, compare it against the durable ledger for each Destination, and enqueue only missing source-destination pairs.

## Priorities and multiple destinations

Source/channel priority controls which work is considered first. Each Destination has an independent outcome: a video can be uploaded to one Destination and still pending or failed at another. The ledger must represent those results separately.

## Open decisions

- Does Stage 1 move to monitoring only when every eligible video succeeded, or can an operator explicitly skip a permanently failed item?
- Retry policy: automatic attempt count/backoff, and when a failure becomes operator-visible.
- Whether to automatically start backfill upon Pipeline activation or require review/confirmation after catalog comparison.
- Destination inventory sync cadence and how to reconcile older uploads that lack a ledger entry.
- Whether upload metadata (especially title/description rewriting or AI assistance) is enabled, and whether edits require operator review.
- Meaning of "immediate" detection and the acceptable delay for the first release.
