import io
import sys
import json
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ccsession.restore import get_snapshot_info, get_last_import_info, restore_snapshot
from ccsession.paths import get_snapshot_dir, get_import_storage_dir


# =============================================================================
# Snapshot Info Tests
# =============================================================================

def test_get_snapshot_info_no_snapshot(tmp_path, monkeypatch):
    """Should raise FileNotFoundError when no snapshot exists."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    with pytest.raises(FileNotFoundError) as excinfo:
        get_snapshot_info()

    assert "No pre-import snapshot found" in str(excinfo.value)


def test_get_snapshot_info_with_snapshot(tmp_path, monkeypatch):
    """Should return snapshot info when snapshot exists."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    # Create snapshot directory structure
    snapshot_dir = fake_home / '.claude-session-imports' / 'pre-import-snapshot'
    snapshot_dir.mkdir(parents=True)

    info = {
        'timestamp': '2026-01-06T12:00:00Z',
        'target_directory': '/home/test/.claude/projects/-test-project',
        'backup_exists': False
    }

    with open(snapshot_dir / 'snapshot_info.json', 'w') as f:
        json.dump(info, f)

    result = get_snapshot_info()

    assert result['exists'] is True
    assert result['timestamp'] == '2026-01-06T12:00:00Z'
    assert result['target_directory'] == '/home/test/.claude/projects/-test-project'
    assert result['backup_exists'] is False


def test_get_snapshot_info_with_backup(tmp_path, monkeypatch):
    """Should return backup path when backup exists."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    # Create snapshot directory structure with backup
    snapshot_dir = fake_home / '.claude-session-imports' / 'pre-import-snapshot'
    snapshot_dir.mkdir(parents=True)

    # Create backup content
    backup_dir = snapshot_dir / 'projects' / '-test-project'
    backup_dir.mkdir(parents=True)
    (backup_dir / 'old-session.jsonl').write_text('{}')

    info = {
        'timestamp': '2026-01-06T12:00:00Z',
        'target_directory': str(fake_home / '.claude' / 'projects' / '-test-project'),
        'backup_exists': True
    }

    with open(snapshot_dir / 'snapshot_info.json', 'w') as f:
        json.dump(info, f)

    result = get_snapshot_info()

    assert result['exists'] is True
    assert result['backup_exists'] is True
    assert result['backup_path'] is not None
    assert '-test-project' in result['backup_path']


# =============================================================================
# Last Import Info Tests
# =============================================================================

def test_get_last_import_info_no_index(tmp_path, monkeypatch):
    """Should return None when no index exists."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    result = get_last_import_info()

    assert result is None


def test_get_last_import_info_with_imports(tmp_path, monkeypatch):
    """Should return most recent import info."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    # Create index
    import_dir = fake_home / '.claude-session-imports'
    import_dir.mkdir(parents=True)

    index = {
        'last_snapshot_taken': '2026-01-06T12:00:00Z',
        'imports': {
            '2026-01-05-100000': {
                'session_name': 'old-session',
                'source_path': '/path/to/old',
                'imported_at': '2026-01-05T10:00:00Z'
            },
            '2026-01-06-120000': {
                'session_name': 'new-session',
                'source_path': '/path/to/new',
                'imported_at': '2026-01-06T12:00:00Z'
            }
        }
    }

    with open(import_dir / 'index.json', 'w') as f:
        json.dump(index, f)

    result = get_last_import_info()

    assert result is not None
    assert result['session_name'] == 'new-session'
    assert result['import_id'] == '2026-01-06-120000'


# =============================================================================
# Restore Tests
# =============================================================================

def test_restore_snapshot_no_snapshot(tmp_path, monkeypatch):
    """Should raise FileNotFoundError when no snapshot exists."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    with pytest.raises(FileNotFoundError):
        restore_snapshot(force=True)


def test_restore_snapshot_empty_backup(tmp_path, monkeypatch):
    """Should delete target directory when backup was empty."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    # Create target directory with imported content
    target_dir = fake_home / '.claude' / 'projects' / '-test-project'
    target_dir.mkdir(parents=True)
    (target_dir / 'imported-session.jsonl').write_text('{"sessionId": "new"}')

    # Create snapshot (no backup - directory was empty before)
    snapshot_dir = fake_home / '.claude-session-imports' / 'pre-import-snapshot'
    snapshot_dir.mkdir(parents=True)

    info = {
        'timestamp': '2026-01-06T12:00:00Z',
        'target_directory': str(target_dir),
        'backup_exists': False
    }

    with open(snapshot_dir / 'snapshot_info.json', 'w') as f:
        json.dump(info, f)

    # Perform restore
    result = restore_snapshot(force=True)

    assert result['restored'] is True
    assert not target_dir.exists()  # Should be deleted
    assert not snapshot_dir.exists()  # Snapshot should be cleaned up


def test_restore_snapshot_with_backup(tmp_path, monkeypatch):
    """Should restore backup content when backup exists."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    # Create target directory with imported content
    target_dir = fake_home / '.claude' / 'projects' / '-test-project'
    target_dir.mkdir(parents=True)
    (target_dir / 'imported-session.jsonl').write_text('{"sessionId": "new"}')

    # Create snapshot with backup
    snapshot_dir = fake_home / '.claude-session-imports' / 'pre-import-snapshot'
    backup_dir = snapshot_dir / 'projects' / '-test-project'
    backup_dir.mkdir(parents=True)
    (backup_dir / 'original-session.jsonl').write_text('{"sessionId": "original"}')

    info = {
        'timestamp': '2026-01-06T12:00:00Z',
        'target_directory': str(target_dir),
        'backup_exists': True
    }

    with open(snapshot_dir / 'snapshot_info.json', 'w') as f:
        json.dump(info, f)

    # Perform restore
    result = restore_snapshot(force=True)

    assert result['restored'] is True
    assert target_dir.exists()
    assert (target_dir / 'original-session.jsonl').exists()
    assert not (target_dir / 'imported-session.jsonl').exists()
    assert not snapshot_dir.exists()  # Snapshot should be cleaned up


