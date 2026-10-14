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
