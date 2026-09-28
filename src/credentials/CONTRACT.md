# credentials.CONTRACT — Google Clients & Authorized Channels (U05)

**Module:** `credentials` · **Status:** complete (Wave 1)
**May import:** `core.api`, `accounts.api` (docs/04 §3). Nothing else.
**Owns:** `google_client`, `authorized_channel` (docs/03 §4), the OAuth flow, and
the token lifecycle. It never uploads media — that is `youtube` (U09).

---

## 1. Public surface (`credentials.api`, INV-12)

| Symbol | Signature | Behaviour |
|---|---|---|
| `add_google_client(workspace, *, label, client_id, client_secret, daily_upload_cap=6, is_active=True)` | → `GoogleClient` | Encrypts the secret before insert (`core.api.encrypt`, INV-1). Rejects a blank label/client id and a cap below 1. |
| `update_google_client(client, *, label, client_secret, daily_upload_cap, is_active)` | → `GoogleClient` | Rotates the secret (re-encrypted) and the mutable fields. `client_id` is immutable by design. |
| `client_secret(client)` | → `str` | Decrypts **in memory only** — the single place a plaintext secret exists, and it is never logged or returned across a pillar boundary. |
| `get_client(workspace, *, label=None, client_id=None)` | → `GoogleClient` | Raises `ClientNotFound`. |
| `list_clients(workspace)` | → `list[GoogleClient]` | Ordered by label. |
| `deactivate_client(client)` | → `GoogleClient` | Stops new work without deleting channels (mirrors `SET_NULL` intent). |
| `bind_channel(client, *, channel_id, title="", scopes=())` | → `AuthorizedChannel` | Idempotent on `(workspace, channel_id)`: re-binding keeps the row and its history. |
| `new_channel(client, *, title="")` | → `AuthorizedChannel` | Creates a row with a unique `pending-…` id when the canonical `UC…` id is not known yet. |
| `get_channel(channel_id, *, workspace=None)` | → `AuthorizedChannel` | Accepts a pk or a canonical id; raises `ChannelNotFound`. |
| `list_channels(workspace)` | → `list[AuthorizedChannel]` | Ordered by title. |
| `revoke_channel(channel, *, reason="")` | → `AuthorizedChannel` | Terminal state; drops both tokens so nothing can silently retry. |
| `start_oauth(channel, *, redirect_uri, scopes)` | → `OAuthStart` | Returns the Google consent URL plus a Django-signed `state` carrying the channel pk. `access_type=offline` + `prompt=consent` (else Google withholds the refresh token). |
| `read_oauth_state(state)` | → `AuthorizedChannel` | Verifies signature and age (`OAUTH_STATE_MAX_AGE_SECONDS`, 900 s); raises `OAuthStateInvalid`. |
| `complete_oauth(code, *, state, redirect_uri, http_client=None, now=None)` | → `AuthorizedChannel` | Exchanges the code, resolves the channel identity when the row is pending (merging into an existing row for that `UC…` id), and stores **encrypted** tokens. |
| `refresh_token(channel)` | → `str` | Decrypts the refresh token; raises `TokenMissing`. |
| `token_health(channel, *, now=None)` | → `str` | `missing`/`valid`/`expiring`/`invalid`/`revoked` (Pillar 2 §2.1). Terminal states win. |
| `refresh_channel_token(channel, *, http_client=None, now=None)` | → `AuthorizedChannel` | Proactive refresh; on Google `invalid_grant` records `revoked` and raises `AuthRevoked`. |
| `valid_access_token(channel, *, http_client=None, now=None)` | → `str` | **The only way to obtain a token.** Refreshes when the token is inside the 5-minute window, so no caller can forget the rule. |
| `OAuthStart` | frozen dataclass | `authorization_url`, `state`. |
| `DEFAULT_DAILY_UPLOAD_CAP` / `PENDING_CHANNEL_PREFIX` / `DEFAULT_REDIRECT_URI` / `OAUTH_STATE_SALT` / `OAUTH_STATE_MAX_AGE_SECONDS` | constants | One definition each. |

