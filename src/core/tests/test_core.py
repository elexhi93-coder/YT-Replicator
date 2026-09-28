import pytest
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from core.api import (
    PACIFIC_TZ,
    AuthExpiredError,
    BotChallengeRequiredError,
    PathTraversalSecurityError,
    PermanentError,
    QuotaExhaustedError,
    ReplicatorError,
    SSRFSecurityError,
    TransientError,
    extract_video_id,
    get_logger,
    next_quota_reset_utc,
    now_pacific,
    now_utc,
    quota_day_string,
    resolve_safe_path,
    validate_youtube_url,
    MasterKeyMissingError,
    SecretDecryptionError,
    decrypt,
    encrypt,
    get_pacific_time,
    get_pacific_date_string,
    quota_day,
    is_safe_ssrf_url,
    NetworkError,
    RateLimitExceeded,
    SourceUrlRejected,
    ItemUnavailable,
    TermsViolation,
    PermanentAuthError,
    QuotaExhausted,
    Settings,
    get_settings,
    reset_settings_cache,
    APP_SETTING_DEFAULTS,
    PassthroughTransformer,
    TransformInput,
    PROVENANCE_MARKER_REGEX,
    format_provenance_marker,
    SourceItem,
)


class TestClock:
    def test_now_utc_has_utc_tzinfo(self):
        dt = now_utc()
        assert dt.tzinfo == timezone.utc

    def test_now_pacific_has_pacific_tzinfo(self):
        dt = now_pacific()
        assert str(dt.tzinfo) == "America/Los_Angeles"

    def test_next_quota_reset_utc_during_standard_time(self):
        # 2026-01-15 12:00:00 UTC = 2026-01-15 04:00:00 PST (UTC-8)
        # Next midnight Pacific is 2026-01-16 00:00:00 PST = 2026-01-16 08:00:00 UTC
        ref = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        reset = next_quota_reset_utc(ref)
        assert reset == datetime(2026, 1, 16, 8, 0, 0, tzinfo=timezone.utc)

    def test_next_quota_reset_utc_during_daylight_time(self):
        # 2026-07-15 12:00:00 UTC = 2026-07-15 05:00:00 PDT (UTC-7)
        # Next midnight Pacific is 2026-07-16 00:00:00 PDT = 2026-07-16 07:00:00 UTC
        ref = datetime(2026, 7, 15, 12, 0, 0, tzinfo=timezone.utc)
        reset = next_quota_reset_utc(ref)
        assert reset == datetime(2026, 7, 16, 7, 0, 0, tzinfo=timezone.utc)

    def test_quota_day_string(self):
        # 2026-07-15 03:00:00 UTC is 2026-07-14 20:00:00 PDT (Still July 14th in LA)
        ref = datetime(2026, 7, 15, 3, 0, 0, tzinfo=timezone.utc)
        assert quota_day_string(ref) == "2026-07-14"

        # 2026-07-15 08:00:00 UTC is 2026-07-15 01:00:00 PDT (July 15th in LA)
        ref2 = datetime(2026, 7, 15, 8, 0, 0, tzinfo=timezone.utc)
        assert quota_day_string(ref2) == "2026-07-15"

    def test_quota_day_returns_pacific_date(self):
        # Naive datetime is UTC; 03:00 UTC is still the previous day in LA (PDT).
        assert quota_day(datetime(2026, 7, 15, 3, 0, 0)) == datetime(2026, 7, 14).date()
        assert quota_day(datetime(2026, 7, 15, 12, 0, 0)) == datetime(2026, 7, 15).date()

    # --- DST transitions (INV-2's whole point; legacy defect D-03) ----------

    def test_spring_forward_transition_reset_is_0700_utc(self):
        # 2026-03-08 02:00 PST -> 03:00 PDT (DST starts). The quota day for
        # 2026-03-08 ends at midnight entering 2026-03-09, which is PDT (UTC-7):
        # 2026-03-09 00:00 PDT = 2026-03-09 07:00 UTC.
        ref = datetime(2026, 3, 8, 20, 0, 0, tzinfo=timezone.utc)  # 13:00 PDT
        reset = next_quota_reset_utc(ref)
        assert reset == datetime(2026, 3, 9, 7, 0, 0, tzinfo=timezone.utc)

    def test_fall_back_transition_reset_is_0800_utc(self):
        # 2026-11-01 02:00 PDT -> 01:00 PST (DST ends). The quota day for
        # 2026-11-02 starts at midnight PST (UTC-8): 2026-11-02 08:00 UTC.
        ref = datetime(2026, 11, 1, 20, 0, 0, tzinfo=timezone.utc)  # 12:00 PST
        reset = next_quota_reset_utc(ref)
        assert reset == datetime(2026, 11, 2, 8, 0, 0, tzinfo=timezone.utc)

    def test_quota_day_rollover_differs_between_pst_and_pdt(self):
        # 07:30 UTC = 00:30 PDT (same day) in summer, but 23:30 PST the
        # previous day in winter — the PST/PDT split is the D-03 defect.
        assert quota_day(datetime(2026, 7, 15, 7, 30, 0)) == datetime(2026, 7, 15).date()
        assert quota_day(datetime(2026, 1, 15, 7, 30, 0)) == datetime(2026, 1, 14).date()

    def test_get_pacific_time_dto_is_consistent(self):
        snapshot = get_pacific_time()
        assert snapshot.pacific_date == snapshot.pacific_now.date()
        assert snapshot.utc_now.tzinfo == timezone.utc
        # next midnight must be in the future and equal the reset function
        assert snapshot.next_midnight_pacific_utc > snapshot.utc_now
        assert snapshot.next_midnight_pacific_utc == next_quota_reset_utc(snapshot.utc_now)

    def test_get_pacific_date_string_format(self):
        value = get_pacific_date_string()
        assert len(value) == 10 and value[4] == "-" and value[7] == "-"
        assert value == get_pacific_time().pacific_date.strftime("%Y-%m-%d")