def test_restore_snapshot_cleans_up_snapshot(tmp_path, monkeypatch):
    """Should delete snapshot directory after successful restore."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    # Create snapshot
    snapshot_dir = fake_home / '.claude-session-imports' / 'pre-import-snapshot'
    snapshot_dir.mkdir(parents=True)

    target_dir = fake_home / '.claude' / 'projects' / '-test-project'

    info = {
        'timestamp': '2026-01-06T12:00:00Z',
        'target_directory': str(target_dir),
        'backup_exists': False
    }

    with open(snapshot_dir / 'snapshot_info.json', 'w') as f:
        json.dump(info, f)

    # Perform restore
    restore_snapshot(force=True)

    # Snapshot should be deleted
    assert not snapshot_dir.exists()


# =============================================================================
# Edge Cases
# =============================================================================

def test_get_snapshot_info_calculates_age(tmp_path, monkeypatch):
    """Should calculate snapshot age in hours."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    # Create snapshot with timestamp 2 hours ago
    from datetime import datetime, timezone, timedelta
    two_hours_ago = datetime.now(timezone.utc) - timedelta(hours=2)

    snapshot_dir = fake_home / '.claude-session-imports' / 'pre-import-snapshot'
    snapshot_dir.mkdir(parents=True)

    info = {
        'timestamp': two_hours_ago.isoformat().replace('+00:00', 'Z'),
        'target_directory': '/test',
        'backup_exists': False
    }

    with open(snapshot_dir / 'snapshot_info.json', 'w') as f:
        json.dump(info, f)

    result = get_snapshot_info()

    assert result['age_hours'] is not None
    assert 1.9 < result['age_hours'] < 2.1  # Approximately 2 hours


def test_restore_cancelled_without_force(tmp_path, monkeypatch):
    """Should return cancelled when not confirmed (simulated)."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    # Create snapshot
    snapshot_dir = fake_home / '.claude-session-imports' / 'pre-import-snapshot'
    snapshot_dir.mkdir(parents=True)

    info = {
        'timestamp': '2026-01-06T12:00:00Z',
        'target_directory': str(fake_home / '.claude' / 'projects' / '-test'),
        'backup_exists': False
    }

    with open(snapshot_dir / 'snapshot_info.json', 'w') as f:
        json.dump(info, f)

    # A terminal is attached; the user types the wrong confirmation
    class _Tty(io.StringIO):
        def isatty(self):
            return True
    monkeypatch.setattr('sys.stdin', _Tty())
    monkeypatch.setattr('builtins.input', lambda _prompt='': 'WRONG')

    result = restore_snapshot(force=False)

    assert result['restored'] is False
    assert result['reason'] == 'cancelled'
    assert snapshot_dir.exists()  # Should NOT be deleted


# =============================================================================
# A restore undoes everything the import added, and nothing else
# =============================================================================

from unittest.mock import patch  # noqa: E402

from ccsession.importing.importer import import_session  # noqa: E402
from ccsession.paths import get_projects_dir  # noqa: E402
from ccsession.restore import show_info  # noqa: E402

OLD_SID = "7f6738b0-d2cb-44ae-a806-09860af58e1f"
AGENT = "a9ba8b4d8b37efc78"


def _full_export(root: Path, project: str) -> None:
    """A layout-2 export carrying a sub-agent, prompt history, a file-history snapshot and a command."""
    mirror = root / "session" / "session-dir" / "subagents"
    mirror.mkdir(parents=True)
    main = [
        {"type": "user", "uuid": "u1", "parentUuid": None, "sessionId": OLD_SID, "cwd": project, "version": "2.1.287",
         "message": {"role": "user", "content": "fix it"}},
        {"type": "assistant", "uuid": "u2", "parentUuid": "u1", "sessionId": OLD_SID, "cwd": project,
         "message": {"id": "msg_01", "role": "assistant", "content": [{"type": "text", "text": "done"}]}},
    ]
    (root / "session" / "main.jsonl").write_text("".join(json.dumps(r) + "\n" for r in main), encoding="utf-8")
    (mirror / f"agent-{AGENT}.jsonl").write_text(json.dumps(
        {"type": "user", "uuid": "s1", "parentUuid": None, "agentId": AGENT, "sessionId": OLD_SID, "cwd": project,
         "message": {"role": "user", "content": "sub"}}) + "\n", encoding="utf-8")
    (root / "session" / "history.jsonl").write_text(json.dumps(
        {"display": "fix it", "pastedContents": {}, "timestamp": 1, "project": project, "sessionId": OLD_SID}) + "\n",
        encoding="utf-8")
    (root / "session" / "file-history").mkdir()
    (root / "session" / "file-history" / "160c@v1").write_text("snapshot", encoding="utf-8")
    (root / "config" / "commands").mkdir(parents=True)
    (root / "config" / "commands" / "review.md").write_text("r", encoding="utf-8")
    (root / "config" / "skills" / "deploy").mkdir(parents=True)
    (root / "config" / "skills" / "deploy" / "SKILL.md").write_text("# deploy", encoding="utf-8")
    (root / ".ccsession-manifest.json").write_text(json.dumps({
        "ccsession_version": "2.1.0", "layout_version": 2, "session_id": OLD_SID, "session_slug": None, "export_name": "t",
        "claude_code_version": "2.1.287",
        "original_context": {"user": "u", "platform": "darwin", "repo_path": project, "git_branch": "main"},
        "session_data": {"main_session": "session/main.jsonl",
                         "agent_sessions": [f"session/session-dir/subagents/agent-{AGENT}.jsonl"],
                         "agent_meta": [], "file_history": ["session/file-history/160c@v1"], "session_env": None,
                         "session_dir": "session/session-dir/", "history": "session/history.jsonl"},
        "config_snapshot": {"commands": ["config/commands/review.md"], "skills": ["config/skills/deploy/SKILL.md"],
                            "hooks": [], "agents": [], "rules": [], "settings": None, "claude_md": None},
        "statistics": {"message_count": 2, "user_messages": 1, "assistant_messages": 1, "tool_uses": 0,
                       "duration_seconds": None, "models_used": []},
    }), encoding="utf-8")


def _import_into(tmp_path, monkeypatch, *, preserve=False, extra_history=(), existing_dirs=()):
    """Import the full export into a project that already has state of its own; returns (project, new_sid)."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    export = tmp_path / "export"
    _full_export(export, "/old/proj")
    project = (tmp_path / "newproj").resolve()
    project.mkdir()
    for d in existing_dirs:
        (project / d).mkdir(parents=True)
    (project / "CLAUDE.md").write_text("# mine\n", encoding="utf-8")
    history = tmp_path / ".claude" / "history.jsonl"
    history.parent.mkdir(parents=True)
    rows = [{"display": "earlier", "timestamp": 0, "project": "/x", "sessionId": "other"}, *extra_history]
    history.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    target = get_projects_dir(project)
    target.mkdir(parents=True)
    (target / "old.jsonl").write_text('{"sessionId": "old"}\n', encoding="utf-8")
    with patch("ccsession.importing.importer.check_version_compatibility", return_value=(True, None)):
        summary = import_session(export, project_path=project, non_interactive=True, preserve_session_id=preserve)
    return project, summary["session_id"]


