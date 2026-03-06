"""Edge-case tests for session discovery, import, and restore."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from ccsession.export.session_discovery import (
    find_project_sessions, find_active_session, select_session,
)
from ccsession.importing.validation import validate_manifest
from ccsession.restore import get_snapshot_info


# =============================================================================
# Session Discovery Edge Cases
# =============================================================================

class TestSessionDiscoveryEdgeCases:
    def test_empty_project_directory(self, tmp_path, monkeypatch):
        """find_project_sessions returns [] for a project dir with no sessions."""
        fake_home = tmp_path / "home"
        claude_dir = fake_home / ".claude" / "projects" / "-test-project"
        claude_dir.mkdir(parents=True)

        monkeypatch.setattr(Path, "home", lambda: fake_home)
        sessions = find_project_sessions("/test/project")
        assert sessions == []

    def test_no_claude_projects_dir(self, tmp_path, monkeypatch):
        """find_project_sessions returns [] when ~/.claude/projects doesn't exist."""
        fake_home = tmp_path / "home"
        fake_home.mkdir()

        monkeypatch.setattr(Path, "home", lambda: fake_home)
        sessions = find_project_sessions("/nonexistent/project")
        assert sessions == []

    def test_all_sessions_stale(self, tmp_path, monkeypatch):
        """find_active_session returns empty list when all sessions are old."""
        old_time = time.time() - 1000  # 1000 seconds ago
        sessions = [
            {'path': tmp_path / 'a.jsonl', 'mtime': old_time, 'session_id': 'aaa'},
            {'path': tmp_path / 'b.jsonl', 'mtime': old_time - 100, 'session_id': 'bbb'},
        ]
        result = find_active_session(sessions, max_age_seconds=300)
        assert result == []

    def test_select_session_falls_back_to_most_recent(self, tmp_path, capsys):
        """select_session falls back to most recent when all sessions are stale."""
        old_time = time.time() - 1000
        sessions = [
            {'path': tmp_path / 'a.jsonl', 'mtime': old_time, 'session_id': 'aaa-most-recent'},
            {'path': tmp_path / 'b.jsonl', 'mtime': old_time - 100, 'session_id': 'bbb-older'},
        ]
        result = select_session(sessions)
        assert result['session_id'] == 'aaa-most-recent'

    def test_find_active_session_empty_list(self):
        """find_active_session returns None for empty session list."""
        assert find_active_session([], max_age_seconds=300) is None


# =============================================================================
# Import Edge Cases
# =============================================================================

class TestImportEdgeCases:
    def test_manifest_missing(self, tmp_path):
        """Should raise ImportError when no manifest file exists."""
        export_dir = tmp_path / "export"
        export_dir.mkdir()

        with pytest.raises(ImportError, match="No .ccsession-manifest.json found"):
            validate_manifest(export_dir)

    def test_manifest_invalid_json(self, tmp_path):
        """Should raise ImportError for malformed JSON manifest."""
        export_dir = tmp_path / "export"
        export_dir.mkdir()
        (export_dir / ".ccsession-manifest.json").write_text("{not valid}", encoding="utf-8")

        with pytest.raises(ImportError, match="Invalid manifest JSON"):
            validate_manifest(export_dir)

    def test_manifest_missing_required_fields(self, tmp_path):
        """Should raise ImportError when required fields are missing."""
        export_dir = tmp_path / "export"
        export_dir.mkdir()
        (export_dir / ".ccsession-manifest.json").write_text(
            json.dumps({"ccsession_version": "2.0.0"}), encoding="utf-8"
        )

        with pytest.raises(ImportError, match="Missing required fields"):
            validate_manifest(export_dir)

    def test_manifest_valid_returns_dict(self, tmp_path):
        """Should return parsed manifest dict when valid."""
        export_dir = tmp_path / "export"
        export_dir.mkdir()
        manifest = {
            "ccsession_version": "2.0.0",
            "session_id": "abc123",
            "export_name": "test",
            "session_data": {"main_session": "session/main.jsonl"},
        }
        (export_dir / ".ccsession-manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )

        result = validate_manifest(export_dir)
        assert result["session_id"] == "abc123"


# =============================================================================
# Restore Edge Cases
# =============================================================================

class TestRestoreEdgeCases:
    def test_no_snapshot_exists(self, tmp_path, monkeypatch):
        """get_snapshot_info raises FileNotFoundError when no snapshot."""
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        with pytest.raises(FileNotFoundError, match="No pre-import snapshot found"):
            get_snapshot_info()

    def test_corrupted_snapshot_info(self, tmp_path, monkeypatch):
        """get_snapshot_info handles corrupted snapshot info gracefully."""
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        snapshot_dir = fake_home / '.claude-session-imports' / 'pre-import-snapshot'
        snapshot_dir.mkdir(parents=True)
        (snapshot_dir / 'snapshot_info.json').write_text("{invalid json", encoding="utf-8")

        # Should raise or handle gracefully — depends on implementation
        with pytest.raises((json.JSONDecodeError, FileNotFoundError, KeyError)):
            get_snapshot_info()
