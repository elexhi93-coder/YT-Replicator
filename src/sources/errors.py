from __future__ import annotations

"""
sources.errors — typed errors for the sources module (docs/04 §5).

Classification follows the project rule: `TransientError` is retried by `jobs`
with backoff, everything else fails the job and is shown to the operator.
"""

from core.api import (
    ItemUnavailable,
    PermanentError,
    RateLimitExceeded,
    SourceUrlRejected,
    TransientError,
)


class SourceError(PermanentError):
    """Base for source/catalog failures the operator must resolve."""

    default_code = "source_error"


class SourceUrlInvalid(SourceError, SourceUrlRejected):
    """The operator's input is not a usable source URL (shape or SSRF guard).

    Folds Pillar 0 §8's `SourceUrlRejected` into this module's vocabulary so one
    `except SourceError` is enough in a view.
    """

    default_code = "source_url_invalid"


class SourceUnresolvable(SourceError):
    """The URL is well-formed but no channel/playlist exists behind it."""

    default_code = "source_unresolvable"


class SourceNotFound(SourceError):
    """No `source` row matches the lookup."""

    default_code = "source_not_found"


class CatalogVideoNotFound(SourceError):
    """No `catalog_video` row matches the lookup."""

    default_code = "catalog_video_not_found"


class ItemGone(SourceError, ItemUnavailable):
    """The item was deleted, made private, or geo-blocked at the source."""

    default_code = "item_gone"


class HydrationRateLimited(RateLimitExceeded):
    """YouTube throttled a hydration request: cool off, then continue (INV-7).

    Only `RateLimitExceeded` is named as a base. It is *already* a
    `TransientError` (core/exceptions.py §8), so listing both would be an
    invalid MRO and would say nothing extra.
    """

    default_code = "hydration_rate_limited"


class ProviderUnavailable(TransientError):
    """The extraction tool is missing or refused to run."""

    default_code = "provider_unavailable"