def test_restore_undoes_everything_the_import_added(tmp_path, monkeypatch):
    project, new_sid = _import_into(tmp_path, monkeypatch)
    target = get_projects_dir(project)
    assert (target / f"{new_sid}.jsonl").is_file() and (target / new_sid / "subagents").is_dir()
    assert (tmp_path / ".claude" / "file-history" / new_sid / "160c@v1").is_file()
    assert (project / ".claude" / "commands" / "review.md").is_file()
    assert "## Imported Session Context" in (project / "CLAUDE.md").read_text(encoding="utf-8")

    result = restore_snapshot(force=True)

    assert result["restored"] is True
    assert not (target / f"{new_sid}.jsonl").exists() and not (target / new_sid).exists()
    assert (target / "old.jsonl").read_text(encoding="utf-8") == '{"sessionId": "old"}\n'
    history = [json.loads(l) for l in (tmp_path / ".claude" / "history.jsonl").read_text(encoding="utf-8").splitlines()]
    assert history == [{"display": "earlier", "timestamp": 0, "project": "/x", "sessionId": "other"}]
    assert not (tmp_path / ".claude" / "file-history" / new_sid).exists()
    assert not (project / ".claude" / "commands" / "review.md").exists()
    assert (project / "CLAUDE.md").read_text(encoding="utf-8") == "# mine\n"
    assert not (tmp_path / ".claude-session-imports" / "pre-import-snapshot").exists()


def test_restore_keeps_later_edits_to_claude_md_and_history(tmp_path, monkeypatch):
    project, new_sid = _import_into(tmp_path, monkeypatch)
    with open(project / "CLAUDE.md", "a", encoding="utf-8") as f:
        f.write("\n# later\n")
    history = tmp_path / ".claude" / "history.jsonl"
    with open(history, "a", encoding="utf-8") as f:
        f.write(json.dumps({"display": "after", "timestamp": 9, "project": "/y", "sessionId": "another"}) + "\n")

    restore_snapshot(force=True)

    assert (project / "CLAUDE.md").read_text(encoding="utf-8") == "# mine\n\n# later\n"
    lines = [json.loads(l)["display"] for l in history.read_text(encoding="utf-8").splitlines()]
    assert lines == ["earlier", "after"]


def test_restore_plan_distinguishes_deletions_from_rollbacks(tmp_path, monkeypatch, capsys):
    project, new_sid = _import_into(tmp_path, monkeypatch)
    target = get_projects_dir(project)
    (target / "old.jsonl").write_text('{"sessionId": "old"}\n{"appended": true}\n', encoding="utf-8")

    restore_snapshot(force=True)

    out = capsys.readouterr().out
    assert f"{new_sid}.jsonl" in out and "deleted" in out.lower()
    assert "old.jsonl" in out and "rolled back" in out.lower()
    assert "history.jsonl" in out and "CLAUDE.md" in out and "review.md" in out


def test_restore_refuses_a_target_that_is_not_a_project_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    victim = tmp_path / "unrelated"
    victim.mkdir()
    (victim / "keep.txt").write_text("precious", encoding="utf-8")
    snapshot_dir = tmp_path / ".claude-session-imports" / "pre-import-snapshot"
    snapshot_dir.mkdir(parents=True)
    (snapshot_dir / "snapshot_info.json").write_text(json.dumps({
        "timestamp": "2026-01-06T12:00:00Z", "target_directory": str(victim), "backup_exists": False}), encoding="utf-8")

    with pytest.raises(RuntimeError, match="projects"):
        restore_snapshot(force=True)

    assert (victim / "keep.txt").read_text(encoding="utf-8") == "precious"
    assert snapshot_dir.exists()


