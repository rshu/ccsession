import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ccsession.paths import (
    get_normalized_project_dir,
    get_projects_dir,
    get_file_history_dir,
    get_todos_dir,
    get_plans_dir,
    get_session_env_dir,
    get_import_storage_dir,
    get_snapshot_dir,
)


class TestGetNormalizedProjectDir:
    """Tests for path normalization logic."""

    def test_unix_path_basic(self):
        with patch("ccsession.paths.os.name", "posix"):
            result = get_normalized_project_dir("/home/user/project")
            assert result == "-home-user-project"

    def test_unix_path_with_dots(self):
        with patch("ccsession.paths.os.name", "posix"):
            result = get_normalized_project_dir("/mnt/c/project.git")
            assert result == "-mnt-c-project-git"

    def test_unix_path_with_underscores(self):
        with patch("ccsession.paths.os.name", "posix"):
            result = get_normalized_project_dir("/mnt/c/my_project")
            assert result == "-mnt-c-my-project"

    def test_windows_path(self):
        with patch("ccsession.paths.os.name", "nt"):
            # C:\Users\user\project -> C-\Users\user\project (: -> -) -> C--Users-user-project (\ -> -)
            result = get_normalized_project_dir("C:\\Users\\user\\project")
            assert result == "C--Users-user-project"

    def test_windows_path_no_leading_dash(self):
        with patch("ccsession.paths.os.name", "nt"):
            result = get_normalized_project_dir("C:\\project")
            assert not result.startswith("-")

    def test_unix_path_has_leading_dash(self):
        with patch("ccsession.paths.os.name", "posix"):
            result = get_normalized_project_dir("/home/user/project")
            assert result.startswith("-")

    def test_accepts_path_object(self):
        with patch("ccsession.paths.os.name", "posix"):
            result = get_normalized_project_dir(Path("/home/user/project"))
            assert result == "-home-user-project"


class TestDirectoryHelpers:
    """Tests for directory path helpers."""

    def test_get_projects_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        with patch("ccsession.paths.os.name", "posix"):
            result = get_projects_dir("/home/user/project")
            assert result == tmp_path / ".claude" / "projects" / "-home-user-project"

    def test_get_file_history_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        result = get_file_history_dir("abc-123")
        assert result == tmp_path / ".claude" / "file-history" / "abc-123"

    def test_get_todos_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        result = get_todos_dir()
        assert result == tmp_path / ".claude" / "todos"

    def test_get_plans_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        result = get_plans_dir()
        assert result == tmp_path / ".claude" / "plans"

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
