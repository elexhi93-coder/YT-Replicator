from __future__ import annotations

"""
core.api — Public Interface Contract for the Core Module.

All cross-module communication touching the core module must import ONLY from core.api.
"""

from core.clock import (
    PACIFIC_TZ,
    PacificTimeDTO,
    get_pacific_date_string,
    get_pacific_time,
    next_quota_reset_utc,
    now_pacific,
    now_utc,
    quota_day,
    quota_day_string,
)
from core.exceptions import (
    AuthExpiredError,
    BotChallengeRequiredError,
    ItemUnavailable,
    MasterKeyMissingError,
    NetworkError,
    PathTraversalSecurityError,
    PermanentAuthError,
    PermanentError,
    PillarError,
    QuotaExhausted,
    QuotaExhaustedError,
    RateLimitExceeded,
    ReplicatorError,
    ResourceTemporarilyUnavailable,
    SSRFSecurityError,
    SecretDecryptionError,
    SourceUrlRejected,
    TermsViolation,
    TransientError,
)
from core.logging import StructuredLoggerAdapter, get_logger
from core.registry import (
    PortNotRegistered,
    get_destination_platform,
    get_metadata_transformer,
    get_retention_oracle,
    get_source_provider,
    register_destination_platform,
    register_metadata_transformer,
    register_retention_oracle,
    register_source_provider,
    reset_port_registry,
)
from core.security import is_safe_ssrf_url, resolve_safe_path
from core.crypto import decrypt, encrypt
from core.settings import APP_SETTING_DEFAULTS, Settings, get_settings, reset_settings_cache
from core.validators import extract_video_id, validate_youtube_url

from core.ports import (
    PROVENANCE_MARKER_REGEX,
    AuthState,
    ChannelRef,
    DestinationPlatform,
    DestinationVideoDTO,
    InventoryBatch,
    MaterializedMedia,
    MaterializeRequest,
    MetadataTransformer,
    PassthroughTransformer,
    ProgressCallback,
    ResolvedSource,
    RetentionFacts,
    RetentionOracle,
    SourceItem,
    SourceItemDetail,
    SourceProvider,
    SourceRef,
    TransformInput,
    TransformResult,
    UploadOutcome,
    UploadRequest,
    VideoRef,
    format_provenance_marker,
)

__all__ = [
    # Exceptions
    "ReplicatorError",
    "PillarError",
    "TransientError",
    "PermanentError",
    "QuotaExhaustedError",
    "QuotaExhausted",
    "AuthExpiredError",
    "BotChallengeRequiredError",
    "PathTraversalSecurityError",
    "SSRFSecurityError",
    "MasterKeyMissingError",
    "SecretDecryptionError",
    "NetworkError",
    "RateLimitExceeded",
    "ResourceTemporarilyUnavailable",
    "SourceUrlRejected",
    "ItemUnavailable",
    "TermsViolation",
    "PermanentAuthError",
    # Crypto (AES-256-GCM, INV-1 / ADJ-P2-01)
    "encrypt",
    "decrypt",
    # Clock (INV-2)
    "PACIFIC_TZ",
    "PacificTimeDTO",
    "now_utc",
    "now_pacific",
    "next_quota_reset_utc",
    "quota_day",
    "quota_day_string",
    "get_pacific_time",
    "get_pacific_date_string",
    # Security (INV-7)
    "resolve_safe_path",
    "is_safe_ssrf_url",
    # Settings
    "APP_SETTING_DEFAULTS",
    "Settings",
    "get_settings",
    "reset_settings_cache",
    # URL & Format Validation
    "validate_youtube_url",
    "extract_video_id",
    # Logging
    "get_logger",
    "StructuredLoggerAdapter",
    # Port registry (Pillar 0 inversion — docs/04 §6 row 2026-09-28)
    "PortNotRegistered",
    "register_source_provider",
    "get_source_provider",
    "register_destination_platform",
    "get_destination_platform",
    "register_metadata_transformer",
    "get_metadata_transformer",
    "register_retention_oracle",
    "get_retention_oracle",
    "reset_port_registry",
    # Ports & contract types (Pillar 0)
    "SourceProvider",
    "DestinationPlatform",
    "MetadataTransformer",
    "PassthroughTransformer",
    "RetentionOracle",
    "RetentionFacts",
    "ProgressCallback",
    "ResolvedSource",
    "SourceItem",
    "SourceItemDetail",
    "MaterializeRequest",
    "MaterializedMedia",
    "AuthState",
    "InventoryBatch",
    "DestinationVideoDTO",
    "UploadRequest",
    "UploadOutcome",
    "TransformInput",
    "TransformResult",
    "SourceRef",
    "ChannelRef",
    "VideoRef",
    "PROVENANCE_MARKER_REGEX",
    "format_provenance_marker",
]