def test_restore_without_a_terminal_and_without_yes_is_refused_cleanly(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    snapshot_dir = tmp_path / ".claude-session-imports" / "pre-import-snapshot"
    snapshot_dir.mkdir(parents=True)
    (snapshot_dir / "snapshot_info.json").write_text(json.dumps({
        "timestamp": "2026-01-06T12:00:00Z",
        "target_directory": str(tmp_path / ".claude" / "projects" / "-p"), "backup_exists": False}), encoding="utf-8")
    monkeypatch.setattr("sys.stdin", io.StringIO(""))

    result = restore_snapshot(force=False)

    assert result == {"restored": False, "reason": "no-tty"}
    assert "--yes" in capsys.readouterr().err
    assert snapshot_dir.exists()


def test_messages_name_the_ccsession_command_not_a_script(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert show_info() == 1
    assert "ccsession.py" not in capsys.readouterr().err

    snapshot_dir = tmp_path / ".claude-session-imports" / "pre-import-snapshot"
    snapshot_dir.mkdir(parents=True)
    (snapshot_dir / "snapshot_info.json").write_text(json.dumps({
        "timestamp": "2026-01-06T12:00:00Z", "target_directory": "/x/projects/-p", "backup_exists": False}),
        encoding="utf-8")
    assert show_info() == 0
    out = capsys.readouterr().out
    assert "ccsession.py" not in out and "ccsession restore --restore" in out


# =============================================================================
# Second review round: precise undo, containment, legacy locations
# =============================================================================

from ccsession.output import QUIET, NORMAL, set_verbosity  # noqa: E402


def test_restore_removes_only_the_history_lines_the_import_wrote(tmp_path, monkeypatch):
    """With --preserve-session-id the id is not fresh: lines that existed before the import
    (the export's own line is already in history.jsonl here, so the import appends nothing)
    and lines typed later must survive."""
    own = {"display": "fix it", "pastedContents": {}, "timestamp": 1, "project": "/old/proj", "sessionId": OLD_SID}
    project, new_sid = _import_into(tmp_path, monkeypatch, preserve=True, extra_history=[own])
    assert new_sid == OLD_SID
    history = tmp_path / ".claude" / "history.jsonl"
    with open(history, "a", encoding="utf-8") as f:
        f.write(json.dumps({"display": "typed later", "timestamp": 9, "project": str(project), "sessionId": OLD_SID}) + "\n")

    result = restore_snapshot(force=True)

    assert result["history_lines_removed"] == 0
    lines = [json.loads(l)["display"] for l in history.read_text(encoding="utf-8").splitlines()]
    assert lines == ["earlier", "fix it", "typed later"]


def test_restore_keeps_prompts_typed_into_the_imported_session_afterwards(tmp_path, monkeypatch):
    project, new_sid = _import_into(tmp_path, monkeypatch)
    history = tmp_path / ".claude" / "history.jsonl"
    with open(history, "a", encoding="utf-8") as f:
        f.write(json.dumps({"display": "typed later", "timestamp": 9, "project": str(project), "sessionId": new_sid}) + "\n")

    result = restore_snapshot(force=True)

    assert result["history_lines_removed"] == 1
    lines = [json.loads(l)["display"] for l in history.read_text(encoding="utf-8").splitlines()]
    assert lines == ["earlier", "typed later"]


def test_restore_removes_only_directories_the_import_created(tmp_path, monkeypatch):
    project, _ = _import_into(tmp_path, monkeypatch, existing_dirs=[".claude/commands", ".claude/hooks"])
    assert (project / ".claude" / "skills" / "deploy" / "SKILL.md").is_file()

    restore_snapshot(force=True)

    assert (project / ".claude" / "commands").is_dir(), "pre-existing directory must survive"
    assert (project / ".claude" / "hooks").is_dir()
    assert not (project / ".claude" / "skills").exists(), "directory created by the import is removed"


def test_restore_removes_a_dot_claude_directory_the_import_created(tmp_path, monkeypatch):
    project, _ = _import_into(tmp_path, monkeypatch)
    assert (project / ".claude").is_dir()

    restore_snapshot(force=True)

    assert not (project / ".claude").exists()


def _snapshot(tmp_path, **info):
    snapshot_dir = tmp_path / ".claude-session-imports" / "pre-import-snapshot"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    base = {"timestamp": "2026-01-06T12:00:00Z", "backup_exists": False}
    base.update(info)
    (snapshot_dir / "snapshot_info.json").write_text(json.dumps(base), encoding="utf-8")
    return snapshot_dir


def test_restore_refuses_a_target_under_another_projects_directory(tmp_path, monkeypatch):
    """`~/projects/<repo>` is also '.../projects/<name>'; only the recorded Claude dir counts."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    victim = tmp_path / "projects" / "my-real-repo"
    victim.mkdir(parents=True)
    (victim / "keep.txt").write_text("precious", encoding="utf-8")
    snapshot_dir = _snapshot(tmp_path, target_directory=str(victim), claude_dir=str(tmp_path / ".claude"),
                             snapshot_version=2, new_session_id="sid")

    with pytest.raises(RuntimeError, match="Refusing"):
        restore_snapshot(force=True)

    assert (victim / "keep.txt").read_text(encoding="utf-8") == "precious" and snapshot_dir.exists()


def test_restore_of_a_2_1_0_snapshot_requires_the_current_projects_root(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    victim = tmp_path / "elsewhere" / "projects" / "-p"
    victim.mkdir(parents=True)
    _snapshot(tmp_path, target_directory=str(victim))

    with pytest.raises(RuntimeError, match="Refusing"):
        restore_snapshot(force=True)

    assert victim.exists()


def test_restore_refuses_a_relative_target(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "projects" / "victim").mkdir(parents=True)
    _snapshot(tmp_path, target_directory="projects/victim")

    with pytest.raises(RuntimeError, match="Refusing"):
        restore_snapshot(force=True)

    assert (tmp_path / "projects" / "victim").exists()


def test_restore_refuses_a_damaged_snapshot(tmp_path, monkeypatch):
    """backup_exists says the project directory was copied, but the copy is missing: deleting
    the current content would lose the pre-existing sessions for good."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    target = tmp_path / ".claude" / "projects" / "-p"
    target.mkdir(parents=True)
    (target / "pre.jsonl").write_text("{}\n", encoding="utf-8")
    _snapshot(tmp_path, target_directory=str(target), backup_exists=True)

    with pytest.raises(RuntimeError, match="damaged|missing"):
        restore_snapshot(force=True)

    assert (target / "pre.jsonl").exists()


def test_restore_only_deletes_the_file_history_directory_of_the_imported_session(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "keep.txt").write_text("precious", encoding="utf-8")
    target = tmp_path / ".claude" / "projects" / "-p"
    _snapshot(tmp_path, target_directory=str(target), claude_dir=str(tmp_path / ".claude"), snapshot_version=2,
              new_session_id="sid", file_history_dir={"path": str(victim), "existed": False})

    result = restore_snapshot(force=True)

    assert result["restored"] is True
    assert (victim / "keep.txt").read_text(encoding="utf-8") == "precious"


def test_restore_only_removes_config_files_under_the_project(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    victim = tmp_path / "victim.txt"
    victim.write_text("precious", encoding="utf-8")
    target = tmp_path / ".claude" / "projects" / "-p"
    _snapshot(tmp_path, target_directory=str(target), claude_dir=str(tmp_path / ".claude"), snapshot_version=2,
              new_session_id="sid", project_path=str(tmp_path / "proj"), created_config_files=[str(victim)])

    restore_snapshot(force=True)

    assert victim.read_text(encoding="utf-8") == "precious"


def test_restore_with_a_closed_stdin_is_refused_cleanly(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    _snapshot(tmp_path, target_directory=str(tmp_path / ".claude" / "projects" / "-p"))
    monkeypatch.setattr("sys.stdin", None)

    assert restore_snapshot(force=False) == {"restored": False, "reason": "no-tty"}
    assert "--yes" in capsys.readouterr().err


def test_quiet_show_info_still_prints_the_summary(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    _snapshot(tmp_path, target_directory="/x/projects/-p")
    set_verbosity(QUIET)
    try:
        assert show_info() == 0
    finally:
        set_verbosity(NORMAL)
    out = capsys.readouterr().out
    assert "Target directory: /x/projects/-p" in out and "ccsession restore --restore" in out


def test_a_2_1_0_snapshot_in_the_legacy_location_is_found_under_config_dir(tmp_path, monkeypatch):
    """2.1.0 always wrote ~/.claude-session-imports, even with CLAUDE_CONFIG_DIR set."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    cfg = tmp_path / "cfg"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    target = cfg / "projects" / "-p"
    target.mkdir(parents=True)
    (target / "imported.jsonl").write_text("{}\n", encoding="utf-8")
    legacy = _snapshot(tmp_path, target_directory=str(target))

    info = get_snapshot_info()
    assert info["target_directory"] == str(target)

    result = restore_snapshot(force=True)

    assert result["restored"] is True
    assert not target.exists() and not legacy.exists()


def test_last_import_is_chosen_by_time_not_by_key_order(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    storage = tmp_path / ".claude-session-imports"
    storage.mkdir()
    imports = {}
    for n in range(1, 12):
        key = "2026-10-14-120000" if n == 1 else f"2026-10-14-120000-{n}"
        imports[key] = {"session_name": f"s{n}", "source_path": "/p", "imported_at": f"2026-10-14T12:00:00.{n:06d}Z"}
    (storage / "index.json").write_text(json.dumps({"imports": imports}), encoding="utf-8")

    assert get_last_import_info()["import_id"] == "2026-10-14-120000-11"


# =============================================================================
# Third review round
# =============================================================================

import os  # noqa: E402
import stat  # noqa: E402
import sys as _sys  # noqa: E402

UUID = "11111111-2222-4333-8444-555555555555"


def test_restore_refuses_a_dot_dot_target(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    cfg = tmp_path / ".claude"
    (cfg / "projects").mkdir(parents=True)
    (cfg / "settings.json").write_text("{}", encoding="utf-8")
    snapshot_dir = _snapshot(tmp_path, target_directory=str(cfg / "projects" / ".."), claude_dir=str(cfg),
                             snapshot_version=2, new_session_id=UUID)

    with pytest.raises(RuntimeError, match="Refusing"):
        restore_snapshot(force=True)

    assert (cfg / "settings.json").exists() and snapshot_dir.exists()


@pytest.mark.parametrize("sid", [".", "..", "../victim", UUID + "/.."])
def test_restore_never_deletes_file_history_outside_a_uuid_directory(tmp_path, monkeypatch, sid):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    cfg = tmp_path / ".claude"
    (cfg / "file-history" / "other").mkdir(parents=True)
    (tmp_path / ".claude" / "victim").mkdir()
    _snapshot(tmp_path, target_directory=str(cfg / "projects" / "-p"), claude_dir=str(cfg), snapshot_version=2,
              new_session_id=sid, file_history_dir={"path": str(cfg / "file-history" / sid), "existed": False})

    restore_snapshot(force=True)

    assert (cfg / "file-history" / "other").is_dir() and (cfg / "victim").is_dir()


def test_restore_never_deletes_config_files_through_dot_dot(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    victim = tmp_path / "victim.txt"
    victim.write_text("precious", encoding="utf-8")
    project = tmp_path / "proj"
    (project / ".claude").mkdir(parents=True)
    _snapshot(tmp_path, target_directory=str(tmp_path / ".claude" / "projects" / "-p"),
              claude_dir=str(tmp_path / ".claude"), snapshot_version=2, new_session_id=UUID,
              project_path=str(project), created_config_files=[str(project / ".claude" / ".." / ".." / "victim.txt")])

    restore_snapshot(force=True)

    assert victim.read_text(encoding="utf-8") == "precious"


def test_a_current_format_snapshot_in_the_legacy_location_is_not_used_under_config_dir(tmp_path, monkeypatch):
    """Only ccsession 2.1.0 snapshots are looked up in ~/.claude-session-imports when
    CLAUDE_CONFIG_DIR is set; a newer one there belongs to the default ~/.claude."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    default_target = tmp_path / ".claude" / "projects" / "-p"
    default_target.mkdir(parents=True)
    (default_target / "later.jsonl").write_text("{}\n", encoding="utf-8")
    _snapshot(tmp_path, target_directory=str(default_target), claude_dir=str(tmp_path / ".claude"),
              snapshot_version=2, new_session_id=UUID)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "isolated"))

    with pytest.raises(FileNotFoundError) as excinfo:
        restore_snapshot(force=True)

    assert str(tmp_path / "isolated" / "ccsession-imports") in str(excinfo.value)
    assert (default_target / "later.jsonl").exists()


def test_restore_refuses_a_snapshot_taken_for_another_claude_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    cfg = tmp_path / "cfg"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    other = tmp_path / "other-claude"
    (other / "projects" / "-p").mkdir(parents=True)
    snapshot_dir = cfg / "ccsession-imports" / "pre-import-snapshot"
    snapshot_dir.mkdir(parents=True)
    (snapshot_dir / "snapshot_info.json").write_text(json.dumps({
        "snapshot_version": 2, "timestamp": "2026-01-06T12:00:00Z", "backup_exists": False,
        "target_directory": str(other / "projects" / "-p"), "claude_dir": str(other), "new_session_id": UUID}),
        encoding="utf-8")

    with pytest.raises(RuntimeError, match="different Claude config directory"):
        restore_snapshot(force=True)

    assert (other / "projects" / "-p").is_dir()


def test_import_and_restore_with_a_relative_config_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "cfg-rel")
    export = tmp_path / "export"
    _full_export(export, "/old/proj")
    project = (tmp_path / "newproj").resolve()
    project.mkdir()
    with patch("ccsession.importing.importer.check_version_compatibility", return_value=(True, None)):
        summary = import_session(export, project_path=project, non_interactive=True, skip_config=True)
    assert Path(summary["session_file"]).is_file()

    assert restore_snapshot(force=True)["restored"] is True
    assert not Path(summary["session_file"]).exists()


@pytest.mark.skipif(_sys.platform == "win32", reason="POSIX permissions and symlinks")
def test_restore_keeps_the_history_file_mode_and_symlink(tmp_path, monkeypatch):
    project, new_sid = _import_into(tmp_path, monkeypatch)
    history = tmp_path / ".claude" / "history.jsonl"
    real = tmp_path / "dotfiles" / "history.jsonl"
    real.parent.mkdir()
    history.replace(real)
    os.symlink(real, history)
    os.chmod(real, 0o600)

    restore_snapshot(force=True)

    assert history.is_symlink(), "a symlinked history.jsonl stays a symlink"
    assert stat.S_IMODE(real.stat().st_mode) == 0o600
    assert [json.loads(l)["display"] for l in real.read_text(encoding="utf-8").splitlines()] == ["earlier"]


def test_restore_keeps_a_prompt_appended_while_it_rewrites_the_history(tmp_path, monkeypatch):
    project, new_sid = _import_into(tmp_path, monkeypatch)
    history = tmp_path / ".claude" / "history.jsonl"
    import ccsession.history_file as history_module
    real_read = history_module._read_bytes
    calls = []

    def read_then_race(path):
        data = real_read(path)
        if not calls:  # a writer that ignores the lock appends right after the read
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"display": "racing", "timestamp": 99, "sessionId": "other"}) + "\n")
        calls.append(1)
        return data

    monkeypatch.setattr(history_module, "_read_bytes", read_then_race)

    restore_snapshot(force=True)

    displays = [json.loads(l)["display"] for l in history.read_text(encoding="utf-8").splitlines()]
    assert displays == ["earlier", "racing"]


