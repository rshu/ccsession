import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ccsession.utils import utc_now_iso, parse_iso_timestamp


class TestUtcNowIso:
    """Tests for utc_now_iso()."""

    def test_returns_string(self):
        result = utc_now_iso()
        assert isinstance(result, str)

    def test_ends_with_z(self):
        result = utc_now_iso()
        assert result.endswith("Z")

    def test_does_not_contain_plus_offset(self):
        result = utc_now_iso()
        assert "+00:00" not in result

    def test_is_parseable_iso_format(self):
        result = utc_now_iso()
        parsed = datetime.fromisoformat(result.replace("Z", "+00:00"))
        assert parsed.tzinfo is not None


class TestParseIsoTimestamp:
    """Tests for parse_iso_timestamp()."""

    def test_parse_z_suffix(self):
        result = parse_iso_timestamp("2024-01-15T10:30:00Z")
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15
        assert result.hour == 10
        assert result.minute == 30
        assert result.tzinfo is not None

    def test_parse_offset_suffix(self):
        result = parse_iso_timestamp("2024-01-15T10:30:00+00:00")
        assert result.year == 2024
        assert result.tzinfo is not None

    def test_roundtrip(self):
        iso_str = utc_now_iso()
        parsed = parse_iso_timestamp(iso_str)
        assert parsed.tzinfo is not None
        assert parsed.tzinfo.utcoffset(None) == timezone.utc.utcoffset(None)

    def test_returns_timezone_aware(self):
        result = parse_iso_timestamp("2024-06-01T12:00:00Z")
        assert result.tzinfo is not None
