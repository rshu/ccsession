import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ccsession.paths import (
    get_claude_dir,
    get_projects_root,
    get_history_file,
    get_session_dir,
    get_normalized_project_dir,
    get_project_dir_name,
    get_projects_dir,
    get_file_history_dir,
    get_session_env_dir,
    get_import_storage_dir,
    get_snapshot_dir,
)


class TestGetNormalizedProjectDir:
    """Claude Code 2.1.287 names the project directory with
    ``cwd.replace(/[^a-zA-Z0-9]/g, "-")`` (per UTF-16 code unit, no ``u`` flag) and,
    past 200 characters, truncates and appends ``-<base36 of a Java-style string hash>``.
    Expected values below were produced by running that JavaScript in Node."""

    def test_unix_path_basic(self):
        assert get_normalized_project_dir("/home/user/project") == "-home-user-project"

    def test_unix_path_with_dots(self):
        assert get_normalized_project_dir("/mnt/c/project.git") == "-mnt-c-project-git"

    def test_unix_path_with_underscores(self):
        assert get_normalized_project_dir("/mnt/c/my_project") == "-mnt-c-my-project"

    def test_windows_path(self):
        assert get_normalized_project_dir("C:\\Users\\user\\project") == "C--Users-user-project"

    def test_windows_path_no_leading_dash(self):
        assert not get_normalized_project_dir("C:\\project").startswith("-")

    def test_unc_path_keeps_both_leading_dashes(self):
        assert get_normalized_project_dir("\\\\server\\share\\p") == "--server-share-p"

    def test_unix_path_has_leading_dash(self):
        assert get_normalized_project_dir("/home/user/project").startswith("-")

    def test_accepts_path_object(self):
        assert get_normalized_project_dir(Path("/home/user/project")) == "-home-user-project"

    def test_space_becomes_a_dash(self):
        assert get_normalized_project_dir("/Users/me/My Project") == "-Users-me-My-Project"

    def test_windows_path_with_space(self):
        assert get_normalized_project_dir("C:\\Users\\John Smith\\proj") == "C--Users-John-Smith-proj"

    def test_every_punctuation_character_becomes_a_dash(self):
        assert get_normalized_project_dir("/Users/me/p~@+#()'q") == "-Users-me-p-------q"

    def test_bmp_non_ascii_character_becomes_one_dash(self):
        assert get_normalized_project_dir("/Users/mé/p") == "-Users-m--p"

    def test_astral_character_becomes_two_dashes(self):
        """JavaScript regexes without the ``u`` flag see a surrogate pair as two code units."""
        assert get_normalized_project_dir("/Users/me/🚀/p") == "-Users-me----p"

    def test_long_path_is_truncated_with_a_hash_suffix(self):
        long_path = "/Users/me/" + "a" * 195 + "/proj"
        assert len(long_path) == 210
        result = get_normalized_project_dir(long_path)
        assert result == "-Users-me-" + "a" * 190 + "-u1y0ac"
        assert len(result) == 200 + 1 + 6

    def test_path_of_exactly_200_characters_is_not_hashed(self):
        path = "/" + "b" * 199
        assert get_normalized_project_dir(path) == "-" + "b" * 199

    def test_hash_is_computed_over_utf16_code_units(self):
        long_path = "/Users/me/🚀/" + "c" * 200
        result = get_normalized_project_dir(long_path)
        assert result.endswith("-og8s17")
        assert result.startswith("-Users-me----" + "c" * 187)