def test_restore_keeps_claude_codes_auto_memory(tmp_path, monkeypatch, capsys):
    """projects/<name>/memory/ holds Claude Code's auto-memory; the import never writes it."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    export = tmp_path / "export"
    _full_export(export, "/old/proj")
    project = (tmp_path / "newproj").resolve()
    project.mkdir()
    target = get_projects_dir(project)
    (target / "memory").mkdir(parents=True)
    (target / "memory" / "MEMORY.md").write_text("old memory\n", encoding="utf-8")
    with patch("ccsession.importing.importer.check_version_compatibility", return_value=(True, None)):
        import_session(export, project_path=project, non_interactive=True, skip_config=True)
    with open(target / "memory" / "MEMORY.md", "a", encoding="utf-8") as f:
        f.write("learned later\n")
    (target / "memory" / "feedback.md").write_text("new", encoding="utf-8")

    restore_snapshot(force=True)

    assert (target / "memory" / "MEMORY.md").read_text(encoding="utf-8") == "old memory\nlearned later\n"
    assert (target / "memory" / "feedback.md").read_text(encoding="utf-8") == "new"
    out = capsys.readouterr().out.lower()
    assert "memory/" in out and "kept" in out


def test_restore_keeps_auto_memory_created_after_an_import_into_a_new_project(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    export = tmp_path / "export"
    _full_export(export, "/old/proj")
    project = (tmp_path / "newproj").resolve()
    project.mkdir()
    with patch("ccsession.importing.importer.check_version_compatibility", return_value=(True, None)):
        summary = import_session(export, project_path=project, non_interactive=True, skip_config=True)
    target = get_projects_dir(project)
    (target / "memory").mkdir()
    (target / "memory" / "MEMORY.md").write_text("fresh", encoding="utf-8")

    restore_snapshot(force=True)

    assert not Path(summary["session_file"]).exists()
    assert (target / "memory" / "MEMORY.md").read_text(encoding="utf-8") == "fresh"


def test_plan_names_the_import_the_snapshot_protects(tmp_path, monkeypatch, capsys):
    """After a failed import the index still names the previous successful one."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    storage = tmp_path / ".claude-session-imports"
    storage.mkdir()
    (storage / "index.json").write_text(json.dumps({"imports": {"2026-01-01-000000": {
        "session_name": "older-export", "source_path": "/p", "imported_at": "2026-01-01T00:00:00Z"}}}), encoding="utf-8")
    _snapshot(tmp_path, target_directory=str(tmp_path / ".claude" / "projects" / "-p"),
              claude_dir=str(tmp_path / ".claude"), snapshot_version=2, new_session_id=UUID,
              export_name="failed-export", export_path="/exports/failed-export")

    restore_snapshot(force=True)

    out = capsys.readouterr().out
    assert "failed-export" in out and "older-export" not in out


