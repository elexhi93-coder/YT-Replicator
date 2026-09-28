from __future__ import annotations

"""
credentials.models — Google clients and authorized channels (docs/03 §4).

Two tables, both tenant-scoped:

* `google_client` — one row per Google Cloud project. The client secret is
  stored **encrypted** (`core.api.encrypt`, INV-1); plaintext never touches
  this table or a log line (defects D-11, D-22).
* `authorized_channel` — one row per destination YouTube channel, bound to the
  client that authorized it. `ON DELETE SET NULL` on the client is deliberate:
  removing a client must not destroy the channel or its tokens, it must leave a
  visibly fixable "needs a client" state.

Cross-module note (docs/04 §3): the `workspace` FK is declared as a **string**
reference (`"accounts.Workspace"`) so no Python import of a sibling module is
needed — Django resolves it through the app registry. All cross-module
*behaviour* still goes through `accounts.api` (INV-12).
"""

from django.db import models


class GoogleClient(models.Model):
    """A Google Cloud project whose OAuth client authorizes channels."""

    workspace = models.ForeignKey(
        "accounts.Workspace",
        on_delete=models.CASCADE,
        related_name="google_clients",
    )
    label = models.TextField()
    client_id = models.TextField()
    #: AES-256-GCM envelope (core.api.encrypt) as bytes — `bytea` in docs/03 §4.
    client_secret_enc = models.BinaryField(default=b"")
    daily_upload_cap = models.IntegerField(default=6)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "google_client"
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "client_id"], name="uq_google_client_client_id"
            ),
            models.UniqueConstraint(
                fields=["workspace", "label"], name="uq_google_client_label"
            ),
            models.CheckConstraint(
                condition=models.Q(daily_upload_cap__gt=0),
                name="ck_google_client_cap",
            ),
        ]
        indexes = [
            models.Index(
                fields=["workspace", "is_active"], name="google_client_active_idx"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.label} ({self.client_id})"


class AuthorizedChannel(models.Model):
    """A destination channel with its OAuth tokens (encrypted at rest)."""

    TOKEN_MISSING = "missing"
    TOKEN_VALID = "valid"
    TOKEN_EXPIRING = "expiring"
    TOKEN_INVALID = "invalid"
    TOKEN_REVOKED = "revoked"
    TOKEN_STATES = [
        (TOKEN_MISSING, "Missing"),
        (TOKEN_VALID, "Valid"),
        (TOKEN_EXPIRING, "Expiring"),
        (TOKEN_INVALID, "Invalid"),
        (TOKEN_REVOKED, "Revoked"),
    ]
    #: Doc alias — the state machine in Pillar 2 §2.1.
    TokenHealthStatus = TOKEN_STATES

    workspace = models.ForeignKey(
        "accounts.Workspace",
        on_delete=models.CASCADE,
        related_name="authorized_channels",
    )
    google_client = models.ForeignKey(
        GoogleClient,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="channels",
    )
    channel_id = models.TextField()  # 'UC…'
    title = models.TextField(default="")
    access_token_enc = models.BinaryField(null=True, blank=True, default=None)
    refresh_token_enc = models.BinaryField(null=True, blank=True, default=None)
    token_expires_at = models.DateTimeField(null=True, blank=True)
    #: docs/03 §4 declares `text[]`; stored as JSON (jsonb on PostgreSQL) because
    #: the test harness runs SQLite — see CONTRACT.md §5 reconciliation 1.
    scopes = models.JSONField(default=list, blank=True)
    token_state = models.TextField(choices=TOKEN_STATES, default=TOKEN_MISSING)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "authorized_channel"
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "channel_id"], name="uq_channel_workspace_channel"
            ),
            models.CheckConstraint(
                condition=models.Q(
                    token_state__in=[
                        "missing",
                        "valid",
                        "expiring",
                        "invalid",
                        "revoked",
                    ]
                ),
                name="ck_channel_token_state",
            ),
        ]
        indexes = [
            models.Index(
                fields=["workspace", "token_state"],
                name="authorized_channel_state_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.title or self.channel_id} [{self.token_state}]"
