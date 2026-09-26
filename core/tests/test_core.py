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


class TestSecurity:
    def test_resolve_safe_path_valid(self, tmp_path):
        subfile = tmp_path / "downloads" / "video.mp4"
        subfile.parent.mkdir(parents=True, exist_ok=True)
        subfile.touch()

        resolved = resolve_safe_path("downloads/video.mp4", tmp_path)
        assert resolved == subfile.resolve()

    def test_resolve_safe_path_traversal_blocked(self, tmp_path):
        with pytest.raises(PathTraversalSecurityError):
            resolve_safe_path("../../etc/passwd", tmp_path)


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


class TestLogging:
    def test_structured_logger(self):
        logger = get_logger("test", test_id="123")
        assert logger is not None
