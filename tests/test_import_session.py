import sys
import json
from pathlib import Path
import subprocess
from unittest.mock import patch
import pytest

from ccsession.errors import InvalidExportError

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
    """Should raise InvalidExportError when manifest is missing."""
    export_dir = tmp_path / "export"
    export_dir.mkdir()

    with pytest.raises(InvalidExportError) as excinfo:
        validate_manifest(export_dir)

    assert "No .ccsession-manifest.json found" in str(excinfo.value)


def test_validate_manifest_invalid_json(tmp_path):
    """Should raise InvalidExportError when manifest is invalid JSON."""
    export_dir = tmp_path / "export"
    export_dir.mkdir()

    manifest_path = export_dir / ".ccsession-manifest.json"
    manifest_path.write_text("not valid json {", encoding="utf-8")

    with pytest.raises(InvalidExportError) as excinfo:
        validate_manifest(export_dir)

    assert "Invalid manifest JSON" in str(excinfo.value)


def test_validate_manifest_missing_fields(tmp_path):
    """Should raise InvalidExportError when required fields are missing."""
    export_dir = tmp_path / "export"
    export_dir.mkdir()

    manifest_path = export_dir / ".ccsession-manifest.json"
    manifest_path.write_text(json.dumps({"ccsession_version": "2.0.0"}), encoding="utf-8")

    with pytest.raises(InvalidExportError) as excinfo:
        validate_manifest(export_dir)

    assert "Missing required fields" in str(excinfo.value)


def test_validate_manifest_valid(tmp_path):
    """Should return manifest dict when valid."""
    export_dir = tmp_path / "export"
    export_dir.mkdir()

    manifest = {
        "ccsession_version": "2.1.0",
        "layout_version": 2,
        "session_id": "test-session-id",
        "session_data": {"main_session": "session/main.jsonl"}
    }

    manifest_path = export_dir / ".ccsession-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = validate_manifest(export_dir)

    assert result == manifest


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
    which = patch("ccsession.importing.validation.shutil.which", return_value="/usr/bin/claude")
    run = patch("ccsession.importing.validation.subprocess.run", return_value=completed)

    class _Both:
        def __enter__(self):
            which.__enter__()
            return run.__enter__()

        def __exit__(self, *exc):
            run.__exit__(*exc)
            which.__exit__(*exc)

    return _Both()


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
        "ccsession_version": "2.0.0", "layout_version": 2,
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
                         "file_history": [], "session_env": None,
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
    # Agent ids are deliberately stable: Claude Code matches them against task-id tags in message text
    assert user_result["toolUseResult"]["agentId"] == agent_id
    session_dir = get_projects_dir(project) / new_sid
    assert (session_dir / "subagents" / f"agent-{agent_id}.jsonl").is_file()
    assert (session_dir / "subagents" / f"agent-{agent_id}.meta.json").is_file()
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


def test_preserved_import_into_a_populated_session_dir_aborts_before_touching_the_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    sid, agent_id = "7f6738b0-d2cb-44ae-a806-09860af58e1f", "a9ba8b4d8b37efc78"
    export = tmp_path / "export"
    _export_with_agent(export, sid, agent_id, "/old/proj")
    project = (tmp_path / "newproj").resolve()
    project.mkdir()
    populated = get_projects_dir(project) / sid / "subagents"
    populated.mkdir(parents=True)
    (populated / "agent-x.jsonl").write_text("{}\n", encoding="utf-8")
    previous_snapshot = tmp_path / ".claude-session-imports" / "pre-import-snapshot"
    previous_snapshot.mkdir(parents=True)
    (previous_snapshot / "snapshot_info.json").write_text('{"timestamp": "2026-01-01T00:00:00Z"}', encoding="utf-8")

    with patch("ccsession.importing.importer.check_version_compatibility", return_value=(True, None)):
        with pytest.raises(FileExistsError, match="already exists"):
            import_session(export, project_path=project, preserve_session_id=True, non_interactive=True)

    assert (previous_snapshot / "snapshot_info.json").read_text(encoding="utf-8").startswith('{"timestamp": "2026-01-01')
    assert not (get_projects_dir(project) / f"{sid}.jsonl").exists()


