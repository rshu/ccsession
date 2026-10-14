import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ccsession.paths import (
    get_claude_dir,
    get_projects_root,
    get_history_file,
    get_session_dir,
    get_normalized_project_dir,
    get_projects_dir,
    get_file_history_dir,
    get_session_env_dir,
    get_import_storage_dir,
    get_snapshot_dir,
)


class TestGetNormalizedProjectDir:
    """Tests for path normalization logic."""

    def test_unix_path_basic(self):
        assert get_normalized_project_dir("/home/user/project", platform="posix") == "-home-user-project"

    def test_unix_path_with_dots(self):
        assert get_normalized_project_dir("/mnt/c/project.git", platform="posix") == "-mnt-c-project-git"

    def test_unix_path_with_underscores(self):
        assert get_normalized_project_dir("/mnt/c/my_project", platform="posix") == "-mnt-c-my-project"

    def test_windows_path(self):
        # C:\Users\user\project -> C-\Users\user\project (: -> -) -> C--Users-user-project (\ -> -)
        assert get_normalized_project_dir("C:\\Users\\user\\project", platform="nt") == "C--Users-user-project"

    def test_windows_path_no_leading_dash(self):
        assert not get_normalized_project_dir("C:\\project", platform="nt").startswith("-")

    def test_unix_path_has_leading_dash(self):
        assert get_normalized_project_dir("/home/user/project", platform="posix").startswith("-")

    def test_accepts_path_object(self):
        assert get_normalized_project_dir(Path("/home/user/project"), platform="posix") == "-home-user-project"

    def test_defaults_to_the_running_platform(self):
        assert get_normalized_project_dir("/x") == get_normalized_project_dir("/x", platform=os.name)


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
