# 07 — Observability and Audit: Destinations & Auth

**Pillar:** 2 · Destinations & Auth · **Chapter:** Observability and Audit · **Status:** `drafting`  
**Governed by:** `docs/PILLARS/_STANDARD/CHAPTER_STANDARD.md` §2 · `docs/000_AI_DEEP_SPEC_STANDARD.md` §8  
**Depends on:** `docs/PILLARS/02_DESTINATIONS_AND_AUTH/00_PILLAR_OVERVIEW.md`  
**Invariants enforced:** INV-1, INV-2, INV-4  

---

## 1. Domain Event Registry

All significant domain events are emitted asynchronously via the platform event bus:

| Event Name | Trigger Condition | Payload Key Attributes | Redaction Guarantee |
|---|---|---|---|
| `destination.channel.connected` | Operator authorizes new YouTube channel | `channel_id`, `client_id`, `title` | No refresh token in payload (`INV-1`). |
| `destination.token.refreshed` | Proactive background token refresh succeeded | `channel_id`, `expires_at_utc` | No access token or secret in payload. |
| `destination.token.revoked` | Token refresh returned `invalid_grant` | `channel_id`, `reason` | Operator notification triggered. |
| `destination.quota.consumed` | Video or thumbnail upload consumed units | `client_id`, `pacific_date`, `units`, `total_consumed` | Emitted after successful quota decrement. |
| `destination.quota.exhausted` | Client remaining quota < 1600 units | `client_id`, `resets_at_utc` | Alerts delivery scheduler to sleep. |
| `destination.upload.completed` | Chunked upload completed with YouTube ID | `channel_id`, `destination_video_id`, `duration_ms` | Media path redacted. |

---

## 2. Real-Time Prometheus Metrics

```prometheus
# HELP ytr_destination_quota_consumed_units_total Cumulative YouTube quota units consumed.
# TYPE ytr_destination_quota_consumed_units_total counter
ytr_destination_quota_consumed_units_total{client_id="...", operation="upload_video"} 1600

# HELP ytr_destination_quota_remaining_units Daily quota units remaining before Pacific rollover.
# TYPE ytr_destination_quota_remaining_units gauge
ytr_destination_quota_remaining_units{client_id="..."} 5200

# HELP ytr_destination_token_health Status of authorized channel tokens (1 = current status).
# TYPE ytr_destination_token_health gauge
ytr_destination_token_health{channel_id="...", status="VALID"} 1
ytr_destination_token_health{channel_id="...", status="REVOKED"} 0

# HELP ytr_destination_upload_chunk_duration_seconds Latency of resumable chunk PUTs.
# TYPE ytr_destination_upload_chunk_duration_seconds histogram
```

---

## 3. Security & Audit Logging Rules (`INV-1`)

1. **Zero Secret Leakage**: Log formatters strictly strip fields containing `secret`, `token`, `credential`, or `auth_code`.
2. **Audit Trails**: Every token refresh or permission grant is logged with timestamp, channel ID, and result code.
