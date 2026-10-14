"""Export tree tests against a fake Claude Code 2.1 layout."""
from __future__ import annotations

import json
from pathlib import Path

from ccsession.export.exporter import export_session

SID = "7f6738b0-d2cb-44ae-a806-09860af58e1f"
AGENT = "a9ba8b4d8b37efc78"
PROJECT = "/home/user/proj"


def _record(**kw):
    base = {"type": "user", "uuid": "u1", "parentUuid": None, "sessionId": SID, "cwd": PROJECT,
            "version": "2.1.287", "gitBranch": "main", "timestamp": "2026-10-14T02:50:00.000Z",
            "message": {"role": "user", "content": "hi"}}
    base.update(kw)
    return base


def _fake_claude_dir(home: Path) -> Path:
    claude = home / ".claude"
    proj = claude / "projects" / "-home-user-proj"
    sess = proj / SID
    (sess / "subagents").mkdir(parents=True)
    (sess / "tool-results").mkdir()
    (sess / "workflows" / "scripts").mkdir(parents=True)
    (proj / f"{SID}.jsonl").write_text(json.dumps(_record()) + "\n", encoding="utf-8")
    (sess / "subagents" / f"agent-{AGENT}.jsonl").write_text(
        json.dumps(_record(agentId=AGENT, isSidechain=True)) + "\n", encoding="utf-8")
    (sess / "subagents" / f"agent-{AGENT}.meta.json").write_text(
        json.dumps({"agentType": "Explore", "toolUseId": "toolu_01", "spawnDepth": 1}), encoding="utf-8")
    (sess / "tool-results" / "bvce53z33.txt").write_text("big output", encoding="utf-8")
    (sess / "workflows" / "wf_1.json").write_text("{}", encoding="utf-8")
    (sess / "workflows" / "scripts" / "wf_1.js").write_text("export const meta = {}", encoding="utf-8")
    (sess / "auto-mode-classifier-error.txt").write_text("=== ERROR ===", encoding="utf-8")
    (claude / "history.jsonl").write_text(json.dumps(
        {"display": "hi", "pastedContents": {}, "timestamp": 1, "project": PROJECT, "sessionId": SID}) + "\n",
        encoding="utf-8")
    return claude


