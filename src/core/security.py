from __future__ import annotations

"""
YT-Replicator — Path-Safety Resolver & SSRF Domain Firewall (INV-7).

Enforces INV-7: prevents directory traversal attacks and SSRF.
Any physical media read or delete operation must strictly resolve within an
explicitly configured storage root; any outbound URL must strictly target an
allow-listed public domain and never a private, loopback, or link-local IP.
"""

import ipaddress
from pathlib import Path
from urllib.parse import urlparse

from core.exceptions import PathTraversalSecurityError


def resolve_safe_path(base_root: str | Path, relative_path: str | Path) -> Path:
    """Resolve and verify that `relative_path` strictly resides within `base_root`.

    Contract: `docs/PILLARS/07.../03_INTERFACE_CONTRACT.md` §3.3.
    Returns the fully resolved Path object.
    Raises PathTraversalSecurityError if the result would escape base_root
    (e.g. '../' segments or an absolute path pointing outside the root).
    """
    resolved_root = Path(base_root).resolve()
    candidate = Path(relative_path)
    resolved_target = (
        candidate.resolve() if candidate.is_absolute() else (resolved_root / candidate).resolve()
    )

    # relative_to verifies the prefix hierarchy safely after resolution
    try:
        resolved_target.relative_to(resolved_root)
    except ValueError:
        raise PathTraversalSecurityError(
            f"Path traversal detected: {relative_path} is outside base root {base_root}",
            details={"target_path": str(relative_path), "base_root": str(base_root)},
        )

    return resolved_target


def _is_blocked_ip(hostname: str) -> bool:
    """True when hostname is an IP literal that must never be contacted."""
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        return False  # not an IP literal; domain rules apply instead
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def is_safe_ssrf_url(url: str, allowed_domains: tuple[str, ...]) -> bool:
    """Validate that `url` strictly targets allowed public domains (INV-7).

    Contract: `docs/PILLARS/07.../03_INTERFACE_CONTRACT.md` §3.3.

    Returns True only when ALL hold:
      - the scheme is http or https,
      - a hostname is present,
      - the hostname is exactly an allow-listed domain or its subdomain
        ('youtube.com' allows 'www.youtube.com', never 'youtube.com.evil.net'),
      - the hostname is not an IP literal in a blocked range (loopback,
        private, link-local including 169.254.169.254, reserved, multicast).

    Never raises: predicate semantics (`-> bool`); callers decide whether a
    False becomes SSRFSecurityError. No DNS resolution is performed — the
    check is on the URL as written, so it is deterministic and side-effect free.
    """
    if not url or not allowed_domains:
        return False

    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        return False

    hostname = (parsed.hostname or "").lower()
    if not hostname:
        return False

    if _is_blocked_ip(hostname):
        return False

    for domain in allowed_domains:
        domain = domain.lower()
        if hostname == domain or hostname.endswith("." + domain):
            return True
    return False
