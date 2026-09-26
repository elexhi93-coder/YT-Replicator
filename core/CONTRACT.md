# Core Module — CONTRACT

**Module:** `core`  
**Status:** Stable (U01 completed)  
**Dependencies:** None (INV-12: `core` imports nothing outside the standard library and Django core).

---

## 1. Exposed Public API (`core.api`)

All consumer modules must import strictly from `core.api`:

```python
from core.api import (
    # Clock
    PACIFIC_TZ,
    now_utc,
    now_pacific,
    next_quota_reset_utc,
    quota_day_string,
    
    # Exceptions
    ReplicatorError,
    TransientError,
    PermanentError,
    QuotaExhaustedError,
    AuthExpiredError,
    BotChallengeRequiredError,
    PathTraversalSecurityError,
    SSRFSecurityError,
    
    # Security & Path Safety
    resolve_safe_path,
    
    # URL & Format Validation
    validate_youtube_url,
    extract_video_id,
    
    # Logging
    get_logger,
)
```

---

## 2. Invariants Maintained by `core`

- **INV-CLOCK-1:** YouTube quota reset strictly aligns with `America/Los_Angeles` midnight, correctly accounting for Daylight Saving transitions (PST vs PDT).
- **INV-PATH-1:** Path traversal attempts outside designated media roots raise `PathTraversalSecurityError` and are immediately aborted.
- **INV-SSRF-1:** Ingestion URLs are strictly validated against genuine YouTube endpoints; internal network IPs, arbitrary web domains, and cloud metadata IPs (`169.254.169.254`) are blocked.
- **INV-ERR-1:** All application exceptions inherit from `ReplicatorError`, bifurcating into recoverable (`TransientError`) and fatal (`PermanentError`).