def test_import_refuses_a_main_session_path_outside_the_export(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    export = tmp_path / "export"
    _export_with_agent(export, "7f6738b0-d2cb-44ae-a806-09860af58e1f", "a9ba8b4d8b37efc78", "/old/proj")
    manifest = json.loads((export / ".ccsession-manifest.json").read_text(encoding="utf-8"))
    manifest["session_data"]["main_session"] = "../outside.jsonl"
    (export / ".ccsession-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (tmp_path / "outside.jsonl").write_text("{}\n", encoding="utf-8")
    project = (tmp_path / "newproj").resolve()
    project.mkdir()
    with patch("ccsession.importing.importer.check_version_compatibility", return_value=(True, None)):
        with pytest.raises(InvalidExportError, match="outside the export"):
            import_session(export, project_path=project, non_interactive=True)


def test_import_with_skip_config_leaves_claude_md_alone(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    export = tmp_path / "export"
    _export_with_agent(export, "7f6738b0-d2cb-44ae-a806-09860af58e1f", "a9ba8b4d8b37efc78", "/old/proj")
    project = (tmp_path / "newproj").resolve()
    project.mkdir()
    (project / "CLAUDE.md").write_text("# mine\n", encoding="utf-8")

    with patch("ccsession.importing.importer.check_version_compatibility", return_value=(True, None)):
        import_session(export, project_path=project, non_interactive=True, skip_config=True)

    assert (project / "CLAUDE.md").read_text(encoding="utf-8") == "# mine\n"


def test_importing_the_same_export_twice_adds_one_claude_md_note(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    export = tmp_path / "export"
    _export_with_agent(export, "7f6738b0-d2cb-44ae-a806-09860af58e1f", "a9ba8b4d8b37efc78", "/old/proj")
    project = (tmp_path / "newproj").resolve()
    project.mkdir()

    with patch("ccsession.importing.importer.check_version_compatibility", return_value=(True, None)):
        import_session(export, project_path=project, non_interactive=True)
        import_session(export, project_path=project, non_interactive=True)

    assert (project / "CLAUDE.md").read_text(encoding="utf-8").count("## Imported Session Context") == 1


# =============================================================================
# Failure before any write must not disturb the previous snapshot
# =============================================================================

def _previous_snapshot(tmp_path):
    previous = tmp_path / ".claude-session-imports" / "pre-import-snapshot"
    previous.mkdir(parents=True)
    (previous / "snapshot_info.json").write_text('{"timestamp": "2026-01-01T00:00:00Z"}', encoding="utf-8")
    return previous


def test_a_missing_transcript_is_detected_before_the_snapshot_is_replaced(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    export = tmp_path / "export"
    _export_with_agent(export, "7f6738b0-d2cb-44ae-a806-09860af58e1f", "a9ba8b4d8b37efc78", "/old/proj")
    (export / "session" / "main.jsonl").unlink()
    project = (tmp_path / "newproj").resolve()
    project.mkdir()
    previous = _previous_snapshot(tmp_path)

    with patch("ccsession.importing.importer.check_version_compatibility", return_value=(True, None)):
        with pytest.raises(FileNotFoundError):
            import_session(export, project_path=project, non_interactive=True)

    assert (previous / "snapshot_info.json").read_text(encoding="utf-8").startswith('{"timestamp": "2026-01-01')


def test_a_bad_config_path_is_detected_before_the_snapshot_is_replaced(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    export = tmp_path / "export"
    _export_with_agent(export, "7f6738b0-d2cb-44ae-a806-09860af58e1f", "a9ba8b4d8b37efc78", "/old/proj")
    manifest = json.loads((export / ".ccsession-manifest.json").read_text(encoding="utf-8"))
    manifest["config_snapshot"]["commands"] = ["../outside.md"]
    manifest["session_data"]["file_history"] = ["/etc/hosts"]
    (export / ".ccsession-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    project = (tmp_path / "newproj").resolve()
    project.mkdir()
    previous = _previous_snapshot(tmp_path)

    with patch("ccsession.importing.importer.check_version_compatibility", return_value=(True, None)):
        with pytest.raises(InvalidExportError):
            import_session(export, project_path=project, non_interactive=True)

    assert (previous / "snapshot_info.json").read_text(encoding="utf-8").startswith('{"timestamp": "2026-01-01')
    assert not (get_projects_dir(project)).exists()


def test_import_records_what_it_created_in_the_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    export = tmp_path / "export"
    _export_with_agent(export, "7f6738b0-d2cb-44ae-a806-09860af58e1f", "a9ba8b4d8b37efc78", "/old/proj")
    (export / "config" / "commands").mkdir(parents=True)
    (export / "config" / "commands" / "review.md").write_text("r", encoding="utf-8")
    manifest = json.loads((export / ".ccsession-manifest.json").read_text(encoding="utf-8"))
    manifest["config_snapshot"]["commands"] = ["config/commands/review.md"]
    (export / ".ccsession-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    project = (tmp_path / "newproj").resolve()
    project.mkdir()

    with patch("ccsession.importing.importer.check_version_compatibility", return_value=(True, None)):
        summary = import_session(export, project_path=project, non_interactive=True)

    info = json.loads((tmp_path / ".claude-session-imports" / "pre-import-snapshot" / "snapshot_info.json").read_text(encoding="utf-8"))
    assert info["new_session_id"] == summary["session_id"]
    assert info["created_config_files"] == [str(project / ".claude" / "commands" / "review.md")]
    assert "## Imported Session Context" in info["claude_md_note"]


# =============================================================================
# Claude Code version probe
# =============================================================================

def test_version_probe_resolves_the_executable_and_bounds_the_wait():
    """A bare 'claude' misses npm's claude.cmd shim on Windows, and a hung child must not hang the import."""
    completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="2.1.287 (Claude Code)\n", stderr="")
    with patch("ccsession.importing.validation.shutil.which", return_value="/opt/bin/claude.cmd"):
        with patch("ccsession.importing.validation.subprocess.run", return_value=completed) as run:
            _, warning = check_version_compatibility({"claude_code_version": "2.1.287"})

    assert warning is None
    args, kwargs = run.call_args
    assert args[0] == ["/opt/bin/claude.cmd", "--version"]
    assert kwargs.get("timeout") and kwargs["timeout"] > 0
    assert kwargs.get("stdin") == subprocess.DEVNULL


def test_version_probe_without_claude_on_path_runs_nothing():
    with patch("ccsession.importing.validation.shutil.which", return_value=None):
        with patch("ccsession.importing.validation.subprocess.run", side_effect=AssertionError("must not run")):
            _, warning = check_version_compatibility({"claude_code_version": "2.1.287"})

    assert "Could not determine" in warning


def test_version_probe_timeout_is_reported_as_unknown():
    with patch("ccsession.importing.validation.shutil.which", return_value="/usr/bin/claude"):
        with patch("ccsession.importing.validation.subprocess.run",
                   side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=5)):
            _, warning = check_version_compatibility({"claude_code_version": "2.1.287"})

    assert "Could not determine" in warning


def test_eof_on_the_version_prompt_aborts_the_import_cleanly(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    export = tmp_path / "export"
    _export_with_agent(export, "7f6738b0-d2cb-44ae-a806-09860af58e1f", "a9ba8b4d8b37efc78", "/old/proj")
    project = (tmp_path / "newproj").resolve()
    project.mkdir()

    def no_stdin(_prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", no_stdin)
    with patch("ccsession.importing.importer.check_version_compatibility", return_value=(True, "Version mismatch")):
        assert import_session(export, project_path=project, non_interactive=False) is None

    assert not get_projects_dir(project).exists()


# =============================================================================
# Second review round
# =============================================================================

def test_a_corrupt_sidecar_is_detected_before_the_snapshot_is_replaced(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    export = tmp_path / "export"
    _export_with_agent(export, "7f6738b0-d2cb-44ae-a806-09860af58e1f", "a9ba8b4d8b37efc78", "/old/proj")
    (export / "session" / "session-dir" / "subagents" / "agent-a9ba8b4d8b37efc78.meta.json").write_text("{not json", encoding="utf-8")
    project = (tmp_path / "newproj").resolve()
    project.mkdir()
    previous = _previous_snapshot(tmp_path)

    with patch("ccsession.importing.importer.check_version_compatibility", return_value=(True, None)):
        with pytest.raises(InvalidExportError, match="sidecar|not valid JSON"):
            import_session(export, project_path=project, non_interactive=True)

    assert (previous / "snapshot_info.json").read_text(encoding="utf-8").startswith('{"timestamp": "2026-01-01')
    assert not get_projects_dir(project).exists()


def test_a_partial_failure_still_records_the_config_files_it_created(tmp_path, monkeypatch):
    """`ccsession restore --restore` must be able to remove what a failed import left behind."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    export = tmp_path / "export"
    _export_with_agent(export, "7f6738b0-d2cb-44ae-a806-09860af58e1f", "a9ba8b4d8b37efc78", "/old/proj")
    (export / "config" / "commands").mkdir(parents=True)
    (export / "config" / "commands" / "review.md").write_text("r", encoding="utf-8")
    manifest = json.loads((export / ".ccsession-manifest.json").read_text(encoding="utf-8"))
    manifest["config_snapshot"]["commands"] = ["config/commands/review.md"]
    (export / ".ccsession-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    project = (tmp_path / "newproj").resolve()
    project.mkdir()

    with patch("ccsession.importing.importer.check_version_compatibility", return_value=(True, None)):
        with patch("ccsession.importing.importer.add_claude_md_note", side_effect=OSError("disk full")):
            with pytest.raises(OSError):
                import_session(export, project_path=project, non_interactive=True)

    info = json.loads((tmp_path / ".claude-session-imports" / "pre-import-snapshot" / "snapshot_info.json").read_text(encoding="utf-8"))
    assert info["created_config_files"] == [str(project / ".claude" / "commands" / "review.md")]
    assert info["appended_history_lines"], "history lines written before the failure are recorded too"


def test_a_claude_md_that_is_not_utf8_does_not_abort_the_import(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    export = tmp_path / "export"
    _export_with_agent(export, "7f6738b0-d2cb-44ae-a806-09860af58e1f", "a9ba8b4d8b37efc78", "/old/proj")
    project = (tmp_path / "newproj").resolve()
    project.mkdir()
    (project / "CLAUDE.md").write_bytes(b"# caf\xe9\n")

    with patch("ccsession.importing.importer.check_version_compatibility", return_value=(True, None)):
        summary = import_session(export, project_path=project, non_interactive=True)

    assert summary is not None
    data = (project / "CLAUDE.md").read_bytes()
    assert data.startswith(b"# caf\xe9\n") and b"## Imported Session Context" in data


def test_quiet_import_still_warns_about_skipped_config_files(tmp_path, monkeypatch, capsys):
    from ccsession.output import QUIET, NORMAL, set_verbosity
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    export = tmp_path / "export"
    _export_with_agent(export, "7f6738b0-d2cb-44ae-a806-09860af58e1f", "a9ba8b4d8b37efc78", "/old/proj")
    (export / "config" / "commands").mkdir(parents=True)
    (export / "config" / "commands" / "review.md").write_text("theirs", encoding="utf-8")
    manifest = json.loads((export / ".ccsession-manifest.json").read_text(encoding="utf-8"))
    manifest["config_snapshot"]["commands"] = ["config/commands/review.md"]
    (export / ".ccsession-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    project = (tmp_path / "newproj").resolve()
    (project / ".claude" / "commands").mkdir(parents=True)
    (project / ".claude" / "commands" / "review.md").write_text("mine", encoding="utf-8")

    set_verbosity(QUIET)
    try:
        with patch("ccsession.importing.importer.check_version_compatibility", return_value=(True, None)):
            import_session(export, project_path=project, non_interactive=True)
    finally:
        set_verbosity(NORMAL)

    assert "Skipped 1" in capsys.readouterr().err


def test_version_probe_ignores_an_executable_found_in_the_current_directory_on_windows(tmp_path, monkeypatch):
    """shutil.which searches the cwd first on Windows; an export or project could ship a claude.cmd."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("ccsession.importing.validation.sys.platform", "win32")
    with patch("ccsession.importing.validation.shutil.which", return_value=str(tmp_path / "claude.cmd")):
        with patch("ccsession.importing.validation.subprocess.run", side_effect=AssertionError("must not run")):
            _, warning = check_version_compatibility({"claude_code_version": "2.1.287"})

    assert "Could not determine" in warning


def test_a_closed_stdin_on_the_version_prompt_aborts_the_import_cleanly(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    export = tmp_path / "export"
    _export_with_agent(export, "7f6738b0-d2cb-44ae-a806-09860af58e1f", "a9ba8b4d8b37efc78", "/old/proj")
    project = (tmp_path / "newproj").resolve()
    project.mkdir()
    monkeypatch.setattr("sys.stdin", None)

    with patch("ccsession.importing.importer.check_version_compatibility", return_value=(True, "Version mismatch")):
        assert import_session(export, project_path=project, non_interactive=False) is None

    assert not get_projects_dir(project).exists()


# =============================================================================
# Third review round
# =============================================================================

def _rewrite_manifest(export, mutate):
    manifest = json.loads((export / ".ccsession-manifest.json").read_text(encoding="utf-8"))
    mutate(manifest)
    (export / ".ccsession-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


@pytest.mark.parametrize("bad_id", ["../nonexistent/../../home/.ssh", ".", "not-a-uuid", "7F6738B0-D2CB-44AE-A806-09860AF58E1F"])
def test_a_preserved_session_id_must_be_a_canonical_uuid(tmp_path, monkeypatch, bad_id):
    """With --preserve-session-id the id becomes a path component of every file written."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    export = tmp_path / "export"
    _export_with_agent(export, "7f6738b0-d2cb-44ae-a806-09860af58e1f", "a9ba8b4d8b37efc78", "/old/proj")
    _rewrite_manifest(export, lambda m: m.update(session_id=bad_id))
    project = (tmp_path / "newproj").resolve()
    project.mkdir()
    previous = _previous_snapshot(tmp_path)

    with patch("ccsession.importing.importer.check_version_compatibility", return_value=(True, None)):
        with pytest.raises(InvalidExportError, match="session id"):
            import_session(export, project_path=project, preserve_session_id=True, non_interactive=True)

    assert (previous / "snapshot_info.json").read_text(encoding="utf-8").startswith('{"timestamp": "2026-01-01')
    assert not (tmp_path / ".claude").exists()


def test_a_lone_surrogate_in_the_transcript_round_trips(tmp_path, monkeypatch):
    """JSON.stringify writes a string cut in the middle of an emoji as a \\ud83d escape."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    export = tmp_path / "export"
    _export_with_agent(export, "7f6738b0-d2cb-44ae-a806-09860af58e1f", "a9ba8b4d8b37efc78", "/old/proj")
    main = export / "session" / "main.jsonl"
    main.write_text(main.read_text(encoding="utf-8").replace('"content": "fix it"', '"content": "cut \\ud83d here"'),
                    encoding="utf-8")
    hist = export / "session" / "history.jsonl"
    hist.write_text(hist.read_text(encoding="utf-8").replace('"display": "fix it"', '"display": "cut \\ud83d"'),
                    encoding="utf-8")
    project = (tmp_path / "newproj").resolve()
    project.mkdir()

    with patch("ccsession.importing.importer.check_version_compatibility", return_value=(True, None)):
        summary = import_session(export, project_path=project, non_interactive=True)

    raw = Path(summary["session_file"]).read_bytes()
    raw.decode("utf-8")  # valid UTF-8 on disk
    records = [json.loads(l) for l in raw.decode("utf-8").splitlines()]
    assert any(r.get("message", {}).get("content") == "cut \ud83d here" for r in records)
    history = (tmp_path / ".claude" / "history.jsonl").read_bytes().decode("utf-8")
    assert json.loads(history.splitlines()[-1])["display"] == "cut \ud83d"


def test_an_export_history_that_is_not_utf8_is_refused_before_the_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    export = tmp_path / "export"
    _export_with_agent(export, "7f6738b0-d2cb-44ae-a806-09860af58e1f", "a9ba8b4d8b37efc78", "/old/proj")
    (export / "session" / "history.jsonl").write_bytes(b'{"display": "caf\xe9", "timestamp": 1}\n')
    project = (tmp_path / "newproj").resolve()
    project.mkdir()
    previous = _previous_snapshot(tmp_path)

    with patch("ccsession.importing.importer.check_version_compatibility", return_value=(True, None)):
        with pytest.raises(InvalidExportError, match="history"):
            import_session(export, project_path=project, non_interactive=True)

    assert (previous / "snapshot_info.json").read_text(encoding="utf-8").startswith('{"timestamp": "2026-01-01')


def test_non_object_lines_are_ignored_in_both_histories(tmp_path, monkeypatch):
    """Claude Code tolerates such lines (history_load_shape_rejected), so ccsession must too."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    export = tmp_path / "export"
    _export_with_agent(export, "7f6738b0-d2cb-44ae-a806-09860af58e1f", "a9ba8b4d8b37efc78", "/old/proj")
    with open(export / "session" / "history.jsonl", "a", encoding="utf-8") as f:
        f.write("[1, 2]\nnull\n")
    user_history = tmp_path / ".claude" / "history.jsonl"
    user_history.parent.mkdir(parents=True)
    user_history.write_text('null\n"text"\n{"display": "mine", "timestamp": 0, "sessionId": "other"}', encoding="utf-8")
    project = (tmp_path / "newproj").resolve()
    project.mkdir()

    with patch("ccsession.importing.importer.check_version_compatibility", return_value=(True, None)):
        summary = import_session(export, project_path=project, non_interactive=True)

    assert summary["history_lines"] == 1
    lines = user_history.read_text(encoding="utf-8").splitlines()
    assert lines[2] == '{"display": "mine", "timestamp": 0, "sessionId": "other"}', "an unterminated last line is not merged"
    assert json.loads(lines[3])["display"] == "fix it"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_a_history_file_created_by_the_import_is_private(tmp_path, monkeypatch):
    """Claude Code creates history.jsonl with mode 0600; prompts can hold pasted secrets."""
    import stat
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    export = tmp_path / "export"
    _export_with_agent(export, "7f6738b0-d2cb-44ae-a806-09860af58e1f", "a9ba8b4d8b37efc78", "/old/proj")
    project = (tmp_path / "newproj").resolve()
    project.mkdir()

    with patch("ccsession.importing.importer.check_version_compatibility", return_value=(True, None)):
        import_session(export, project_path=project, non_interactive=True)

    assert stat.S_IMODE((tmp_path / ".claude" / "history.jsonl").stat().st_mode) == 0o600


@pytest.mark.skipif(sys.platform == "win32", reason="undecodable bytes in paths are a POSIX filesystem concept")
def test_a_project_path_with_undecodable_bytes_is_recorded_as_claude_code_would(tmp_path, monkeypatch):
    """Node turns undecodable bytes into U+FFFD; the imported records must match what
    Claude Code writes for that cwd, and writing them must not fail."""
    import os
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    export = tmp_path / "export"
    _export_with_agent(export, "7f6738b0-d2cb-44ae-a806-09860af58e1f", "a9ba8b4d8b37efc78", "/old/proj")
    raw = os.fsencode(str(tmp_path)) + b"/proj-\xff"
    try:
        os.mkdir(raw)
    except OSError:
        pytest.skip("this filesystem rejects names that are not valid UTF-8 (APFS)")
    project = Path(os.fsdecode(raw))

    with patch("ccsession.importing.importer.check_version_compatibility", return_value=(True, None)):
        summary = import_session(export, project_path=project, non_interactive=True, skip_config=True)

    records = [json.loads(l) for l in Path(summary["session_file"]).read_text(encoding="utf-8").splitlines()]
    assert {r["cwd"] for r in records if "cwd" in r} == {str(tmp_path) + "/proj-�"}


def test_an_export_from_an_undecodable_directory_can_be_imported_with_config(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    export = tmp_path / "export"
    _export_with_agent(export, "7f6738b0-d2cb-44ae-a806-09860af58e1f", "a9ba8b4d8b37efc78", "/old/proj")
    _rewrite_manifest(export, lambda m: m["original_context"].update(repo_path="/tmp/w/proj-\udcff"))
    project = (tmp_path / "newproj").resolve()
    project.mkdir()

    with patch("ccsession.importing.importer.check_version_compatibility", return_value=(True, None)):
        import_session(export, project_path=project, non_interactive=True)

    assert "## Imported Session Context" in (project / "CLAUDE.md").read_text(encoding="utf-8")


def test_a_failure_part_way_through_the_config_copy_still_records_what_was_written(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    export = tmp_path / "export"
    _export_with_agent(export, "7f6738b0-d2cb-44ae-a806-09860af58e1f", "a9ba8b4d8b37efc78", "/old/proj")
    for name in ("a.md", "b.md"):
        (export / "config" / "commands").mkdir(parents=True, exist_ok=True)
        (export / "config" / "commands" / name).write_text(name, encoding="utf-8")
    _rewrite_manifest(export, lambda m: m["config_snapshot"].update(commands=["config/commands/a.md", "config/commands/b.md"]))
    project = (tmp_path / "newproj").resolve()
    project.mkdir()
    from ccsession.utils import copy_file_writable as real_copy
    calls = []

    def copy_then_fail(src, dst):
        calls.append(dst)
        if len(calls) == 2:
            raise OSError("No space left on device")
        return real_copy(src, dst)

    with patch("ccsession.importing.importer.check_version_compatibility", return_value=(True, None)):
        with patch("ccsession.importing.config.copy_file_writable", side_effect=copy_then_fail):
            with pytest.raises(OSError):
                import_session(export, project_path=project, non_interactive=True)

    info = json.loads((tmp_path / ".claude-session-imports" / "pre-import-snapshot" / "snapshot_info.json").read_text(encoding="utf-8"))
    assert str(project / ".claude" / "commands" / "a.md") in info["created_config_files"]
    assert str(project / ".claude") in info["created_config_dirs"]


def test_a_failure_part_way_through_the_history_append_still_records_what_was_written(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    export = tmp_path / "export"
    _export_with_agent(export, "7f6738b0-d2cb-44ae-a806-09860af58e1f", "a9ba8b4d8b37efc78", "/old/proj")
    with open(export / "session" / "history.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"display": "second", "timestamp": 2, "project": "/old/proj",
                            "sessionId": "7f6738b0-d2cb-44ae-a806-09860af58e1f"}) + "\n")
    project = (tmp_path / "newproj").resolve()
    project.mkdir()
    from ccsession.importing import session_dir
    real = session_dir.json_line
    calls = []

    def fail_second(record):
        if "display" in record:  # prompt-history records only; transcripts use the same helper
            calls.append(record)
            if len(calls) == 2:
                raise OSError("No space left on device")
        return real(record)

    with patch("ccsession.importing.importer.check_version_compatibility", return_value=(True, None)):
        with patch("ccsession.importing.session_dir.json_line", side_effect=fail_second):
            with pytest.raises(OSError):
                import_session(export, project_path=project, non_interactive=True)

    info = json.loads((tmp_path / ".claude-session-imports" / "pre-import-snapshot" / "snapshot_info.json").read_text(encoding="utf-8"))
    assert len(info["appended_history_lines"]) == 1 and '"fix it"' in info["appended_history_lines"][0]


def test_a_failed_snapshot_leaves_the_previous_one_in_place(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    export = tmp_path / "export"
    _export_with_agent(export, "7f6738b0-d2cb-44ae-a806-09860af58e1f", "a9ba8b4d8b37efc78", "/old/proj")
    project = (tmp_path / "newproj").resolve()
    project.mkdir()
    get_projects_dir(project).mkdir(parents=True)
    (get_projects_dir(project) / "old.jsonl").write_text("{}\n", encoding="utf-8")
    previous = _previous_snapshot(tmp_path)

    with patch("ccsession.importing.importer.check_version_compatibility", return_value=(True, None)):
        with patch("ccsession.importing.snapshot.shutil.copytree", side_effect=OSError("No space left on device")):
            with pytest.raises(OSError):
                import_session(export, project_path=project, non_interactive=True)

    assert (previous / "snapshot_info.json").read_text(encoding="utf-8").startswith('{"timestamp": "2026-01-01')
    assert not list((tmp_path / ".claude-session-imports").glob("*.tmp*"))
    assert not (get_projects_dir(project) / "7f6738b0-d2cb-44ae-a806-09860af58e1f.jsonl").exists()


def test_import_says_that_settings_json_is_not_restored(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    export = tmp_path / "export"
    _export_with_agent(export, "7f6738b0-d2cb-44ae-a806-09860af58e1f", "a9ba8b4d8b37efc78", "/old/proj")
    (export / "config").mkdir(exist_ok=True)
    (export / "config" / "settings.json").write_text('{"hooks": {}}', encoding="utf-8")
    _rewrite_manifest(export, lambda m: m["config_snapshot"].update(settings="config/settings.json"))
    project = (tmp_path / "newproj").resolve()
    project.mkdir()

    with patch("ccsession.importing.importer.check_version_compatibility", return_value=(True, None)):
        import_session(export, project_path=project, non_interactive=True)

    assert "settings.json" in capsys.readouterr().out
    assert not (project / ".claude" / "settings.json").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_version_probe_ignores_a_symlinked_executable_in_the_current_directory_on_windows(tmp_path, monkeypatch):
    import os
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "payload.cmd").write_text("echo", encoding="utf-8")
    os.symlink(tmp_path / "sub" / "payload.cmd", tmp_path / "claude.cmd")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("ccsession.importing.validation.sys.platform", "win32")
    with patch("ccsession.importing.validation.shutil.which", return_value=os.path.join(os.curdir, "claude.cmd")):
        with patch("ccsession.importing.validation.subprocess.run", side_effect=AssertionError("must not run")):
            _, warning = check_version_compatibility({"claude_code_version": "2.1.287"})

    assert "Could not determine" in warning


# =============================================================================
# Fourth review round
# =============================================================================

def _snapshot_dir(tmp_path):
    return tmp_path / ".claude-session-imports" / "pre-import-snapshot"


def _with_commands(export, *names):
    (export / "config" / "commands").mkdir(parents=True, exist_ok=True)
    for name in names:
        (export / "config" / "commands" / name).write_text(name, encoding="utf-8")
    _rewrite_manifest(export, lambda m: m["config_snapshot"].update(commands=[f"config/commands/{n}" for n in names]))


def test_writes_are_journaled_before_they_happen(tmp_path, monkeypatch):
    """A SIGTERM or a closed terminal skips every finally block; the journal written
    before each step is all a restore has."""
    from ccsession.restore import restore_snapshot
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    export = tmp_path / "export"
    _export_with_agent(export, "7f6738b0-d2cb-44ae-a806-09860af58e1f", "a9ba8b4d8b37efc78", "/old/proj")
    _with_commands(export, "a.md", "b.md")
    project = (tmp_path / "newproj").resolve()
    project.mkdir()
    import ccsession.utils as utils
    real_copy = utils.copy_file_writable
    calls = []

    def copy_then_die(src, dst):
        calls.append(dst)
        if len(calls) == 2:
            raise SystemExit("killed")  # stands in for a signal: no Exception handler runs
        return real_copy(src, dst)

    with patch("ccsession.importing.importer.check_version_compatibility", return_value=(True, None)):
        with patch("ccsession.importing.importer.record_import_artifacts", lambda *a, **k: None):
            with patch("ccsession.importing.config.copy_file_writable", side_effect=copy_then_die):
                with pytest.raises(SystemExit):
                    import_session(export, project_path=project, non_interactive=True)

    assert (project / ".claude" / "commands" / "a.md").is_file()
    history = tmp_path / ".claude" / "history.jsonl"
    assert history.read_text(encoding="utf-8").strip()
    restore_snapshot(force=True)
    assert not (project / ".claude").exists()
    assert not history.exists() or not history.read_text(encoding="utf-8").strip()


def test_a_copy_that_fails_before_creating_the_file_is_not_undone_later(tmp_path, monkeypatch):
    """The user may put their own file at that path before restoring."""
    from ccsession.restore import restore_snapshot
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    export = tmp_path / "export"
    _export_with_agent(export, "7f6738b0-d2cb-44ae-a806-09860af58e1f", "a9ba8b4d8b37efc78", "/old/proj")
    _with_commands(export, "a.md")
    project = (tmp_path / "newproj").resolve()
    project.mkdir()

    with patch("ccsession.importing.importer.check_version_compatibility", return_value=(True, None)):
        with patch("ccsession.importing.config.copy_file_writable", side_effect=PermissionError("denied")):
            with pytest.raises(PermissionError):
                import_session(export, project_path=project, non_interactive=True)

    (project / ".claude" / "commands").mkdir(parents=True, exist_ok=True)
    (project / ".claude" / "commands" / "a.md").write_text("my own", encoding="utf-8")
    restore_snapshot(force=True)
    assert (project / ".claude" / "commands" / "a.md").read_text(encoding="utf-8") == "my own"


def test_a_partially_written_claude_md_note_is_undone(tmp_path, monkeypatch):
    from ccsession.restore import restore_snapshot
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    export = tmp_path / "export"
    _export_with_agent(export, "7f6738b0-d2cb-44ae-a806-09860af58e1f", "a9ba8b4d8b37efc78", "/old/proj")
    project = (tmp_path / "newproj").resolve()
    project.mkdir()
    (project / "CLAUDE.md").write_bytes(b"# mine\n")
    import ccsession.importing.config as config

    def half_then_fail(path, data):
        with open(path, "ab") as f:
            f.write(data[: len(data) // 2])
        raise OSError("No space left on device")

    with patch("ccsession.importing.importer.check_version_compatibility", return_value=(True, None)):
        with patch.object(config, "_append_bytes", side_effect=half_then_fail):
            with pytest.raises(OSError):
                import_session(export, project_path=project, non_interactive=True)

    assert (project / "CLAUDE.md").read_bytes() != b"# mine\n"
    restore_snapshot(force=True)
    assert (project / "CLAUDE.md").read_bytes() == b"# mine\n"


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_dangling_symlinks_are_never_written_through_or_removed(tmp_path, monkeypatch):
    """A dotfiles checkout that is not present leaves dangling links in the project."""
    import os
    from ccsession.restore import restore_snapshot
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    export = tmp_path / "export"
    _export_with_agent(export, "7f6738b0-d2cb-44ae-a806-09860af58e1f", "a9ba8b4d8b37efc78", "/old/proj")
    _with_commands(export, "review.md")
    project = (tmp_path / "newproj").resolve()
    (project / ".claude" / "commands").mkdir(parents=True)
    os.symlink(tmp_path / "dotfiles" / "CLAUDE.md", project / "CLAUDE.md")
    os.symlink(tmp_path / "dotfiles" / "review.md", project / ".claude" / "commands" / "review.md")

    with patch("ccsession.importing.importer.check_version_compatibility", return_value=(True, None)):
        import_session(export, project_path=project, non_interactive=True)

    assert not (tmp_path / "dotfiles").exists(), "nothing was written through the links"
    restore_snapshot(force=True)
    assert (project / "CLAUDE.md").is_symlink()
    assert (project / ".claude" / "commands" / "review.md").is_symlink()


def test_read_only_files_in_the_export_are_imported_writable_and_restore_completes(tmp_path, monkeypatch):
    import os
    import stat
    from ccsession.restore import restore_snapshot
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    export = tmp_path / "export"
    _export_with_agent(export, "7f6738b0-d2cb-44ae-a806-09860af58e1f", "a9ba8b4d8b37efc78", "/old/proj")
    _with_commands(export, "review.md")
    (export / "session" / "session-dir" / "tool-results").mkdir(parents=True)
    (export / "session" / "session-dir" / "tool-results" / "b7.txt").write_text("out", encoding="utf-8")
    for f in [export / "config" / "commands" / "review.md", export / "session" / "session-dir" / "tool-results" / "b7.txt"]:
        os.chmod(f, stat.S_IREAD)
    project = (tmp_path / "newproj").resolve()
    project.mkdir()

    with patch("ccsession.importing.importer.check_version_compatibility", return_value=(True, None)):
        import_session(export, project_path=project, non_interactive=True)

    assert os.stat(project / ".claude" / "commands" / "review.md").st_mode & stat.S_IWUSR
    assert restore_snapshot(force=True)["restored"] is True
    assert not (project / ".claude").exists()


def test_deeply_nested_records_are_refused_before_the_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    export = tmp_path / "export"
    _export_with_agent(export, "7f6738b0-d2cb-44ae-a806-09860af58e1f", "a9ba8b4d8b37efc78", "/old/proj")
    agent = export / "session" / "session-dir" / "subagents" / "agent-a9ba8b4d8b37efc78.jsonl"
    nested = "[" * 5000 + "]" * 5000
    with open(agent, "a", encoding="utf-8") as f:
        f.write('{"type": "user", "uuid": "s9", "toolUseResult": ' + nested + '}\n')
    project = (tmp_path / "newproj").resolve()
    project.mkdir()
    previous = _previous_snapshot(tmp_path)

    with patch("ccsession.importing.importer.check_version_compatibility", return_value=(True, None)):
        with pytest.raises(InvalidExportError):
            import_session(export, project_path=project, non_interactive=True)

    assert (previous / "snapshot_info.json").read_text(encoding="utf-8").startswith('{"timestamp": "2026-01-01')


def test_history_records_with_unhashable_fields_import(tmp_path, monkeypatch):
    """Claude Code's history schema tolerates odd field types; so must the de-duplication."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    export = tmp_path / "export"
    _export_with_agent(export, "7f6738b0-d2cb-44ae-a806-09860af58e1f", "a9ba8b4d8b37efc78", "/old/proj")
    with open(export / "session" / "history.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"display": ["x"], "timestamp": {"t": 1}, "sessionId": "7f6738b0-d2cb-44ae-a806-09860af58e1f"}) + "\n")
    user_history = tmp_path / ".claude" / "history.jsonl"
    user_history.parent.mkdir(parents=True)
    user_history.write_text(json.dumps({"display": "mine", "sessionId": {"bad": 1}}) + "\n", encoding="utf-8")
    project = (tmp_path / "newproj").resolve()
    project.mkdir()

    with patch("ccsession.importing.importer.check_version_compatibility", return_value=(True, None)):
        summary = import_session(export, project_path=project, non_interactive=True)

    assert summary["history_lines"] == 2


def test_the_project_directory_must_exist(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    export = tmp_path / "export"
    _export_with_agent(export, "7f6738b0-d2cb-44ae-a806-09860af58e1f", "a9ba8b4d8b37efc78", "/old/proj")

    with patch("ccsession.importing.importer.check_version_compatibility", return_value=(True, None)):
        with pytest.raises(FileNotFoundError, match="Project directory"):
            import_session(export, project_path=tmp_path / "missing", non_interactive=True)

    assert not (tmp_path / ".claude-session-imports").exists()


@pytest.mark.parametrize("mutate", [
    lambda m: m.update(session_id=5),
    lambda m: m.update(session_data=["x"]),
    lambda m: m.update(original_context="x"),
    lambda m: m["session_data"].update(agent_sessions=[5]),
    lambda m: m["session_data"].update(file_history="x"),
    lambda m: m["session_data"].update(history=7),
    lambda m: m["original_context"].update(repo_path=7),
])
def test_manifest_fields_of_the_wrong_type_are_refused_cleanly(tmp_path, monkeypatch, mutate):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    export = tmp_path / "export"
    _export_with_agent(export, "7f6738b0-d2cb-44ae-a806-09860af58e1f", "a9ba8b4d8b37efc78", "/old/proj")
    _rewrite_manifest(export, mutate)
    project = (tmp_path / "newproj").resolve()
    project.mkdir()

    with patch("ccsession.importing.importer.check_version_compatibility", return_value=(True, None)):
        with pytest.raises(InvalidExportError):
            import_session(export, project_path=project, non_interactive=True)


def test_an_unfinished_restore_blocks_a_new_import(tmp_path, monkeypatch):
    """The snapshot of a failed restore holds the only copy of the pre-import sessions."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    export = tmp_path / "export"
    _export_with_agent(export, "7f6738b0-d2cb-44ae-a806-09860af58e1f", "a9ba8b4d8b37efc78", "/old/proj")
    project = (tmp_path / "newproj").resolve()
    project.mkdir()
    previous = _previous_snapshot(tmp_path)
    (previous / "RESTORE_IN_PROGRESS").write_text("", encoding="utf-8")

    with patch("ccsession.importing.importer.check_version_compatibility", return_value=(True, None)):
        with pytest.raises(RuntimeError, match="restore"):
            import_session(export, project_path=project, non_interactive=True)

    assert (previous / "snapshot_info.json").read_text(encoding="utf-8").startswith('{"timestamp": "2026-01-01')


def test_version_probe_on_windows_runs_from_the_executables_directory(tmp_path, monkeypatch):
    """npm's claude.cmd runs a bare `node`, which cmd.exe would look up in the current directory."""
    monkeypatch.setattr("ccsession.importing.validation.sys.platform", "win32")
    exe_dir = tmp_path / "npm"
    exe_dir.mkdir()
    completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="2.1.287 (Claude Code)\n", stderr="")
    with patch("ccsession.importing.validation.shutil.which", return_value=str(exe_dir / "claude.cmd")):
        with patch("ccsession.importing.validation.subprocess.run", return_value=completed) as run:
            check_version_compatibility({"claude_code_version": "2.1.287"})

    kwargs = run.call_args[1]
    assert Path(kwargs["cwd"]) == exe_dir
    assert kwargs["env"]["NoDefaultCurrentDirectoryInExePath"] == "1"


@pytest.mark.parametrize("inventory", [[], None])
def test_all_mirrored_agent_ids_are_remapped_even_with_an_incomplete_inventory(tmp_path, monkeypatch, inventory):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    export = tmp_path / "export"
    sid, agent_id = "7f6738b0-d2cb-44ae-a806-09860af58e1f", "a9ba8b4d8b37efc78"
    _export_with_agent(export, sid, agent_id, "/old/proj")
    _rewrite_manifest(export, lambda m: m["session_data"].update(agent_sessions=inventory))
    project = tmp_path / "newproj"
    project.mkdir()
    agent = export / "session" / "session-dir" / "subagents" / f"agent-{agent_id}.jsonl"
    with agent.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"uuid": "s2", "parentUuid": "s1", "sessionId": sid}) + "\n")

    with patch("ccsession.importing.importer.check_version_compatibility", return_value=(True, None)):
        summary = import_session(export, project_path=project, non_interactive=True)

    restored_agent = get_projects_dir(project) / summary["session_id"] / "subagents" / f"agent-{agent_id}.jsonl"
    records = [json.loads(line) for line in restored_agent.read_text(encoding="utf-8").splitlines()]
    assert records[0]["uuid"] != "s1" and records[1]["uuid"] != "s2"
    assert records[1]["parentUuid"] == records[0]["uuid"]
    assert {r["sessionId"] for r in records} == {summary["session_id"]}


def test_a_null_optional_original_context_imports(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    export = tmp_path / "export"
    _export_with_agent(export, "7f6738b0-d2cb-44ae-a806-09860af58e1f", "a9ba8b4d8b37efc78", "/old/proj")
    _rewrite_manifest(export, lambda m: m.update(original_context=None))
    project = tmp_path / "newproj"
    project.mkdir()

    with patch("ccsession.importing.importer.check_version_compatibility", return_value=(True, None)):
        summary = import_session(export, project_path=project, non_interactive=True)

    assert Path(summary["session_file"]).is_file()
    assert "User: Unknown" in (project / "CLAUDE.md").read_text(encoding="utf-8")


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
@pytest.mark.parametrize("destination", ["project", "session", "transcript", "file-history"])
def test_import_refuses_symlink_destinations_before_replacing_snapshot(tmp_path, monkeypatch, destination):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    export = tmp_path / "export"
    sid = "7f6738b0-d2cb-44ae-a806-09860af58e1f"
    _export_with_agent(export, sid, "a9ba8b4d8b37efc78", "/old/proj")
    project = tmp_path / "newproj"
    project.mkdir()
    outside = tmp_path / "outside"
    target_dir = get_projects_dir(project)
    if destination == "project":
        outside.mkdir()
        target_dir.parent.mkdir(parents=True)
        target_dir.symlink_to(outside, target_is_directory=True)
    elif destination == "session":
        outside.mkdir()
        target_dir.mkdir(parents=True)
        (target_dir / sid).symlink_to(outside, target_is_directory=True)
    elif destination == "transcript":
        target_dir.mkdir(parents=True)
        (target_dir / f"{sid}.jsonl").symlink_to(outside)
    else:
        (export / "session" / "file-history").mkdir()
        (export / "session" / "file-history" / "160c@v1").write_text("snapshot", encoding="utf-8")
        _rewrite_manifest(export, lambda m: m["session_data"].update(file_history=["session/file-history/160c@v1"]))
        outside.mkdir()
        (tmp_path / ".claude").mkdir(exist_ok=True)
        (tmp_path / ".claude" / "file-history").symlink_to(outside, target_is_directory=True)
    previous = _previous_snapshot(tmp_path)

    with patch("ccsession.importing.importer.check_version_compatibility", return_value=(True, None)):
        with pytest.raises(FileExistsError):
            import_session(export, project_path=project, preserve_session_id=True, non_interactive=True)

    assert (previous / "snapshot_info.json").read_text(encoding="utf-8").startswith('{"timestamp": "2026-01-01')
    assert not outside.exists() or (outside.is_dir() and not list(outside.iterdir()))


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX target paths needed for this cross-platform regression")
def test_a_windows_export_imports_with_working_tool_output_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    export = tmp_path / "export"
    sid = "7f6738b0-d2cb-44ae-a806-09860af58e1f"
    _export_with_agent(export, sid, "a9ba8b4d8b37efc78", "C:\\work\\proj")
    output = export / "session" / "session-dir" / "tool-results" / "b7.txt"
    output.parent.mkdir()
    output.write_text("tool output", encoding="utf-8")
    transcript = export / "session" / "main.jsonl"
    with transcript.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"uuid": "u4", "sessionId": sid,
                           "cwd": "C:/work/proj/sub", "toolUseResult": {
                               "persistedOutputPath": "C:\\Users\\u\\.claude\\projects\\C--work-proj\\" + sid + "\\tool-results\\b7.txt"}}) + "\n")
    project = tmp_path / "newproj"
    project.mkdir()

    with patch("ccsession.importing.importer.check_version_compatibility", return_value=(True, None)):
        summary = import_session(export, project_path=project, non_interactive=True)

    records = [json.loads(line) for line in Path(summary["session_file"]).read_text(encoding="utf-8").splitlines()]
    assert records[-1]["cwd"] == str(project / "sub")
    assert Path(records[-1]["toolUseResult"]["persistedOutputPath"]).read_text(encoding="utf-8") == "tool output"