class TestSecurity:
    def test_resolve_safe_path_valid(self, tmp_path):
        subfile = tmp_path / "downloads" / "video.mp4"
        subfile.parent.mkdir(parents=True, exist_ok=True)
        subfile.touch()

        resolved = resolve_safe_path(tmp_path, "downloads/video.mp4")
        assert resolved == subfile.resolve()

    def test_resolve_safe_path_traversal_blocked(self, tmp_path):
        with pytest.raises(PathTraversalSecurityError):
            resolve_safe_path(tmp_path, "../../etc/passwd")

    def test_resolve_safe_path_absolute_escape_blocked(self, tmp_path):
        outside = Path.cwd() / "elsewhere"
        with pytest.raises(PathTraversalSecurityError):
            resolve_safe_path(tmp_path, outside)

    def test_is_safe_ssrf_url_allows_youtube_domains(self):
        allowed = ("youtube.com", "youtu.be", "youtube-nocookie.com")
        assert is_safe_ssrf_url("https://www.youtube.com/watch?v=x", allowed)
        assert is_safe_ssrf_url("https://youtu.be/x", allowed)
        assert is_safe_ssrf_url("https://youtube-nocookie.com/embed/x", allowed)

    def test_is_safe_ssrf_url_blocks_other_hosts(self):
        allowed = ("youtube.com", "youtu.be")
        assert not is_safe_ssrf_url("https://evil.com/video", allowed)
        assert not is_safe_ssrf_url("https://youtube.com.evil.net/", allowed)
        assert not is_safe_ssrf_url("https://notyoutube.com/", allowed)

    def test_is_safe_ssrf_url_blocks_private_and_metadata_ips(self):
        allowed = ("youtube.com",)
        assert not is_safe_ssrf_url("http://169.254.169.254/latest/meta-data", allowed)
        assert not is_safe_ssrf_url("http://127.0.0.1/admin", allowed)
        assert not is_safe_ssrf_url("http://192.168.1.1/admin", allowed)
        assert not is_safe_ssrf_url("http://10.0.0.5/", allowed)
        assert not is_safe_ssrf_url("http://[::1]/", allowed)

    def test_is_safe_ssrf_url_blocks_bad_scheme_or_empty(self):
        assert not is_safe_ssrf_url("ftp://youtube.com/", ("youtube.com",))
        assert not is_safe_ssrf_url("", ("youtube.com",))
        assert not is_safe_ssrf_url("https://www.youtube.com/", ())


