import sys
import json
from pathlib import Path
import subprocess
from unittest.mock import patch
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ccsession.paths import get_normalized_project_dir, get_projects_dir
from ccsession.importing.validation import validate_manifest, check_version_compatibility
from ccsession.importing.importer import import_session
from ccsession.importing.uuids import generate_new_session_id, generate_new_agent_id
from ccsession.importing.session_io import read_session_jsonl, write_session_file


# =============================================================================
# Manifest Validation Tests
# =============================================================================

def test_validate_manifest_missing(tmp_path):
    """Should raise ImportError when manifest is missing."""
    export_dir = tmp_path / "export"
    export_dir.mkdir()

    with pytest.raises(ImportError) as excinfo:
        validate_manifest(export_dir)

    assert "No .ccsession-manifest.json found" in str(excinfo.value)


def test_validate_manifest_invalid_json(tmp_path):
    """Should raise ImportError when manifest is invalid JSON."""
    export_dir = tmp_path / "export"
    export_dir.mkdir()

    manifest_path = export_dir / ".ccsession-manifest.json"
    manifest_path.write_text("not valid json {", encoding="utf-8")

    with pytest.raises(ImportError) as excinfo:
        validate_manifest(export_dir)

    assert "Invalid manifest JSON" in str(excinfo.value)


def test_validate_manifest_missing_fields(tmp_path):
    """Should raise ImportError when required fields are missing."""
    export_dir = tmp_path / "export"
    export_dir.mkdir()

    manifest_path = export_dir / ".ccsession-manifest.json"
    manifest_path.write_text(json.dumps({"ccsession_version": "2.0.0"}), encoding="utf-8")

    with pytest.raises(ImportError) as excinfo:
        validate_manifest(export_dir)

    assert "Missing required fields" in str(excinfo.value)


def test_validate_manifest_valid(tmp_path):
    """Should return manifest dict when valid."""
    export_dir = tmp_path / "export"
    export_dir.mkdir()

    manifest = {
        "ccsession_version": "2.0.0",
        "session_id": "test-session-id",
        "session_data": {"main_session": "session/main.jsonl"}
    }

    manifest_path = export_dir / ".ccsession-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = validate_manifest(export_dir)

    # 2.0.0 exports carry no layout_version; validation records the default
    assert result == {**manifest, "layout_version": 1}


# =============================================================================
# Path Normalization Tests
# =============================================================================

def test_get_normalized_project_dir_unix():
    """Should normalize Unix paths correctly."""
    # Unix path: /mnt/c/python/ccsession -> -mnt-c-python-ccsession
    result = get_normalized_project_dir("/mnt/c/python/ccsession")

    # On Unix, should have - prefix
    import os
    if os.name != 'nt':
        assert result == "-mnt-c-python-ccsession"


def test_get_normalized_project_dir_underscore():
    """Should convert underscores to hyphens."""
    result = get_normalized_project_dir("/mnt/c/python/ccsession_test")

    import os
    if os.name != 'nt':
        assert result == "-mnt-c-python-ccsession-test"


def test_get_normalized_project_dir_dots():
    """Should convert dots to hyphens."""
    result = get_normalized_project_dir("/mnt/c/my.project")

    import os
    if os.name != 'nt':
        assert result == "-mnt-c-my-project"


