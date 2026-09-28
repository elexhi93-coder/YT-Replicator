# 04 — Logic and Business Rules: Platform Foundation & Ops

**Pillar:** 7 · Platform Foundation & Operations · **Chapter:** Logic and Business Rules · **Status:** `drafting`  
**Governed by:** `docs/PILLARS/_STANDARD/CHAPTER_STANDARD.md` §2 · `docs/000_AI_DEEP_SPEC_STANDARD.md` §5  
**Depends on:** `docs/PILLARS/07_PLATFORM_FOUNDATION_AND_OPS/00_PILLAR_OVERVIEW.md`  
**Invariants enforced:** INV-1, INV-2, INV-7, INV-10, INV-11  

---

## 1. Authenticated AES-256-GCM Cipher Implementation (`INV-1`, `ADJ-P2-01`)

### 1.1 Envelope Specification
- Cipher: AES-256 in Galois/Counter Mode (GCM).
- Key Length: 256 bits (32 bytes), sourced from `PLATFORM_MASTER_KEY` environment variable.
- Nonce / IV: 96 bits (12 bytes), cryptographically random per encryption operation via `os.urandom(12)`.
- Authentication Tag: 128 bits (16 bytes) ensuring tamper detection.
- Serialization: Base64 encoding of concatenated bytes: `base64(iv + ciphertext + tag)`.

```
Plaintext ──▶ [ AES-256-GCM + Random IV (12B) ] ──▶ [ IV + Ciphertext + Tag (16B) ]
                                                            │
                                                            ▼
                                                Base64 URL-safe String
```

---

## 2. The Universal Pacific Time Clock Engine (`INV-2`)

### 2.1 Rollover & Calculation Algorithm
- Timezone: `zoneinfo.ZoneInfo("America/Los_Angeles")`.
- When calculating calendar date:
  ```python
  now_utc = datetime.now(timezone.utc)
  now_pacific = now_utc.astimezone(PACIFIC_TZ)
  pacific_date = now_pacific.date()
  ```
- Calculating next midnight rollover in UTC:
  ```python
  next_midnight_pacific = datetime.combine(
      pacific_date + timedelta(days=1),
      time.min,
      tzinfo=PACIFIC_TZ
  )
  next_midnight_utc = next_midnight_pacific.astimezone(timezone.utc)
  ```
All quota calculations across Pillars 2 and 6 call this canonical clock implementation.

---

## 3. Generic Worker Run Loop & Admission Gating

### 3.1 The Worker Execution Flow (`src.worker.runner`)
The worker loop operates as a pure orchestrator with **zero embedded business logic**:
```
┌────────────────────────────────────────────────────────┐
│ 1. Heartbeat Tick (record worker liveness)             │
├────────────────────────────────────────────────────────┤
│ 2. Admission Gate Check:                               │
│    - Is global scheduler paused? If yes: sleep & loop. │
│    - Is host disk below 10 GB floor? If yes: warn.     │
├────────────────────────────────────────────────────────┤
│ 3. Atomic Job Claim:                                   │
│    - Claim via jobs.api.claim_next_job(worker_id)      │
│    - If None: sleep with adaptive backoff (1s -> 5s).  │
├────────────────────────────────────────────────────────┤
│ 4. Dispatch by Task Type:                              │
│    - 'sources.scan'     ──▶ invoke sources handler     │
│    - 'media.download'   ──▶ invoke media handler       │
│    - 'delivery.upload'  ──▶ invoke delivery handler    │
├────────────────────────────────────────────────────────┤
│ 5. Report Result:                                      │
│    - Success ──▶ jobs.api.complete_job()               │
│    - Error   ──▶ jobs.api.fail_job(category, code)     │
└────────────────────────────────────────────────────────┘
```
