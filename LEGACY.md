# Legacy reference — `project003_bundle/`

**Status: read-only archive.**

---

## 1. What this folder is

The previous implementation of this project, in three generations, at the point
where its developer stopped. It is the reference we rebuilt from — not a
codebase we build on.

| Generation | What it was |
|---|---|
| 1 | Desktop Python/tkinter downloader and uploader, with a plugin system and PyInstaller builds. |
| 2 | Headless Docker watcher + n8n webhook orchestration + FFmpeg processor. |
| 3 | Flask dashboard + SQLite, direct YouTube upload, catalog, quota rotation. |

All three coexist in the same tree. Nothing was removed when the next generation
was added, which is why 62 documents, 81 Python files and 61 templates describe
three different products at once.

---

## 2. The five rules

1. **Do not edit anything here.** It is evidence, not code. A change destroys
   the evidence `docs/01` cites.
2. **Do not import, install, or run it.** It is not on the path, not a
   dependency, and never will be.
3. **Do not copy code from here without first reading its disposition** in
   `docs/01_LEGACY_REVERSE_ENGINEERING.md` — `KEEP`, `ADAPT`, or `DROP`.
   Copying a `DROP` is how a fixed defect comes back.
4. **Where its documents and its code disagree, the code is the evidence.**
   Several of its documents describe tables, routes and packages that do not
   exist (defects D-01, D-27).
5. **Never commit what `.gitignore` excludes.** In particular: `.env`, `db/`,
   the backup files, the ZIP, and the credential export in
   `docs/Export-Import/` — that last one contains **refresh tokens**, which do
   not expire.

---

## 3. Why read-only

`docs/01` records **56 features** dispositioned `KEEP`/`ADAPT`/`DROP` and **27
defects** with their evidence. Keeping the original intact is what makes those
citations checkable: anyone can open the cited file and confirm the defect was
real.

Its own documentation was already internally inconsistent before any of us
touched it, so the folder is treated as a source of facts about *behaviour*, and
its prose as corroboration only.

---

## 4. Read next

- `docs/01_LEGACY_REVERSE_ENGINEERING.md` — what it did, what we keep, what we
  refuse, and why.
- `docs/00_DESIGN_PRINCIPLES.md` — the rules the next implementation follows
  instead.

If you find something in this folder that seems useful and it is not in `docs/01`
at all, that is a **gap in the inventory**, not a licence to copy it: record it in
`01` first, decide its disposition, then act.