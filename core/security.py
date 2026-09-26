from __future__ import annotations

"""
YT-Replicator — Path-Safety Resolver.

Enforces INV-10 and P14: prevents directory traversal attacks.
Any physical media read or delete operation must strictly resolve within an
explicitly configured storage root.
"""

from pathlib import Path
from core.exceptions import PathTraversalSecurityError


def resolve_safe_path(target_path: str | Path, base_root: str | Path) -> Path:
    """Resolve and verify that `target_path` is strictly inside `base_root`.

    Returns the resolved Path object.
    Raises PathTraversalSecurityError if target_path attempts to escape base_root.
    """
    resolved_root = Path(base_root).resolve()
    resolved_target = (resolved_root / target_path).resolve() if not Path(target_path).is_absolute() else Path(target_path).resolve()

    # In Python 3.9+, is_relative_to verifies the prefix hierarchy safely
    try:
        resolved_target.relative_to(resolved_root)
    except ValueError:
        raise PathTraversalSecurityError(
            f"Path traversal detected: {target_path} is outside base root {base_root}",
            details={"target_path": str(target_path), "base_root": str(base_root)},
        )

    return resolved_target
