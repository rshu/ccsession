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


class TestWriteJsonIsAtomic:
    def test_a_failed_write_leaves_the_previous_content(self, tmp_path):
        """snapshot_info.json is rewritten after a failure; a half-written file would make
        the very snapshot the user is told to restore from unreadable."""
        import json
        from ccsession.utils import write_json

        target = tmp_path / "info.json"
        write_json(target, {"ok": True})

        try:
            write_json(target, {"ok": False, "bad": object()})
        except TypeError:
            pass

        assert json.loads(target.read_text(encoding="utf-8")) == {"ok": True}
        assert [p.name for p in tmp_path.iterdir()] == ["info.json"]


class TestJsonLine:
    def test_lone_surrogates_become_escapes(self):
        import json
        from ccsession.utils import json_line
        line = json_line({"display": "cut \ud83d", "é": "ü"})
        line.encode("utf-8")
        assert "\\ud83d" in line and "é" in line
        assert json.loads(line) == {"display": "cut \ud83d", "é": "ü"}


class TestCopyFileWritable:
    def test_a_read_only_source_gives_a_writable_copy(self, tmp_path):
        """copy2 carries the read-only attribute (Windows) or the uchg flag (macOS) onto
        the copy, and the restore could then never delete it."""
        import os
        import stat
        from ccsession.utils import copy_file_writable
        src = tmp_path / "src.md"
        src.write_text("x", encoding="utf-8")
        os.chmod(src, stat.S_IREAD)
        try:
            copy_file_writable(src, tmp_path / "dst.md")
            assert (tmp_path / "dst.md").read_text(encoding="utf-8") == "x"
            assert os.stat(tmp_path / "dst.md").st_mode & stat.S_IWUSR
            (tmp_path / "dst.md").unlink()
        finally:
            os.chmod(src, stat.S_IREAD | stat.S_IWRITE)


class TestForceRemove:
    def test_read_only_files_are_removed(self, tmp_path):
        import os
        import stat
        from ccsession.utils import force_rmtree
        tree = tmp_path / "tree"
        (tree / "sub").mkdir(parents=True)
        (tree / "sub" / "ro.txt").write_text("x", encoding="utf-8")
        os.chmod(tree / "sub" / "ro.txt", stat.S_IREAD)
        force_rmtree(tree)
        assert not tree.exists()
