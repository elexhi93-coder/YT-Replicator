from __future__ import annotations

"""
YT-Replicator — Tenancy models (docs/03 §3, D11).

Tenant-shaped, single-tenant operated: `workspace` and `workspace_member`
exist so that adding tenants later is a feature switch, not a migration.
Table names match `03_DATABASE_SCHEMA.md` exactly (`workspace`,
`workspace_member`); roles are the coarse v1 trio (`owner`/`operator`/
`viewer`) with the documented CHECK constraint.
"""

from django.conf import settings
from django.db import models


class Workspace(models.Model):
    """Tenant root. One row in v1 (the default workspace)."""

    name = models.TextField()
    slug = models.TextField(unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "workspace"

    def __str__(self) -> str:
        return f"{self.name} ({self.slug})"


class WorkspaceMember(models.Model):
    """User ↔ workspace with a coarse role. `unique(workspace, user)` (docs/03 §3)."""

    ROLE_OWNER = "owner"
    ROLE_OPERATOR = "operator"
    ROLE_VIEWER = "viewer"
    ROLE_CHOICES = [
        (ROLE_OWNER, "Owner"),
        (ROLE_OPERATOR, "Operator"),
        (ROLE_VIEWER, "Viewer"),
    ]

    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name="memberships"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships"
    )
    role = models.TextField(choices=ROLE_CHOICES, default=ROLE_OPERATOR)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "workspace_member"
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "user"], name="uq_workspace_user"
            ),
            models.CheckConstraint(
                condition=models.Q(role__in=("owner", "operator", "viewer")),
                name="ck_member_role",
            ),
        ]
        indexes = [
            models.Index(fields=["user"], name="workspace_member_user_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.user_id}·{self.workspace_id}={self.role}"