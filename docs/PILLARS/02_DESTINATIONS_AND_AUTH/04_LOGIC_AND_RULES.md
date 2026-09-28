# 04 — Logic and Business Rules: Destinations & Auth

**Pillar:** 2 · Destinations & Auth · **Chapter:** Logic and Business Rules · **Status:** `drafting`  
**Governed by:** `docs/PILLARS/_STANDARD/CHAPTER_STANDARD.md` §2 · `docs/000_AI_DEEP_SPEC_STANDARD.md` §5  
**Depends on:** `docs/PILLARS/02_DESTINATIONS_AND_AUTH/00_PILLAR_OVERVIEW.md`  
**Invariants enforced:** INV-1, INV-2, INV-4, INV-11  

---

## 1. Pacific Day Quota Accounting Engine (`INV-2`)

### 1.1 The Midnight Pacific Rollover Rule
Google Cloud YouTube Data API v3 enforces quota ceilings that reset strictly at **midnight Pacific Time**:
- Timezone: `America/Los_Angeles` (PST UTC-8 / PDT UTC-7).
- Rollover Timestamp: `00:00:00.000` Pacific Time.

### 1.2 Quota Evaluation Algorithm
When a check or reservation occurs:
1. Current UTC time is converted to `America/Los_Angeles`.
2. Date string is derived: `pacific_date = now_pt.strftime("%Y-%m-%d")`.
3. Query `quota_usage` record for `(client_id, pacific_date)` with row-level lock (`SELECT ... FOR UPDATE`).
4. If no record exists, insert row with `consumed_units = 0`.
5. Check: `remaining = daily_limit - consumed_units`.
6. If `remaining < 1600`, upload is rejected with `QuotaExceededError`.
7. If permitted, `consumed_units` is incremented atomically by 1600.

```
UTC Now ────────> Convert to America/Los_Angeles (PT)
                        │
                        ▼
                pacific_date = YYYY-MM-DD
                        │
                        ▼
        SELECT consumed_units FROM quota_usage
        WHERE client_id = :id AND pacific_date = :date
        FOR UPDATE;
                        │
           ┌────────────┴────────────┐
           ▼                         ▼
   consumed + 1600 > limit    consumed + 1600 <= limit
           │                         │
           ▼                         ▼
    Reject: 429 Quota        Permit: UPDATE consumed += 1600
    (Reset at 00:00 PT)      Proceed to Resumable Upload
```

---

## 2. Token Lifecycle & Proactive Refresh Loop

### 2.1 Health State Machine
```
   [ NEW AUTH ] ────────> [ VALID ] (access token fresh)
                             │
            expires in < 5m  │

---

## 3. Resumable Upload Chunking Protocol

To support large media transfers over lossy network links, video uploads strictly follow
Google's Resumable Upload specification:

### 3.1 Upload Session Initialization
1. POST metadata to `https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status`.
2. Header includes:
   - `X-Upload-Content-Type: video/mp4`
   - `X-Upload-Content-Length: {total_file_bytes}`
3. YouTube returns `HTTP 200` with session URI in the `Location` header.

### 3.2 Chunked Transfer Rules
- **Chunk Size**: Multiples of 256 KB. Default chunk size: **8 MB** (`8 * 1024 * 1024` bytes).
- Each chunk sent via PUT to `Location` URI with `Content-Range: bytes {start}-{end}/{total}`.
- If network drops mid-stream:
  - Worker issues empty PUT to `Location` with `Content-Range: bytes */{total}` to query YouTube's current received byte offset (`HTTP 308 Resume Incomplete` with `Range: bytes=0-{last_byte}`).
  - Upload resumes from `{last_byte + 1}`.
- On final chunk completion, YouTube returns `HTTP 200` with the created Video ID.

---

## 4. Provenance & Compliance Injections

### 4.1 Provenance Marker Placement
Before sending the video metadata payload, Pillar 2 ensures the provenance marker format
stipulated by Pillar 0 is appended to the video description:
```text
{original_description}

<!-- YTR:src={source_id}:vid={source_video_id} -->
```
This guarantees downstream auditability and loop prevention without cluttering the public description.

### 4.2 WebP Thumbnail Auto-Conversion
- YouTube Data API v3 rejects `.webp` thumbnail uploads (`HTTP 400 invalidImageFormat`).
- If input thumbnail is WebP:
  - In-memory raster conversion: Pillow (`PIL.Image`) converts WebP bytes to JPEG at 90% quality.
  - Sized to standard 1280x720 aspect ratio if needed, capped under 2 MB.

                             ▼
                        [ EXPIRING ] ──> Refresh Token POST
                             │                 │
                             │                 ├─ Success ──> [ VALID ]
                             │                 ▼
                             └─────────> [ REVOKED / EXPIRED ]
                                         (operator alert)
```

### 2.2 Proactive Refresh Logic
- Access tokens expire after 3,600 seconds (1 hour).
- Upload worker checks `token_expires_at`:
  - If `token_expires_at - now_utc <= 300` (within 5 minutes of expiration):
    - Decrypt `refresh_token` using `core.crypto.decrypt()` (`INV-1`).
    - POST to `https://oauth2.googleapis.com/token` with `grant_type=refresh_token`.
    - On HTTP 200: store new `access_token` and update `token_expires_at = now + expires_in`.
    - On HTTP 400 `invalid_grant`: set `token_health = 'REVOKED'`, halt upload, emit audit event.
