# 07 — Observability and Audit: Platform Foundation & Ops

**Pillar:** 7 · Platform Foundation & Operations · **Chapter:** Observability and Audit · **Status:** `drafting`  
**Governed by:** `docs/PILLARS/_STANDARD/CHAPTER_STANDARD.md` §2 · `docs/000_AI_DEEP_SPEC_STANDARD.md` §8  
**Depends on:** `docs/PILLARS/07_PLATFORM_FOUNDATION_AND_OPS/00_PILLAR_OVERVIEW.md`  
**Invariants enforced:** INV-1, INV-11  

---

## 1. Universal Audit Trail Registry (`audit_event`)

Pillar 7 provides the centralized audit logging mechanism used by the entire platform.
Every administrative modification, credential save, or state change writes an immutable audit record:

| Audit Action | Emitting Component | Redacted Attributes | Purpose |
|---|---|---|---|
| `auth.login.success` | `accounts` | Password hash | Session tracking |
| `auth.login.failed` | `accounts` | Input credentials | Brute-force detection |
| `destinations.client.saved` | `destinations` | `client_secret` (`INV-1`) | Client configuration audit |
| `pipelines.status.toggled` | `pipelines` | None | Administrative change log |
| `ops.scheduler.paused` | `ops` | None | Worker execution pause audit |
| `media.retention.executed` | `media` | None | Storage reclamation audit |

---

## 2. Real-Time Prometheus Metrics

```prometheus
# HELP ytr_platform_workers_active Current number of alive worker processes.
# TYPE ytr_platform_workers_active gauge
ytr_platform_workers_active 4

# HELP ytr_platform_audit_events_total Cumulative audit events recorded.
# TYPE ytr_platform_audit_events_total counter
ytr_platform_audit_events_total{event="auth.login.success"} 42
ytr_platform_audit_events_total{event="pipelines.status.toggled"} 12

# HELP ytr_platform_http_requests_total Total HTTP requests handled by web server.
# TYPE ytr_platform_http_requests_total counter
ytr_platform_http_requests_total{status="200", method="GET"} 3491
ytr_platform_http_requests_total{status="403", method="POST"} 3
```

---

## 3. Liveness Probes (`/healthz`)

- **Route**: `GET /healthz`
- **Behavior**: Unauthenticated lightweight health check for container orchestrators and monitoring agents.
- **Checks**:
  1. PostgreSQL database connectivity (`SELECT 1`).
  2. Free space on primary storage root (`> 10 GB`).
  3. Master cryptographic key is loaded.
- Returns HTTP 200 `{"status": "healthy"}` if all pass, or HTTP 503 `{"status": "unhealthy", "reason": "..."}` if any check fails.
