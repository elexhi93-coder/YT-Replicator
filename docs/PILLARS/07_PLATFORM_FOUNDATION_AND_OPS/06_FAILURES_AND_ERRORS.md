# 06 — Failures, Errors, and Recovery: Platform Foundation & Ops

**Pillar:** 7 · Platform Foundation & Operations · **Chapter:** Failures and Errors · **Status:** `drafting`  
**Governed by:** `docs/PILLARS/_STANDARD/CHAPTER_STANDARD.md` §2 · `docs/000_AI_DEEP_SPEC_STANDARD.md` §7  
**Depends on:** `docs/PILLARS/07_PLATFORM_FOUNDATION_AND_OPS/00_PILLAR_OVERVIEW.md`  
**Invariants enforced:** INV-1, INV-7, INV-10  

---

## 1. Domain Error Classification

```
PlatformBaseError (base)
├── CryptographicError
│   ├── SecretDecryptionError (key mismatch or corrupt tag)
│   └── MasterKeyMissingError (PLATFORM_MASTER_KEY not set)
├── SecurityPolicyError
│   ├── PathTraversalSecurityError (INV-7 directory escape attempt)
│   └── SSRFSecurityViolationError (prohibited private IP or host)
├── AuthorizationError
│   ├── AuthenticationRequiredError (unauthenticated session)
│   └── InsufficientRolePermissionError (viewer attempted admin action)
└── HostEnvironmentError
    └── DiskSpaceFloorExceededError (host disk free space < 10 GB)
```

---

## 2. Exhaustive Error Catalog

| Error Code | Cause | Classification | Recovery / Action |
|---|---|---|---|
| `PLAT_ERR_KEY_MISSING` | `PLATFORM_MASTER_KEY` environment variable missing | **Fatal Startup** | Halt application bootstrap. Alert administrator. |
| `PLAT_ERR_CIPHER_CORRUPT` | Decryption authentication tag mismatch | **Security / Fatal** | Reject token usage immediately (`INV-1`). Log security alert. |
| `PLAT_ERR_PATH_ESCAPE` | Path traversal attempted (`../`) | **Security Violation** | Abort operation immediately (`INV-7`). |
| `PLAT_ERR_SSRF_BLOCKED` | Request targeted RFC 1918 private IP | **Security Violation** | Drop outbound HTTP call immediately (`INV-7`). |
| `PLAT_ERR_AUTH_FORBIDDEN` | User role lacks required permission | **Authorization** | Return HTTP 403 Forbidden with operator banner. |

---

## 3. Worker Process Crash & Host Restart Recovery

When the host system reboots or the worker process restarts:
1. `src.worker.runner` executes a startup sweep before claiming new jobs.
2. Identifies any jobs left in executing phases (`downloading`, `uploading`) associated with this worker PID.
3. Invokes `jobs.api.fail_job(category=TRANSIENT, error_code="WORKER_RESTARTED")` to cleanly release held leases.
4. Cleans any partial temp files created by this worker in `partials/`.
5. Enters standard claim and run loop.