def test_export_mirrors_the_session_dir_and_history(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    claude = _fake_claude_dir(tmp_path)
    session_info = {"path": claude / "projects" / "-home-user-proj" / f"{SID}.jsonl", "session_id": SID, "mtime": 0}

    export_dir, manifest = export_session(session_info, PROJECT, export_name="t", output_dir=tmp_path / "out")

    mirror = export_dir / "session" / "session-dir"
    assert (mirror / "subagents" / f"agent-{AGENT}.jsonl").is_file()
    assert (mirror / "subagents" / f"agent-{AGENT}.meta.json").is_file()
    assert (mirror / "tool-results" / "bvce53z33.txt").read_text(encoding="utf-8") == "big output"
    assert (mirror / "workflows" / "scripts" / "wf_1.js").is_file()
    assert (mirror / "auto-mode-classifier-error.txt").is_file()
    history = (export_dir / "session" / "history.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(history[0])["display"] == "hi"
    assert manifest["layout_version"] == 2
    assert manifest["session_data"]["session_dir"] == "session/session-dir/"
    assert manifest["session_data"]["history"] == "session/history.jsonl"
    assert manifest["session_data"]["agent_sessions"] == [f"session/session-dir/subagents/agent-{AGENT}.jsonl"]
    assert manifest["session_data"]["agent_meta"] == [f"session/session-dir/subagents/agent-{AGENT}.meta.json"]
    assert manifest["claude_code_version"] == "2.1.287"


def test_export_has_no_legacy_copies_or_stores(tmp_path, monkeypatch):
    """Sub-agents and tool results live only in the session-dir mirror; the todos/plans
    stores of older Claude Code releases are not part of the format."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    claude = _fake_claude_dir(tmp_path)
    session_info = {"path": claude / "projects" / "-home-user-proj" / f"{SID}.jsonl", "session_id": SID, "mtime": 0}

    export_dir, manifest = export_session(session_info, PROJECT, export_name="t", output_dir=tmp_path / "out")

    assert not (export_dir / "session" / "agents").exists()
    assert not (export_dir / "session" / "tool-results").exists()
    assert not (export_dir / "session" / "plan.md").exists()
    assert not (export_dir / "session" / "todos.json").exists()
    assert not {"plan_file", "todos", "tool_results"} & set(manifest["session_data"])


def test_export_marks_an_empty_session_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    proj = tmp_path / ".claude" / "projects" / "-home-user-proj"
    proj.mkdir(parents=True)
    (proj / f"{SID}.jsonl").write_text(json.dumps(_record()) + "\n", encoding="utf-8")
    session_info = {"path": proj / f"{SID}.jsonl", "session_id": SID, "mtime": 0}

    export_dir, manifest = export_session(session_info, PROJECT, export_name="t", output_dir=tmp_path / "out")

    assert (export_dir / "session" / "session-dir" / "_empty").is_file()
    assert manifest["session_data"]["session_dir"] is None
    assert manifest["session_data"]["history"] is None
    assert not (export_dir / "session" / "history.jsonl").exists()


def test_export_mirrors_skill_directories_in_the_config_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    claude = _fake_claude_dir(tmp_path)
    project = tmp_path / "proj"
    (project / ".claude" / "skills" / "deploy" / "references").mkdir(parents=True)
    (project / ".claude" / "skills" / "deploy" / "SKILL.md").write_text("# deploy", encoding="utf-8")
    (project / ".claude" / "skills" / "deploy" / "references" / "steps.md").write_text("1.", encoding="utf-8")
    (project / ".claude" / "commands" / "team").mkdir(parents=True)
    (project / ".claude" / "commands" / "team" / "review.md").write_text("r", encoding="utf-8")
    session_info = {"path": claude / "projects" / "-home-user-proj" / f"{SID}.jsonl", "session_id": SID, "mtime": 0}

    export_dir, manifest = export_session(session_info, project, export_name="t", output_dir=tmp_path / "out")

    assert (export_dir / "config" / "skills" / "deploy" / "SKILL.md").read_text(encoding="utf-8") == "# deploy"
    assert (export_dir / "config" / "skills" / "deploy" / "references" / "steps.md").is_file()
    assert (export_dir / "config" / "commands" / "team" / "review.md").is_file()
    assert manifest["config_snapshot"]["skills"] == ["config/skills/deploy/SKILL.md",
                                                     "config/skills/deploy/references/steps.md"]
    assert manifest["config_snapshot"]["commands"] == ["config/commands/team/review.md"]


def test_export_does_not_recreate_a_project_directory_that_no_longer_exists(tmp_path, monkeypatch):
    """Exporting by --session-id a session whose project was deleted must not resurrect the
    directory just to hold the export; the export goes under the current directory instead."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    claude = _fake_claude_dir(tmp_path)
    gone = tmp_path / "gone-project"
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    session_info = {"path": claude / "projects" / "-home-user-proj" / f"{SID}.jsonl", "session_id": SID, "mtime": 0}

    export_dir, manifest = export_session(session_info, gone, export_name="t")

    assert not gone.exists()
    assert export_dir == cwd / ".claude-sessions" / "t"
    assert manifest["original_context"]["repo_path"] == str(gone)


def test_legacy_files_survive_control_and_surrogate_characters(tmp_path, monkeypatch):
    """A lone surrogate (a \\ud800 escape in the transcript) is not UTF-8 encodable and an
    escape in the recorded cwd used to make the XML metadata block ill-formed."""
    import xml.etree.ElementTree as ET
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    proj = tmp_path / ".claude" / "projects" / "-home-user-proj"
    proj.mkdir(parents=True)
    bad = _record(cwd="/home/user/pr\x1boj", version="2.1\x1b.287",
                  message={"role": "user", "content": "lone \ud800 surrogate"})
    (proj / f"{SID}.jsonl").write_text(json.dumps(bad) + "\n", encoding="utf-8")
    session_info = {"path": proj / f"{SID}.jsonl", "session_id": SID, "mtime": 0}

    export_dir, _ = export_session(session_info, PROJECT, export_name="t", output_dir=tmp_path / "out")

    assert "lone" in (export_dir / "conversation_full.md").read_text(encoding="utf-8")
    root = ET.parse(export_dir / "conversation_full.xml").getroot()  # parses: the file is well-formed
    working_directory = [e for e in root.iter() if e.tag.endswith("working-directory")][0]
    assert working_directory.text == "/home/user/proj"


def test_a_failed_export_leaves_no_half_written_directory(tmp_path, monkeypatch):
    from unittest.mock import patch
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    claude = _fake_claude_dir(tmp_path)
    session_info = {"path": claude / "projects" / "-home-user-proj" / f"{SID}.jsonl", "session_id": SID, "mtime": 0}

    with patch("ccsession.export.exporter.format_trajectory", side_effect=RuntimeError("boom")):
        try:
            export_session(session_info, PROJECT, export_name="t", output_dir=tmp_path / "out")
        except RuntimeError:
            pass

    assert not (tmp_path / "out" / "t").exists()


def test_records_with_a_malformed_message_or_timestamp_are_exported(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    proj = tmp_path / ".claude" / "projects" / "-home-user-proj"
    proj.mkdir(parents=True)
    rows = [_record(), {"type": "user", "uuid": "u2", "message": None, "timestamp": 5},
            {"type": "user", "uuid": "u3", "message": "plain", "timestamp": "not a date"},
            {"type": "user", "uuid": "u4", "message": ["role"]}]
    (proj / f"{SID}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    session_info = {"path": proj / f"{SID}.jsonl", "session_id": SID, "mtime": 0}

    export_dir, manifest = export_session(session_info, PROJECT, export_name="t", output_dir=tmp_path / "out")

    trajectory = json.loads((export_dir / "trajectory.json").read_text(encoding="utf-8"))
    assert [t["role"] for t in trajectory["trajectory"]] == ["user", "event", "event", "event"]
    assert (export_dir / "RENDERED.md").is_file()


import pytest  # noqa: E402


@pytest.mark.parametrize("name", ["tmp/..", "tmp/../..", "a/b", "..", ".", "/abs", ""])
def test_an_export_name_must_be_a_single_plain_component(tmp_path, monkeypatch, name):
    """A failed export removes the directory it created; a name like tmp/.. would make
    that the user's own directory."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    claude = _fake_claude_dir(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    (out / "precious.txt").write_text("x", encoding="utf-8")
    session_info = {"path": claude / "projects" / "-home-user-proj" / f"{SID}.jsonl", "session_id": SID, "mtime": 0}

    with pytest.raises(ValueError, match="export name"):
        export_session(session_info, PROJECT, export_name=name, output_dir=out)

    assert (out / "precious.txt").exists()


def test_a_failed_export_into_an_existing_directory_leaves_it(tmp_path, monkeypatch):
    from unittest.mock import patch
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    claude = _fake_claude_dir(tmp_path)
    (tmp_path / "out" / "t").mkdir(parents=True)
    (tmp_path / "out" / "t" / "keep.txt").write_text("x", encoding="utf-8")
    session_info = {"path": claude / "projects" / "-home-user-proj" / f"{SID}.jsonl", "session_id": SID, "mtime": 0}

    with patch("ccsession.export.exporter.format_trajectory", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError):
            export_session(session_info, PROJECT, export_name="t", output_dir=tmp_path / "out")

    assert (tmp_path / "out" / "t" / "keep.txt").exists()


def test_prompt_history_with_a_lone_surrogate_exports(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    claude = _fake_claude_dir(tmp_path)
    with open(claude / "history.jsonl", "a", encoding="utf-8") as f:
        f.write('{"display": "cut \\ud83d", "timestamp": 2, "project": "/home/user/proj", "sessionId": "%s"}\n' % SID)
    session_info = {"path": claude / "projects" / "-home-user-proj" / f"{SID}.jsonl", "session_id": SID, "mtime": 0}

    export_dir, _ = export_session(session_info, PROJECT, export_name="t", output_dir=tmp_path / "out")

    lines = (export_dir / "session" / "history.jsonl").read_bytes().decode("utf-8").splitlines()
    assert json.loads(lines[-1])["display"] == "cut \ud83d"