def test_last_import_compares_times_not_strings(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    storage = tmp_path / ".claude-session-imports"
    storage.mkdir()
    (storage / "index.json").write_text(json.dumps({"imports": {
        "2026-10-14-130000": {"session_name": "first", "imported_at": "2026-10-14T13:00:00Z"},
        "2026-10-14-130000-2": {"session_name": "second", "imported_at": "2026-10-14T13:00:00.070000Z"}}}),
        encoding="utf-8")

    assert get_last_import_info()["session_name"] == "second"


def test_damaged_snapshot_message_names_the_missing_copy(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    target = tmp_path / ".claude" / "projects" / "-p"
    target.mkdir(parents=True)
    snapshot_dir = _snapshot(tmp_path, target_directory=str(target), backup_exists=True)
    (snapshot_dir / "projects" / "-other").mkdir(parents=True)

    with pytest.raises(RuntimeError) as excinfo:
        restore_snapshot(force=True)

    assert str(snapshot_dir / "projects" / "-p") in str(excinfo.value)


def test_an_old_snapshot_is_flagged_in_the_plan(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    _snapshot(tmp_path, target_directory=str(tmp_path / ".claude" / "projects" / "-p"), timestamp="2020-01-01T00:00:00Z")

    restore_snapshot(force=True)

    assert "days old" in capsys.readouterr().err


def test_restore_removes_only_the_file_history_snapshots_the_import_added(tmp_path, monkeypatch):
    """--preserve-session-id into a machine that already has this session's file history."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    existing = tmp_path / ".claude" / "file-history" / OLD_SID
    existing.mkdir(parents=True)
    (existing / "160c@v0").write_text("local", encoding="utf-8")
    export = tmp_path / "export"
    _full_export(export, "/old/proj")
    project = (tmp_path / "newproj").resolve()
    project.mkdir()
    with patch("ccsession.importing.importer.check_version_compatibility", return_value=(True, None)):
        import_session(export, project_path=project, non_interactive=True, preserve_session_id=True, skip_config=True)
    assert (existing / "160c@v1").is_file()

    restore_snapshot(force=True)

    assert (existing / "160c@v0").read_text(encoding="utf-8") == "local"
    assert not (existing / "160c@v1").exists()


# =============================================================================
# Fourth review round
# =============================================================================

def test_import_and_restore_with_dot_dot_in_the_config_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / "x").mkdir()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "x" / ".." / "cfg"))
    export = tmp_path / "export"
    _full_export(export, "/old/proj")
    project = (tmp_path / "newproj").resolve()
    project.mkdir()
    with patch("ccsession.importing.importer.check_version_compatibility", return_value=(True, None)):
        summary = import_session(export, project_path=project, non_interactive=True)

    assert restore_snapshot(force=True)["restored"] is True
    assert not Path(summary["session_file"]).exists()


def test_a_2_1_0_snapshot_with_a_relative_target_is_restored_from_the_same_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "cfg-rel")
    target = tmp_path / "cfg-rel" / "projects" / "-p"
    target.mkdir(parents=True)
    (target / "imported.jsonl").write_text("{}\n", encoding="utf-8")
    _snapshot(tmp_path, target_directory="cfg-rel/projects/-p")

    assert restore_snapshot(force=True)["restored"] is True
    assert not target.exists()


def test_a_2_1_0_snapshot_does_not_resurface_after_a_newer_restore(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    cfg = tmp_path / "cfg"
    target = cfg / "projects" / "-p"
    target.mkdir(parents=True)
    (target / "work.jsonl").write_text("{}\n", encoding="utf-8")
    _snapshot(tmp_path, target_directory=str(target))  # 2.1.0 snapshot in ~/.claude-session-imports
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    (cfg / "ccsession-imports").mkdir()
    (cfg / "ccsession-imports" / "index.json").write_text('{"imports": {}}', encoding="utf-8")

    with pytest.raises(FileNotFoundError):
        restore_snapshot(force=True)

    assert (target / "work.jsonl").exists()


def test_a_moved_config_dir_is_explained(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    cfg = tmp_path / "cfg"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    snapshot_dir = cfg / "ccsession-imports" / "pre-import-snapshot"
    snapshot_dir.mkdir(parents=True)
    (snapshot_dir / "snapshot_info.json").write_text(json.dumps({
        "snapshot_version": 2, "timestamp": "2026-01-06T12:00:00Z", "backup_exists": False,
        "target_directory": str(tmp_path / "old-cfg" / "projects" / "-p"), "claude_dir": str(tmp_path / "old-cfg"),
        "new_session_id": UUID}), encoding="utf-8")

    with pytest.raises(RuntimeError) as excinfo:
        restore_snapshot(force=True)

    message = str(excinfo.value)
    assert "moved or copied" in message and str(snapshot_dir / "snapshot_info.json") in message


@pytest.mark.parametrize("field,value", [
    ("history_file", lambda t: {"path": str(t / "dotfile"), "existed": False}),
    ("claude_md", lambda t: {"path": str(t / "dotfile"), "existed": False}),
])
def test_tampered_history_and_claude_md_paths_are_not_touched(tmp_path, monkeypatch, field, value):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    victim = tmp_path / "dotfile"
    victim.write_text("line\n", encoding="utf-8")
    info = dict(target_directory=str(tmp_path / ".claude" / "projects" / "-p"), claude_dir=str(tmp_path / ".claude"),
                snapshot_version=2, new_session_id=UUID, project_path=str(tmp_path / "proj"),
                appended_history_lines=["line"], claude_md_note="line\n")
    info[field] = value(tmp_path)
    _snapshot(tmp_path, **info)

    restore_snapshot(force=True)

    assert victim.read_text(encoding="utf-8") == "line\n"


@pytest.mark.parametrize("raw", ['[]', 'null', '{"timestamp": "x", "target_directory": null, "backup_exists": true}',
                                 '{"timestamp": "x", "target_directory": 123}'])
def test_a_malformed_snapshot_info_is_reported_as_damaged(tmp_path, monkeypatch, raw):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    snapshot_dir = tmp_path / ".claude-session-imports" / "pre-import-snapshot"
    snapshot_dir.mkdir(parents=True)
    (snapshot_dir / "snapshot_info.json").write_text(raw, encoding="utf-8")

    with pytest.raises(RuntimeError, match="damaged"):
        restore_snapshot(force=True)
    with pytest.raises(RuntimeError, match="damaged"):
        show_info()


def test_a_backup_that_is_a_file_is_a_damaged_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    target = tmp_path / ".claude" / "projects" / "-p"
    target.mkdir(parents=True)
    (target / "pre.jsonl").write_text("{}\n", encoding="utf-8")
    snapshot_dir = _snapshot(tmp_path, target_directory=str(target), backup_exists=True)
    (snapshot_dir / "projects").mkdir()
    (snapshot_dir / "projects" / "-p").write_text("not a directory", encoding="utf-8")

    with pytest.raises(RuntimeError, match="damaged"):
        restore_snapshot(force=True)

    assert (target / "pre.jsonl").exists()


def test_a_restore_that_fails_while_copying_back_leaves_the_project_untouched(tmp_path, monkeypatch):
    project, new_sid = _import_into(tmp_path, monkeypatch)
    target = get_projects_dir(project)
    import ccsession.restore as restore_module

    def broken_copytree(*args, **kwargs):
        raise OSError("No space left on device")

    monkeypatch.setattr(restore_module.shutil, "copytree", broken_copytree)
    with pytest.raises(RuntimeError):
        restore_snapshot(force=True)
    monkeypatch.undo()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    assert (target / "old.jsonl").exists() and (target / f"{new_sid}.jsonl").exists()
    assert not list(target.parent.glob(".ccsession-*")), "no staging directory is left behind"
    assert restore_snapshot(force=True)["restored"] is True
    assert (target / "old.jsonl").exists() and not (target / f"{new_sid}.jsonl").exists()


def test_an_interrupted_restore_says_how_to_recover(tmp_path, monkeypatch, capsys):
    project, _ = _import_into(tmp_path, monkeypatch)
    import ccsession.restore as restore_module
    monkeypatch.setattr(restore_module, "_undo_history", lambda info: (_ for _ in ()).throw(KeyboardInterrupt()))

    with pytest.raises(KeyboardInterrupt):
        restore_snapshot(force=True)

    err = capsys.readouterr().err
    assert "ccsession restore --restore" in err and "snapshot" in err


def test_restore_keeps_every_project_entry_claude_code_reserves(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    export = tmp_path / "export"
    _full_export(export, "/old/proj")
    project = (tmp_path / "newproj").resolve()
    project.mkdir()
    with patch("ccsession.importing.importer.check_version_compatibility", return_value=(True, None)):
        import_session(export, project_path=project, non_interactive=True, skip_config=True)
    target = get_projects_dir(project)
    (target / "tiny_memory").mkdir()
    (target / "tiny_memory" / "m.md").write_text("m", encoding="utf-8")
    (target / "bridge-pointer.json").write_text("{}", encoding="utf-8")
    (target / ".session-aliases").write_text("a", encoding="utf-8")

    restore_snapshot(force=True)

    assert (target / "tiny_memory" / "m.md").exists()
    assert (target / "bridge-pointer.json").exists() and (target / ".session-aliases").exists()


def test_restore_removes_a_read_only_imported_file(tmp_path, monkeypatch):
    import stat
    project, new_sid = _import_into(tmp_path, monkeypatch)
    target = get_projects_dir(project)
    locked = target / new_sid / "tool-results" / "locked.txt"
    locked.parent.mkdir(parents=True, exist_ok=True)
    locked.write_text("x", encoding="utf-8")
    os.chmod(locked, stat.S_IREAD)

    assert restore_snapshot(force=True)["restored"] is True
    assert not (target / new_sid).exists()


def test_plan_lists_each_entry_under_the_right_heading(tmp_path, monkeypatch, capsys):
    project, new_sid = _import_into(tmp_path, monkeypatch)
    target = get_projects_dir(project)
    (target / "old.jsonl").write_text('{"sessionId": "old"}\n{"later": 1}\n', encoding="utf-8")

    restore_snapshot(force=True)

    out = capsys.readouterr().out
    deleted = out.split("will be deleted")[1].split("\n\n")[0]
    rolled = out.split("will be rolled back")[1].split("\n\n")[0]
    assert f"{new_sid}.jsonl" in deleted and "old.jsonl" not in deleted
    assert "old.jsonl" in rolled and f"{new_sid}.jsonl" not in rolled
    assert "turns added to sessions that existed before" in out


def test_a_stale_snapshot_warning_survives_quiet(tmp_path, monkeypatch, capsys):
    from ccsession.output import QUIET, NORMAL, set_verbosity
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    _snapshot(tmp_path, target_directory=str(tmp_path / ".claude" / "projects" / "-p"), timestamp="2020-01-01T00:00:00Z")
    set_verbosity(QUIET)
    try:
        restore_snapshot(force=True)
    finally:
        set_verbosity(NORMAL)
    assert "days old" in capsys.readouterr().err


def test_info_mode_flags_a_stale_or_damaged_snapshot(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    _snapshot(tmp_path, target_directory=str(tmp_path / ".claude" / "projects" / "-p"),
              timestamp="2020-01-01T00:00:00Z", backup_exists=True)

    assert show_info() == 0

    captured = capsys.readouterr()
    assert "days old" in captured.err and "damaged" in captured.err


def test_index_entries_of_odd_shape_are_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    storage = tmp_path / ".claude-session-imports"
    storage.mkdir()
    (storage / "index.json").write_text(json.dumps({"imports": {
        "a": "x", "b": {"session_name": "naive", "imported_at": "2026-10-14T13:00:00"},
        "c": {"session_name": "aware", "imported_at": "2026-10-14T12:00:00Z"}}}), encoding="utf-8")

    assert get_last_import_info()["session_name"] == "naive"