def test_get_projects_dir(tmp_path, monkeypatch):
    """Should return correct target directory path."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    result = get_projects_dir(Path("/mnt/c/python/myproject"))

    import os
    if os.name != 'nt':
        expected = fake_home / ".claude" / "projects" / "-mnt-c-python-myproject"
        assert result == expected


# =============================================================================
# UUID Generation Tests
# =============================================================================

def test_generate_new_session_id():
    """Should generate valid UUID string."""
    result = generate_new_session_id()

    # Should be valid UUID format
    import uuid
    uuid.UUID(result)  # Raises ValueError if invalid
    assert len(result) == 36


def test_generate_new_agent_id():
    """Should generate 17-character hex string matching real Claude agent IDs."""
    result = generate_new_agent_id()

    assert len(result) == 17
    assert all(c in "0123456789abcdef" for c in result)


# =============================================================================
# Session File Read/Write Tests
# =============================================================================

def test_read_session_jsonl(tmp_path):
    """Should read JSONL file and return list of messages."""
    session_file = tmp_path / "session.jsonl"

    messages = [
        {"uuid": "msg-1", "type": "user"},
        {"uuid": "msg-2", "type": "assistant"},
    ]

    session_file.write_text(
        "\n".join(json.dumps(m) for m in messages),
        encoding="utf-8"
    )

    result = read_session_jsonl(session_file)

    assert result == messages


def test_read_session_jsonl_handles_blank_lines(tmp_path):
    """Should skip blank lines in JSONL file."""
    session_file = tmp_path / "session.jsonl"

    content = '{"uuid": "msg-1"}\n\n{"uuid": "msg-2"}\n'
    session_file.write_text(content, encoding="utf-8")

    result = read_session_jsonl(session_file)

    assert len(result) == 2


def test_write_session_file_creates_file(tmp_path):
    """Should write messages to JSONL file."""
    target_path = tmp_path / "sessions" / "new-session.jsonl"

    messages = [
        {"uuid": "msg-1", "type": "user"},
        {"uuid": "msg-2", "type": "assistant"},
    ]

    write_session_file(messages, target_path)

    assert target_path.exists()

    # Read back and verify
    with open(target_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    assert len(lines) == 2
    assert json.loads(lines[0]) == messages[0]


def test_write_session_file_refuses_overwrite(tmp_path):
    """Should raise FileExistsError if target exists."""
    target_path = tmp_path / "session.jsonl"
    target_path.write_text("{}\n", encoding="utf-8")

    messages = [{"uuid": "msg-1"}]

    with pytest.raises(FileExistsError):
        write_session_file(messages, target_path)


# =============================================================================
# Integration Tests
# =============================================================================

# =============================================================================
# Claude Code Version Check Tests
# =============================================================================

def _claude_version_output(stdout):
    """Stand in for running `claude --version`, which prints e.g. '2.1.287 (Claude Code)'."""
    completed = subprocess.CompletedProcess(args=["claude", "--version"], returncode=0,
                                            stdout=stdout, stderr="")
    return patch("ccsession.importing.validation.subprocess.run", return_value=completed)


def test_check_version_compatibility_same_version_gives_no_warning():
    with _claude_version_output("2.1.287 (Claude Code)\n"):
        _, warning = check_version_compatibility({"claude_code_version": "2.1.287"})

    assert warning is None


def test_check_version_compatibility_mismatch_names_both_versions():
    with _claude_version_output("2.1.287 (Claude Code)\n"):
        _, warning = check_version_compatibility({"claude_code_version": "2.0.14"})

    assert "2.0.14" in warning
    assert "2.1.287" in warning


def test_check_version_compatibility_unparseable_output_is_reported_as_unknown():
    with _claude_version_output("something unexpected\n"):
        _, warning = check_version_compatibility({"claude_code_version": "2.1.287"})

    assert "Could not determine" in warning


# =============================================================================
# Import Conflict Tests
# =============================================================================

def test_import_with_preserved_id_conflict_names_the_existing_file(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    project = (tmp_path / "project").resolve()
    project.mkdir()

    session_id = "deadbeef-0000-0000-0000-000000000000"
    export_dir = tmp_path / "export"
    export_dir.mkdir()
    (export_dir / ".ccsession-manifest.json").write_text(json.dumps({
        "ccsession_version": "2.0.0",
        "session_id": session_id,
        "session_data": {"main_session": "session/main.jsonl"},
    }), encoding="utf-8")
    existing = get_projects_dir(project) / f"{session_id}.jsonl"
    existing.parent.mkdir(parents=True)
    existing.write_text("{}\n", encoding="utf-8")

    with patch("ccsession.importing.importer.check_version_compatibility", return_value=(True, None)):
        with pytest.raises(FileExistsError) as excinfo:
            import_session(export_dir, project_path=project,
                           preserve_session_id=True, non_interactive=True)

    assert str(existing) in str(excinfo.value)


# =============================================================================
# Full import of a layout-2 export
# =============================================================================

def _export_with_agent(root, sid, agent_id, project):
    """A layout-2 export of a session with one sub-agent, shaped like ccsession 2.1 writes it."""
    mirror = root / "session" / "session-dir"
    (mirror / "subagents").mkdir(parents=True)
    main = [
        {"type": "last-prompt", "sessionId": sid, "lastPrompt": "fix it", "leafUuid": "u3"},
        {"type": "user", "uuid": "u1", "parentUuid": None, "sessionId": sid, "cwd": project, "version": "2.1.287",
         "message": {"role": "user", "content": "fix it"}},
        {"type": "assistant", "uuid": "u2", "parentUuid": "u1", "sessionId": sid, "cwd": project, "requestId": "req_01",
         "message": {"id": "msg_01", "role": "assistant", "content": [{"type": "tool_use", "id": "toolu_01", "name": "Agent", "input": {}}]}},
        {"type": "user", "uuid": "u3", "parentUuid": "u2", "sessionId": sid, "cwd": project, "sourceToolAssistantUUID": "u2",
         "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_01", "content": "ok"}]},
         "toolUseResult": {"agentId": agent_id, "status": "completed"}},
    ]
    (root / "session").mkdir(exist_ok=True)
    (root / "session" / "main.jsonl").write_text("".join(json.dumps(r) + "\n" for r in main), encoding="utf-8")
    (mirror / "subagents" / f"agent-{agent_id}.jsonl").write_text(json.dumps(
        {"type": "user", "uuid": "s1", "parentUuid": None, "agentId": agent_id, "sessionId": sid, "cwd": project,
         "message": {"role": "user", "content": "sub"}}) + "\n", encoding="utf-8")
    (mirror / "subagents" / f"agent-{agent_id}.meta.json").write_text(json.dumps({"agentType": "Explore", "toolUseId": "toolu_01"}), encoding="utf-8")
    (root / "session" / "history.jsonl").write_text(json.dumps(
        {"display": "fix it", "pastedContents": {}, "timestamp": 1, "project": project, "sessionId": sid}) + "\n", encoding="utf-8")
    (root / ".ccsession-manifest.json").write_text(json.dumps({
        "ccsession_version": "2.1.0", "layout_version": 2, "session_id": sid, "session_slug": None, "export_name": "t",
        "claude_code_version": "2.1.287", "original_context": {"user": "u", "platform": "darwin", "repo_path": project, "git_branch": "main"},
        "session_data": {"main_session": "session/main.jsonl", "agent_sessions": [f"session/session-dir/subagents/agent-{agent_id}.jsonl"],
                         "file_history": [], "plan_file": None, "todos": None, "session_env": None, "tool_results": [],
                         "session_dir": "session/session-dir/", "history": "session/history.jsonl",
                         "agent_meta": [f"session/session-dir/subagents/agent-{agent_id}.meta.json"]},
        "config_snapshot": {"commands": [], "skills": [], "hooks": [], "agents": [], "rules": [], "settings": None, "claude_md": None},
        "statistics": {"message_count": 4, "user_messages": 2, "assistant_messages": 1, "tool_uses": 1, "duration_seconds": None, "models_used": []},
    }), encoding="utf-8")


def test_import_restores_agents_history_and_rewrites_every_reference(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    sid, agent_id = "7f6738b0-d2cb-44ae-a806-09860af58e1f", "a9ba8b4d8b37efc78"
    export = tmp_path / "export"
    _export_with_agent(export, sid, agent_id, "/old/proj")
    project = (tmp_path / "newproj").resolve()
    project.mkdir()

    with patch("ccsession.importing.importer.check_version_compatibility", return_value=(True, None)):
        summary = import_session(export, project_path=project, non_interactive=True)

    new_sid = summary["session_id"]
    assert new_sid != sid
    main = [json.loads(l) for l in Path(summary["session_file"]).read_text(encoding="utf-8").splitlines()]
    by_type = {r["type"]: r for r in main}
    uuids = {r["uuid"] for r in main if "uuid" in r}
    assert by_type["last-prompt"]["leafUuid"] in uuids and by_type["last-prompt"]["leafUuid"] != "u3"
    user_result = [r for r in main if r.get("toolUseResult")][0]
    assert user_result["sourceToolAssistantUUID"] in uuids
    assert all(r["sessionId"] == new_sid for r in main) and all(r.get("cwd", str(project)) == str(project) for r in main)
    new_agent = user_result["toolUseResult"]["agentId"]
    assert new_agent != agent_id
    session_dir = get_projects_dir(project) / new_sid
    assert (session_dir / "subagents" / f"agent-{new_agent}.jsonl").is_file()
    assert (session_dir / "subagents" / f"agent-{new_agent}.meta.json").is_file()
    assert summary["agent_sessions"] == 1 and summary["session_dir_files"] == 2 and summary["history_lines"] == 1
    history = [json.loads(l) for l in (tmp_path / ".claude" / "history.jsonl").read_text(encoding="utf-8").splitlines()]
    assert history[0]["sessionId"] == new_sid and history[0]["project"] == str(project)


def test_import_prints_a_resume_hint_with_the_new_id(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    export = tmp_path / "export"
    _export_with_agent(export, "7f6738b0-d2cb-44ae-a806-09860af58e1f", "a9ba8b4d8b37efc78", "/old/proj")
    project = (tmp_path / "newproj").resolve()
    project.mkdir()
    with patch("ccsession.importing.importer.check_version_compatibility", return_value=(True, None)):
        summary = import_session(export, project_path=project, non_interactive=True)
    out = capsys.readouterr().out
    assert f"claude --resume {summary['session_id']}" in out
    assert "Session: None" not in out
