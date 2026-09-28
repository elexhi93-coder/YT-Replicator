# Core Module — CONTRACT

**Module:** `core`  
**Status:** Stable (U01 complete)  
**Dependencies:** None (INV-12: `core` imports nothing outside the standard library, Django core, and `cryptography`).

---

## 1. Exposed Public API (`core.api`)

All consumer modules must import strictly from `core.api`:

```python
from core.api import (
    # Clock (INV-2) — PacificTimeDTO is the single quota-boundary snapshot
    PACIFIC_TZ,
    PacificTimeDTO,
    now_utc,
    now_pacific,
    next_quota_reset_utc,
    quota_day,
    quota_day_string,
    get_pacific_time,        # -> PacificTimeDTO (contract §3.2)
    get_pacific_date_string, # -> 'YYYY-MM-DD'  (contract §3.2)

    # Exceptions (incl. Pillar 0 §8 port-boundary errors)
    ReplicatorError,         # alias: PillarError
    TransientError,
    PermanentError,
    QuotaExhaustedError,     # alias: QuotaExhausted (see §2.1)
    AuthExpiredError,
    BotChallengeRequiredError,
    PathTraversalSecurityError,
    SSRFSecurityError,
    MasterKeyMissingError,
    SecretDecryptionError,
    NetworkError,            # transient
    RateLimitExceeded,       # transient; carries retry_after_sec
    ResourceTemporarilyUnavailable,
    SourceUrlRejected,       # permanent
    ItemUnavailable,         # permanent
    TermsViolation,          # permanent
    PermanentAuthError,      # base child; not transient => never retried

    # Crypto (AES-256-GCM, INV-1 / ADJ-P2-01)
    encrypt,
    decrypt,

    # Security (INV-7)
    resolve_safe_path,       # (base_root, relative_path) -> Path; raises PathTraversalSecurityError
    is_safe_ssrf_url,        # (url, allowed_domains) -> bool; never raises

    # Settings (U01)
    Settings,                # frozen dataclass, Settings.from_env(env)
    get_settings,            # cached process-wide snapshot
    reset_settings_cache,    # tests only
    APP_SETTING_DEFAULTS,    # docs/03 §11 seed values, one definition

    # URL & Format Validation
    validate_youtube_url,
    extract_video_id,

    # Logging
    get_logger,

    # Ports & contract types (Pillar 0, docs/04 §6 row 2026-09-28)
    SourceProvider, DestinationPlatform, MetadataTransformer,
    PassthroughTransformer, ProgressCallback,
    ResolvedSource, SourceItem, SourceItemDetail,
    MaterializeRequest, MaterializedMedia,
    AuthState, InventoryBatch, DestinationVideoDTO,
    UploadRequest, UploadOutcome,
    TransformInput, TransformResult,
    SourceRef, ChannelRef, VideoRef,
    PROVENANCE_MARKER_REGEX, format_provenance_marker,

    # Port registry (Pillar 0 §3–§5, docs/04 §6 row 2026-09-28)
    PortNotRegistered,
    register_source_provider, get_source_provider,
    register_destination_platform, get_destination_platform,
    register_metadata_transformer, get_metadata_transformer,
    reset_port_registry,
)
```

### 1.1 Function notes

| Function | Errors | Covered by |
|---|---|---|
| `resolve_safe_path(base_root, relative_path)` | `PathTraversalSecurityError` | `TestSecurity` (4 tests: valid, `../`, absolute escape, arg order) |
| `is_safe_ssrf_url(url, allowed_domains)` | never raises (`bool`) | `TestSecurity` (3 tests: allow, host-bad, IP/scheme/empty) |
| `get_pacific_time()` | none | `TestClock.test_get_pacific_time_dto_is_consistent` |
| `get_pacific_date_string()` | none | `TestClock.test_get_pacific_date_string_format` |
| `quota_day(now)` | none (naive = UTC) | `TestClock` incl. DST transitions |
| `encrypt` / `decrypt` | `MasterKeyMissingError`, `SecretDecryptionError`, `TypeError` | `TestCrypto` (8 tests) |
| `Settings.from_env(env)` | `ValueError` on non-integer env | `TestSettings` (4 tests) |
| `PassthroughTransformer.transform` | never raises (§5.1) | `TestPorts.test_passthrough_transformer_never_raises` |
| `get_source_provider()` and siblings | `PortNotRegistered` | `TestPortRegistry` (8 tests, `tests/test_registry.py`) |
| `register_*` / `reset_port_registry` | never raises | `TestPortRegistry` (factory per get, re-registration, independence, reset, passthrough default) |