class TestValidators:
    def test_validate_youtube_url_valid(self):
        valid_urls = [
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtu.be/dQw4w9WgXcQ",
            "https://m.youtube.com/watch?v=dQw4w9WgXcQ",
            "www.youtube.com/watch?v=dQw4w9WgXcQ",
        ]
        for url in valid_urls:
            assert validate_youtube_url(url).startswith("http")

    def test_validate_youtube_url_ssrf_blocked(self):
        invalid_urls = [
            "https://evil.com/video",
            "http://169.254.169.254/latest/meta-data",
            "http://192.168.1.1/admin",
            "https://notyoutube.com",
            "",
        ]
        for url in invalid_urls:
            with pytest.raises(SSRFSecurityError):
                validate_youtube_url(url)

    def test_extract_video_id(self):
        assert extract_video_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"
        assert extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
        assert extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
        assert extract_video_id("https://www.youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
        assert extract_video_id("invalid-id") is None


class TestExceptions:
    def test_hierarchy(self):
        assert issubclass(TransientError, ReplicatorError)
        assert issubclass(PermanentError, ReplicatorError)
        assert issubclass(QuotaExhaustedError, TransientError)
        assert issubclass(AuthExpiredError, PermanentError)
        assert issubclass(BotChallengeRequiredError, TransientError)
        assert issubclass(PathTraversalSecurityError, PermanentError)
        assert issubclass(SSRFSecurityError, PermanentError)

    def test_port_boundary_error_hierarchy(self):
        # Pillar 0 §8: everything crossing a port inherits from PillarError.
        for cls in (
            NetworkError,
            RateLimitExceeded,
            QuotaExhaustedError,
            SourceUrlRejected,
            ItemUnavailable,
            TermsViolation,
            PermanentAuthError,
        ):
            assert issubclass(cls, ReplicatorError)
        # Retryability split (docs/07 U08): transient vs not.
        assert issubclass(NetworkError, TransientError)
        assert issubclass(RateLimitExceeded, TransientError)
        assert not issubclass(SourceUrlRejected, TransientError)
        assert not issubclass(ItemUnavailable, TransientError)
        assert not issubclass(PermanentAuthError, TransientError)
        # QuotaExhausted aliases the transient class (jobs reschedules at reset).
        assert QuotaExhausted is QuotaExhaustedError

    def test_rate_limit_carries_retry_after(self):
        err = RateLimitExceeded(retry_after_sec=120)
        assert err.retry_after_sec == 120
        assert err.details["retry_after_sec"] == 120


class TestSettings:
    def test_defaults_documented(self, monkeypatch):
        monkeypatch.delenv("MEDIA_ROOT", raising=False)
        monkeypatch.delenv("DISK_FREE_FLOOR_GB", raising=False)
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        s = Settings.from_env({})
        assert str(s.media_root) == "media"
        assert s.disk_free_floor_gb == 10
        assert s.log_level == "INFO"

    def test_env_overrides(self):
        s = Settings.from_env(
            {"MEDIA_ROOT": "/data/media", "DISK_FREE_FLOOR_GB": "25", "LOG_LEVEL": "debug"}
        )
        # Path is OS-specific; compare as_posix so this passes on Windows too.
        assert s.media_root.as_posix() == "/data/media"
        assert s.disk_free_floor_gb == 25
        assert s.log_level == "DEBUG"

    def test_invalid_int_raises_helpful_error(self):
        with pytest.raises(ValueError, match="DISK_FREE_FLOOR_GB"):
            Settings.from_env({"DISK_FREE_FLOOR_GB": "lots"})

    def test_get_settings_cached_and_resettable(self, monkeypatch):
        monkeypatch.setenv("DISK_FREE_FLOOR_GB", "42")
        reset_settings_cache()
        try:
            assert get_settings().disk_free_floor_gb == 42
            monkeypatch.setenv("DISK_FREE_FLOOR_GB", "7")
            assert get_settings().disk_free_floor_gb == 42  # still cached
            reset_settings_cache()
            assert get_settings().disk_free_floor_gb == 7
        finally:
            reset_settings_cache()

    def test_app_setting_defaults_match_docs_03_s11(self):
        assert APP_SETTING_DEFAULTS == {
            "monitor_poll_minutes": 15,
            "reconcile_hours": 6,
            "retention_backstop_days": 7,
            "hydrate_interval_seconds": 1,
            "hydrate_abort_on_429_minutes": 5,
            "claim_timeout_minutes": 15,
            "upload_chunk_bytes": 1048576,
            "quota_timezone": "America/Los_Angeles",
        }


class TestPorts:
    def test_dto_is_frozen(self):
        item = SourceItem(
            video_id="dQw4w9WgXcQ",
            title="t",
            published_at=None,
            duration_sec=1,
            thumbnail_url=None,
            live_status="not_live",
            availability="public",
        )
        with pytest.raises(Exception):
            item.title = "changed"  # frozen dataclass (R1)

    def test_passthrough_transformer_never_raises(self):
        result = PassthroughTransformer().transform(
            TransformInput(
                source_title="Title",
                source_description="Desc",
                source_tags=("a", "b"),
                target_language=None,
                template_name=None,
            )
        )
        assert result.applied is False
        assert result.fallback_reason == "transformer_disabled"
        assert result.title == "Title"
        assert result.description == "Desc"
        assert result.tags == ("a", "b")

    def test_provenance_marker_format_and_regex(self):
        marker = format_provenance_marker("dQw4w9WgXcQ", 42)
        assert marker == "[ref:dQw4w9WgXcQ:42]"
        m = PROVENANCE_MARKER_REGEX.search(f"Some description\n{marker}")
        assert m is not None
        assert m.group("source_video_id") == "dQw4w9WgXcQ"
        assert m.group("delivery_id") == "42"
        # Not anchored at end -> no match (markers are append-only)
        assert PROVENANCE_MARKER_REGEX.search(f"{marker}\ntrailing") is None


class TestCrypto:
    def test_encrypt_decrypt_roundtrip(self, monkeypatch):
        # 32-byte hex master key
        key_hex = "00112233445566778899aabbccddeeff00112233445566778899aabbccddeeff"
        monkeypatch.setenv("PLATFORM_MASTER_KEY", key_hex)

        token = "1//0gEXAMPLE_REFRESH_TOKEN_do_not_leak"
        envelope = encrypt(token)

        # Ciphertext must never contain the plaintext
        assert token not in envelope
        # Envelope must be deterministic in length properties but non-deterministic content
        assert isinstance(envelope, str)
        assert encrypt(token) != envelope  # random IV each time

        assert decrypt(envelope) == token

    def test_encrypt_decrypt_with_explicit_key(self):
        key = bytes(range(32))
        envelope = encrypt("secret-value", key=key)
        assert decrypt(envelope, key=key) == "secret-value"

    def test_wrong_key_fails_decryption(self):
        key_a = bytes(range(32))
        key_b = bytes(range(1, 33))
        envelope = encrypt("secret-value", key=key_a)

        with pytest.raises(SecretDecryptionError):
            decrypt(envelope, key=key_b)

    def test_tampered_envelope_fails_decryption(self):
        import base64

        key = bytes(range(32))
        envelope = encrypt("secret-value", key=key)

        raw = bytearray(base64.urlsafe_b64decode(envelope.encode("utf-8")))
        raw[-1] ^= 0xFF  # flip bits in the authentication tag
        tampered = base64.urlsafe_b64encode(bytes(raw)).decode("utf-8")

        with pytest.raises(SecretDecryptionError):
            decrypt(tampered, key=key)

    def test_corrupted_base64_fails(self):
        key = bytes(range(32))
        with pytest.raises(SecretDecryptionError):
            decrypt("not-valid-base64!!!", key=key)

    def test_missing_master_key_raises(self, monkeypatch):
        monkeypatch.delenv("PLATFORM_MASTER_KEY", raising=False)
        with pytest.raises(MasterKeyMissingError):
            encrypt("token")

    def test_invalid_master_key_length_raises(self, monkeypatch):
        monkeypatch.setenv("PLATFORM_MASTER_KEY", "too-short")
        with pytest.raises(MasterKeyMissingError):
            encrypt("token")

    def test_plaintext_type_enforced(self):
        key = bytes(range(32))
        with pytest.raises(TypeError):
            encrypt(b"bytes-not-str", key=key)


class TestLogging:
    def test_structured_logger(self):
        logger = get_logger("test", test_id="123")
        assert logger is not None