class TestProjectDirNameOverride:
    """``CLAUDE_CODE_PROJECT_DIR_NAME`` replaces the computed name, but Claude Code only
    reads it when ``CLAUDE_CONFIG_DIR`` is set, and only when it is a safe directory name."""

    def test_override_applies_with_config_dir(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
        monkeypatch.setenv("CLAUDE_CODE_PROJECT_DIR_NAME", "my_team-proj")
        assert get_project_dir_name("/home/user/project") == "my_team-proj"
        assert get_projects_dir("/home/user/project") == tmp_path / "cfg" / "projects" / "my_team-proj"

    def test_override_is_ignored_without_config_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setenv("CLAUDE_CODE_PROJECT_DIR_NAME", "my_team-proj")
        assert get_project_dir_name("/home/user/project") == "-home-user-project"

    @pytest.mark.parametrize("bad", ["", "has space", "a/b", "x" * 65, "CON", "lpt1", "Nul"])
    def test_invalid_override_values_are_ignored(self, tmp_path, monkeypatch, bad):
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
        monkeypatch.setenv("CLAUDE_CODE_PROJECT_DIR_NAME", bad)
        assert get_project_dir_name("/home/user/project") == "-home-user-project"

    def test_normalized_name_never_consults_the_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
        monkeypatch.setenv("CLAUDE_CODE_PROJECT_DIR_NAME", "override")
        assert get_normalized_project_dir("/home/user/project") == "-home-user-project"


class TestDirectoryHelpers:
    """Tests for directory path helpers."""

    def test_get_projects_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        expected_name = get_normalized_project_dir("/home/user/project")  # platform-specific spelling
        assert get_projects_dir("/home/user/project") == tmp_path / ".claude" / "projects" / expected_name

    def test_get_file_history_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        result = get_file_history_dir("abc-123")
        assert result == tmp_path / ".claude" / "file-history" / "abc-123"

    def test_get_session_env_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        result = get_session_env_dir("abc-123")
        assert result == tmp_path / ".claude" / "session-env" / "abc-123"

    def test_get_import_storage_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        result = get_import_storage_dir()
        assert result == tmp_path / ".claude-session-imports"

    def test_get_snapshot_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        result = get_snapshot_dir()
        assert result == tmp_path / ".claude-session-imports" / "pre-import-snapshot"


class TestClaudeConfigDir:
    def test_defaults_to_dot_claude_under_home(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        assert get_claude_dir() == tmp_path / ".claude"

    def test_honours_claude_config_dir(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
        assert get_claude_dir() == tmp_path / "cfg"

    def test_empty_env_value_falls_back_to_home(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", "")
        assert get_claude_dir() == tmp_path / ".claude"

    def test_tilde_in_env_value_is_expanded(self, tmp_path, monkeypatch):
        # expanduser() reads $HOME on POSIX and USERPROFILE on Windows, not Path.home()
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", "~/alt-claude")
        assert get_claude_dir() == tmp_path / "alt-claude"

    def test_every_helper_derives_from_config_dir(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
        name = get_normalized_project_dir("/home/user/project")
        assert get_projects_root() == tmp_path / "cfg" / "projects"
        assert get_projects_dir("/home/user/project") == tmp_path / "cfg" / "projects" / name
        assert get_session_dir("/home/user/project", "abc") == tmp_path / "cfg" / "projects" / name / "abc"
        assert get_file_history_dir("abc") == tmp_path / "cfg" / "file-history" / "abc"
        assert get_session_env_dir("abc") == tmp_path / "cfg" / "session-env" / "abc"
        assert get_history_file() == tmp_path / "cfg" / "history.jsonl"


class TestImportStorageDir:
    def test_defaults_to_home(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        assert get_import_storage_dir() == tmp_path / ".claude-session-imports"
        assert get_snapshot_dir() == tmp_path / ".claude-session-imports" / "pre-import-snapshot"

    def test_follows_claude_config_dir(self, tmp_path, monkeypatch):
        """An import into an isolated config dir must not replace the snapshot that
        protects the default one."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
        assert get_import_storage_dir() == tmp_path / "cfg" / "ccsession-imports"
        assert get_snapshot_dir() == tmp_path / "cfg" / "ccsession-imports" / "pre-import-snapshot"


class TestNormaliserEdgeCases:
    def test_nfd_input_is_normalised_to_nfc_first(self):
        """Claude Code runs cwd.normalize('NFC') before mapping; an HFS+-style NFD name
        ('e' + combining acute) is one character to it."""
        assert get_normalized_project_dir("/Users/me/Café") == "-Users-me-Caf-"
        assert get_normalized_project_dir("/Users/me/Café") == "-Users-me-Caf-"

    def test_surrogate_escaped_bytes_become_one_dash_each(self):
        """os.getcwd() on Linux decodes undecodable bytes with surrogateescape; Node sees
        U+FFFD per byte. Either way: one dash, and never a crash."""
        assert get_normalized_project_dir("/tmp/proj-\udcff") == "-tmp-proj--"

    def test_override_with_a_trailing_newline_is_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
        monkeypatch.setenv("CLAUDE_CODE_PROJECT_DIR_NAME", "abc\n")
        assert get_project_dir_name("/home/user/project") == "-home-user-project"


@pytest.mark.skipif(sys.platform == "win32", reason="undecodable bytes in paths are a POSIX filesystem concept")
class TestUndecodableBytes:
    """Node decodes a non-UTF-8 directory name with one U+FFFD per maximal invalid
    subpart; Python's os.fsdecode gives one surrogate per byte. Expected values come
    from running Claude Code's naming function in Node on the raw bytes."""

    def test_truncated_multibyte_sequence_is_one_dash(self):
        assert get_normalized_project_dir(os.fsdecode(b"/tmp/a\xe9\x80b")) == "-tmp-a-b"

    def test_truncated_four_byte_sequence_is_one_dash(self):
        assert get_normalized_project_dir(os.fsdecode(b"/a\xf0\x9f\x98b")) == "-a-b"

    def test_hash_of_a_long_name_uses_the_replacement_character(self):
        name = get_normalized_project_dir(os.fsdecode(b"/tmp/" + b"x" * 200 + b"\xe9\x80z"))
        assert name.endswith("-k6ln24")


class TestRelativeConfigDir:
    def test_relative_claude_config_dir_is_made_absolute(self, tmp_path, monkeypatch):
        """Recorded paths must not depend on the directory a later restore runs from."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", "cfg-rel")
        assert get_claude_dir() == tmp_path / "cfg-rel"
        assert get_claude_dir().is_absolute()
        assert get_import_storage_dir() == tmp_path / "cfg-rel" / "ccsession-imports"


class TestDotDotIsNormalised:
    """Recorded paths must be canonical: a restore refuses any path that still has '..'."""

    def test_config_dir_with_dot_dot(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "x" / ".." / "cfg"))
        assert get_claude_dir() == tmp_path / "cfg"
        assert get_import_storage_dir() == tmp_path / "cfg" / "ccsession-imports"

    def test_relative_config_dir_with_dot_dot(self, tmp_path, monkeypatch):
        (tmp_path / "sub").mkdir()
        monkeypatch.chdir(tmp_path / "sub")
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", "../cfg")
        assert get_claude_dir() == tmp_path / "cfg"

    def test_home_with_dot_dot(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "h" / ".." / "home")
        assert get_claude_dir() == tmp_path / "home" / ".claude"
        assert get_import_storage_dir() == tmp_path / "home" / ".claude-session-imports"