### 1.2 The port registry

`worker` and `media` need the Port A adapter but may not import `sources`
(docs/04 §2/§3), so the dependency is inverted in exactly one place:

```python
from core.api import register_source_provider, get_source_provider
register_source_provider(YouTubeSourceProviderFactory)  # at process startup
provider = get_source_provider()                        # anywhere, in any module
```

* Every `get_*` calls its factory, so a caller always receives a usable
  instance and a test can swap behaviour by re-registering.
* Asking for an unregistered port raises `PortNotRegistered` — a
  configuration error naming the port, not a domain failure.
* `get_metadata_transformer()` falls back to `PassthroughTransformer`;
  v1 needs no registration.
* `reset_port_registry()` is for tests only. The binding itself is installed
  by `ui.apps.UiConfig.ready`.

---

## 2. Invariants Maintained by `core`

- **INV-CLOCK-1:** YouTube quota reset strictly aligns with `America/Los_Angeles` midnight, correctly accounting for Daylight Saving transitions (PST vs PDT).
- **INV-PATH-1:** Path traversal attempts outside designated media roots raise `PathTraversalSecurityError` and are immediately aborted.
- **INV-SSRF-1:** Ingestion URLs are strictly validated against genuine YouTube endpoints; internal network IPs, arbitrary web domains, and cloud metadata IPs (`169.254.169.254`) are blocked.
- **INV-ERR-1:** All application exceptions inherit from `ReplicatorError`, bifurcating into recoverable (`TransientError`) and fatal (`PermanentError`).
- **INV-1:** Secrets are encrypted at rest with AES-256-GCM (`encrypt`/`decrypt`, envelope `base64(iv + ciphertext + tag)`, 96-bit random nonce, 128-bit tag). The 32-byte master key comes from `PLATFORM_MASTER_KEY` (hex, base64, or utf-8). Missing/invalid key raises `MasterKeyMissingError`; any corrupt or tampered envelope raises `SecretDecryptionError`.
- **INV-2:** `quota_day()` / `get_pacific_time()` are the only quota-day evaluators; DST transitions (2026-03-08 spring-forward, 2026-11-01 fall-back) are covered by tests.
- **INV-7:** `resolve_safe_path` and `is_safe_ssrf_url` guard all external I/O (Pillar 7 invariant table).
- **INV-11:** every file under `src/core/` ≤ 600 lines (`tests/test_module_size.py`).
- **INV-12 (boundary):** Consumers import only from `core.api`; `core` itself imports no sibling module.

### 2.1 Spec reconciliations (decided here, recorded for U25)

1. **`resolve_safe_path` argument order.** The first U01 commit shipped `(target_path, base_root)`; the locked contract (Pillar 7 §3.3) specifies `(base_root, relative_path)`. The code was changed to match the contract; tests assert the contract order.
2. **`QuotaExhausted` classification.** Pillar 0 §8 draws it under `PermanentError`, but Pillar 0's own `04_LOGIC_AND_RULES.md` maps quota 403s to *"QuotaExhaustedError (transient)"* and `jobs` must reschedule rather than fail. `QuotaExhausted` is an **alias of `QuotaExhaustedError(TransientError)`**.
3. **`PillarError`** is an alias of `ReplicatorError` — §8 requires one error root, not two.
4. **`PermanentAuthError`** hangs directly off the base per the §8 tree; callers classify retryability with `isinstance(err, TransientError)`.

---

## 2.2 Test Coverage

- `src/core/tests/test_core.py` — `TestClock` (incl. DST spring-forward/fall-back), `TestCrypto`, `TestExceptions` (incl. port-boundary hierarchy), `TestLogging`, `TestSecurity` (path + SSRF), `TestSettings`, `TestPorts`, `TestValidators`.
- `src/core/tests/test_registry.py` — `TestPortRegistry` (8 tests): unregistered port raises, factory called per `get`, protocol conformance, re-registration replaces, ports are independent keys, `reset` clears, passthrough default, registered transformer wins.
- `tests/test_module_boundaries.py` — INV-11/INV-12 AST enforcement (U04).
- `tests/test_module_size.py` — 600-line cap (U04).
