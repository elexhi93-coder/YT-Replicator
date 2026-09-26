# External Storage Guide

This guide explains how to point project003's downloads at an external drive
in a way that **survives reboots even if the Windows drive letter changes**.

## How storage works in project003

- The watcher container writes files to a path **inside the container**
  (default: `/downloads`).
- That container path is bind-mounted from a **host path** in `.env`
  (default: `${DOWNLOADS_PATH:-./downloads}`).
- New downloads are organized as:
  `<root>/<ChannelName>/<video_id>/<title>.mp4`
- You can override the in-container root from the dashboard
  (Downloads → Storage Location), but the host bind-mount must already exist.

---

## Option A — Stable Windows mount path (recommended)

External drive letters can change between reboots. Avoid the problem entirely
by mounting the volume into an **NTFS folder** instead of a drive letter.

1. Connect the external drive.
2. Open **Disk Management** (`Win+X` → Disk Management).
3. Right-click the external partition → **Change Drive Letter and Paths…**
4. Click **Add** → **Mount in the following empty NTFS folder** → **Browse**.
5. Pick or create an empty folder, e.g. `C:\Mounts\Media`.
6. Click **OK**. The drive is now reachable via `C:\Mounts\Media`
   regardless of which letter Windows assigns it later.
7. Edit the project's `.env`:
   ```env
   DOWNLOADS_PATH=C:/Mounts/Media
   ```
8. From the project root run:
   ```
   docker compose up -d
   ```
   The watcher and dashboard containers will remount the new path at
   `/downloads` and `/shared/downloads`.

You do **not** need to touch the Storage Location override in this case —
the default `/downloads` already points at the external volume.

---

## Option B — Multiple roots (default + external)

Useful if you want to keep recent downloads on internal SSD and archive
to an external drive later.

1. Set up a stable mount path for the external drive (Option A, steps 1-6).
2. Add a second variable to `.env`:
   ```env
   DOWNLOADS_PATH=./downloads
   EXTERNAL_DOWNLOADS_PATH=C:/Mounts/Media
   ```
3. In `docker-compose.yml`, add a second bind mount to the **watcher** service
   (and dashboard, if you want it visible there too):
   ```yaml
   watcher:
     volumes:
       - ${DOWNLOADS_PATH:-./downloads}:/downloads
       - ${EXTERNAL_DOWNLOADS_PATH:-./downloads}:/external
   ```
4. `docker compose up -d`
5. In the dashboard (Downloads → Storage Location) set the override to
   `/external` and click **Save**. The next download cycle will write there.
6. To switch back, clear the override and Save.

---

## Option C — Direct drive letter (not recommended)

If you must use a raw drive letter, set `DOWNLOADS_PATH=D:/downloads` in
`.env` and `docker compose up -d`. **Caveat:** if Windows reassigns the
drive (e.g. `D:` becomes `E:` after a reboot or USB hub change), the
watcher container will start, find an empty `/downloads`, and may
download already-downloaded videos again is **not** an issue —
deduplication is keyed on `videos.youtube_video_id` in the SQLite DB,
not on file presence. But the new files will land in the wrong place,
and the dashboard won't be able to show them. Always prefer Option A.

---

## What happens to previously downloaded files?

- Files already on disk in the old `<root>/<video_id>/` layout are left
  alone. The dashboard reads the absolute path stored in the DB, so they
  remain visible.
- New downloads use the per-channel layout
  `<root>/<ChannelName>/<video_id>/<title>.mp4`.
- You can safely delete downloaded files after upload — the watcher will
  **not** re-download them, because the deduplication check uses the
  `videos` table in SQLite, not the filesystem.

---

## Troubleshooting

**"Saved, but path is not visible to the watcher container"**
The override path you set isn't bind-mounted into the watcher. Either pick
`/downloads` (always available) or add a second bind mount as in Option B.

**Files appear in the dashboard but won't open / 404**
The dashboard container needs a bind mount at `/shared/downloads` covering
the same host path. Check the `dashboard` service in `docker-compose.yml`.

**Drive letter changed after reboot, downloads went to internal disk**
You're using Option C. Switch to Option A (NTFS folder mount).
