# 06 — Failures, Errors, and Recovery: Destinations & Auth

**Pillar:** 2 · Destinations & Auth · **Chapter:** Failures and Errors · **Status:** `drafting`  
**Governed by:** `docs/PILLARS/_STANDARD/CHAPTER_STANDARD.md` §2 · `docs/000_AI_DEEP_SPEC_STANDARD.md` §7  
**Depends on:** `docs/PILLARS/02_DESTINATIONS_AND_AUTH/00_PILLAR_OVERVIEW.md`  
**Invariants enforced:** INV-1, INV-2, INV-4  

---

## 1. Domain Error Taxonomy

All exceptions raised by Pillar 2 inherit from `DestinationsError` and categorize failures
into Transient (retryable by worker) and Permanent (requires human intervention).

```
DestinationsError (base)
├── QuotaExceededError (Transient — resets at 00:00 PT)
├── TokenExpiredError (Transient — proactively refreshed)
├── TokenRevokedError (Permanent — operator re-auth required)
├── ResumableUploadInterruptedError (Transient — chunk retryable)
├── VideoRejectedByPlatformError (Permanent — violation/duplicate/bad metadata)
└── SecretDecryptionError (Fatal — key misconfiguration)
```

---

## 2. Exhaustive Error Catalog

| Error Code | HTTP / API Cause | Classification | Action / Remediation |
|---|---|---|---|
| `DEST_ERR_QUOTA_EXCEEDED` | Consumed units + 1600 > daily limit, or Google HTTP 403 `quotaExceeded` | **Transient** | Reject upload immediately. Schedule retry after `00:00:00 PT` rollover (`INV-2`). |
| `DEST_ERR_TOKEN_REVOKED` | Google OAuth token endpoint returns HTTP 400 `invalid_grant` | **Permanent** | Mark `authorized_channel.token_health = 'REVOKED'`. Alert operator via UI pill. |
| `DEST_ERR_CHUNK_FAILED` | Network timeout or drop during chunk PUT | **Transient** | Query upload session byte offset via empty PUT; resume transfer from byte offset. |
| `DEST_ERR_DUPLICATE_VIDEO` | YouTube HTTP 400 `duplicateVideo` | **Permanent** | Video hash already exists on destination channel. Fail job permanently; log receipt. |
| `DEST_ERR_TERMS_VIOLATION` | YouTube HTTP 400 `termsOfServiceViolation` | **Permanent** | Video content or title violates YouTube policy. Halt channel uploads and alert operator. |
| `DEST_ERR_DECRYPT_FAILED` | Master platform key mismatch or corrupted ciphertext | **Fatal** | Fail immediately. Log critical security error without leaking ciphertext bytes (`INV-1`). |

---

## 3. Quota Recovery Protocol (`INV-2`)

When `DEST_ERR_QUOTA_EXCEEDED` occurs:
1. The error carries the exact UTC timestamp of the upcoming midnight Pacific rollover:
   ```python
   class QuotaExceededError(DestinationsError):
       resets_at_utc: datetime
       units_needed: int = 1600
   ```
2. The caller (Job Engine / Delivery) delays queued tasks targeting this client until `resets_at_utc`.
3. No additional API calls are dispatched to YouTube until the Pacific day rolls over.