### 1.1 Module layout

* `credentials/models.py` — the two tables, CHECK constraints and indexes exactly as docs/03 §4.
* `credentials/oauth.py` — pure protocol: consent URL, code exchange, refresh, channel identity.
* `credentials/http.py` — the module's only network seam (`HttpClient`), a `urllib` implementation, and the injectable fake used by tests.
* `credentials/errors.py` — typed errors (§2).

---

## 2. Errors

| Error | Parent(s) | Classified as | Raised when |
|---|---|---|---|
| `ClientNotFound` | `CredentialError` | permanent | No client matches the lookup, or a channel has no client bound. |
| `ChannelNotFound` | `CredentialError` | permanent | No channel matches the lookup, or the OAuth state names a deleted row. |
| `OAuthStateInvalid` | `CredentialError` | permanent | Missing/tampered/expired `state`. |
| `OAuthExchangeRejected` | `CredentialError` | permanent | Google refused the authorization code, or no channel could be resolved. |
| `TokenMissing` | `CredentialError` + `PermanentAuthError` | permanent | No refresh token on record: an owner must re-connect the channel. |
| `AuthRevoked` | `CredentialError` + `PermanentAuthError` | permanent | Google returned `invalid_grant`. |
| `TokenRefreshFailed` | `TransientError` | **transient** | 5xx, or no HTTP response at all (`status == 0`). |

`CredentialError` is a `PermanentError`, so the worker's `except PermanentError`
records the failure; the auth errors additionally inherit Pillar 0 §8's
`PermanentAuthError` (which hangs directly off the base) so they are never
retried. `isinstance(err, TransientError)` stays the single retry test.

---

## 3. Tests

`src/credentials/tests/test_credentials.py` — 31 tests:

* **Clients** (7): secret encrypted at rest (plaintext absent from the column),
  documented default cap, unique label/client id, cap ≥ 1, lookup + `ClientNotFound`,
  secret rotation, ordering.
* **Channels** (6): idempotent bind, blank id rejected, lookup by pk/canonical id,
  pending rows, ordering, revoke clears tokens.
* **OAuth flow** (9): consent URL contents (`access_type=offline`, `prompt=consent`,
  scopes, state), state round-trip, tampered and expired state, channel without a
  client, encrypted token storage, identity resolution for a pending row, merge into
  the known row, rejected code, transport failure.
* **Token lifecycle** (9): no refresh for a fresh token, proactive refresh inside the
  window, expired-without-refresh, `invalid_grant` recorded and not retried, 5xx
  retryable and non-destructive, health states, permanent classification.

Plus the global guards: `tests/test_module_boundaries.py`, `tests/test_module_size.py`.
No test reaches the network: `FakeHttp` implements `credentials.http.HttpClient`.

---

## 4. Out of scope

Uploading (U09 `youtube`), quota accounting (`quota_usage` belongs to `youtube`),
destination records (`pipelines`), and any UI (U16).

---

## 5. Reconciliations (decided here, recorded for U25)

1. **`scopes` storage.** docs/03 §4 declares `scopes text[]`; the Django field is
   `JSONField`, because the test harness runs SQLite (INV-10 forbids SQLite only in
   production) and `text[]` has no SQLite equivalent. On PostgreSQL this emits
   `jsonb` and stores the same list; `03_DATABASE_SCHEMA.md` §2.1 records it.
2. **Pillar 2 calls this pillar `destinations`, docs/04 §2 calls the module
   `credentials`.** `docs/04` §2/§3 is what the boundary tests enforce, so the module
   is `credentials`; the destination *record* lives in `pipelines` (docs/03 §6).
3. **`start_oauth(channel)` with an unknown channel id.** v1 needs two entry points
   (reconnect an existing row, connect a brand-new channel), so `new_channel()` covers
   the second. The signed state still names a row, so a callback can never be replayed
   against a different channel.
