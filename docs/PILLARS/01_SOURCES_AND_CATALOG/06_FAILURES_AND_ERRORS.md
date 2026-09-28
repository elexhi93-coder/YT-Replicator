# 06 — Failures and Errors: Sources & Catalog

**Pillar:** 1 · Sources & Catalog · **Chapter:** Failures and Errors · **Status:** `drafting`  
**Governed by:** `docs/PILLARS/_STANDARD/CHAPTER_STANDARD.md` §2 · `docs/000_AI_DEEP_SPEC_STANDARD.md`  
**Depends on:** `docs/PILLARS/01_SOURCES_AND_CATALOG/03_INTERFACE_CONTRACT.md` · `docs/PILLARS/01_SOURCES_AND_CATALOG/04_LOGIC_AND_RULES.md`  
**Invariants enforced:** INV-7, F-48  

---

## 1. Failure Mode Taxonomy

Errors encountered during source registration, scanning, and metadata hydration are
categorized into three strict operational classes:

1. **Transient Failures (Retryable)**: Network timeouts, DNS blips, temporary YouTube HTTP 503 errors.
   - Handled automatically by the job engine with exponential backoff and jitter.
2. **Permanent Failures (Source Level - Non-Retryable)**: Channel deleted, channel terminated for TOS, SSRF violation, invalid URL syntax.
   - Marks source `sync_status = 'FAILED'`, alerts operator, stops automatic polling.
3. **Skip Failures (Item Level - F-48 Resilience)**: Private video, deleted video, geo-blocked video, age-restricted item without cookies.
   - **Never aborts the scan**. Item is logged to audit trail with reason code; scan completes successfully or with `PARTIAL_WARNING`.

---

## 2. Comprehensive Error Catalog

| Error Code | Error Class | Trigger Condition | Operator / UI Presentation | System Action & Recovery |
|---|---|---|---|---|
| `SRC_ERR_SSRF_BLOCKED` | Permanent | Input URL points to private IP, localhost, or non-YouTube domain. | "Invalid source URL: Only public YouTube channel or playlist URLs are allowed." | Registration rejected immediately. No background job enqueued. |
| `SRC_ERR_CHANNEL_NOT_FOUND` | Permanent | YouTube returns HTTP 404 for channel/playlist handle or ID. | "Source not found: Please verify that the YouTube channel or playlist exists." | Source marked `FAILED`. Polling paused. |
| `SRC_ERR_CHANNEL_TERMINATED` | Permanent | Channel was closed due to Terms of Service violations. | "Channel terminated: This channel has been removed by YouTube." | Source marked `FAILED`. Operator prompted to archive source. |
| `SRC_ERR_HTTP_429_RATE_LIMIT` | Transient | YouTube returns HTTP 429 or bot-detection challenge page. | "Rate limit encountered: Cooling off for 15 minutes before retry." | Queue worker halts scans for that source for 15 minutes. Emits `EVENT_SOURCES_RATE_LIMITED`. |
| `SRC_ERR_NETWORK_TIMEOUT` | Transient | Socket timeout (> 30s) reaching YouTube endpoints. | "Network timeout during scan. Retrying automatically..." | Retried up to 3 times with exponential backoff (10s, 30s, 60s). |
| `ITEM_SKIP_DELETED` | Skip (`F-48`) | Video in playlist was deleted by uploader. | Amber warning pill: "1 item skipped (Video deleted)". | Logged in scan results; catalog updates `availability = 'deleted'`. Scan continues. |
| `ITEM_SKIP_PRIVATE` | Skip (`F-48`) | Video was set to private by uploader. | Amber warning pill: "1 item skipped (Video private)". | Logged in scan results; catalog updates `availability = 'private'`. Scan continues. |
| `ITEM_SKIP_GEO_BLOCKED` | Skip (`F-48`) | Video is unavailable in the host server's geographic region. | Amber warning pill: "1 item skipped (Region restricted)". | Logged in scan results; catalog updates `availability = 'unlisted'` with note. Scan continues. |
| `ITEM_SKIP_AGE_RESTRICTED` | Skip (`F-48`) | Deep hydration blocked by YouTube login requirement. | "Hydration skipped: Age restricted content requires session cookies." | Flat scan metadata retained; deep hydration marked pending/skipped. |

---

## 3. The F-48 Partial-Failure Recovery Algorithm

To prevent defect `D-07` (batch scrape abort on single corrupted item):

```python
def process_scan_batch(source_id: UUID, entries: Iterable[dict]) -> ScanSummary:
    summary = ScanSummary(total=0, upserted=0, skipped=0)
    
    for raw_entry in entries:
        summary.total += 1
        video_id = raw_entry.get("id")
        
        # Guard: Check for known skip conditions
        if not video_id or raw_entry.get("title") == "[Private video]":
            record_item_skip(source_id, video_id, reason="ITEM_SKIP_PRIVATE")
            summary.skipped += 1
            continue
            
        if raw_entry.get("title") == "[Deleted video]":
            record_item_skip(source_id, video_id, reason="ITEM_SKIP_DELETED")
            summary.skipped += 1
            continue
            
        try:
            dto = parse_flat_entry(raw_entry)
            upsert_catalog_video(dto)
            summary.upserted += 1
        except Exception as ex:
            # Defensive catch-all to protect the batch
            logger.warning(f"Failed to process video {video_id} in source {source_id}: {ex}")
            record_item_skip(source_id, video_id, reason="ITEM_SKIP_UNEXPECTED", details=str(ex))
            summary.skipped += 1
            continue

    # Final source status update
    if summary.skipped > 0 and summary.upserted > 0:
        set_source_status(source_id, status="PARTIAL_WARNING")
    elif summary.upserted > 0:
        set_source_status(source_id, status="IDLE")
    else:
        set_source_status(source_id, status="FAILED", error="No reachable videos in source")

    return summary
```

---

## 4. Change Log

- **2026-09-28:** Authored `06_FAILURES_AND_ERRORS.md` defining error classifications, UI messages, bot-check cooling procedures, and the F-48 partial-failure recovery algorithm.
