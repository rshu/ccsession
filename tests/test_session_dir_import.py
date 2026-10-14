"""Restoring the per-session directory and prompt history from an export."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ccsession.importing.remap import RemapPlan
from ccsession.importing.session_dir import SessionDirImport, import_history, import_session_dir

OLD_SID = "7f6738b0-d2cb-44ae-a806-09860af58e1f"
NEW_SID = "1daacb2b-ece9-454d-8640-89d7cbcde89a"
OLD_AGENT, NEW_AGENT = "a9ba8b4d8b37efc78", "bbbbbbbbbbbbbbbbb"


def _plan(**overrides):
    base = dict(old_session_id=OLD_SID, new_session_id=NEW_SID, uuid_map={"s1": "n1", "s2": "n2"},
                agent_map={OLD_AGENT: NEW_AGENT}, path_rules=())
    base.update(overrides)
    return RemapPlan(**base)


def _layout2_export(root: Path) -> dict:
    mirror = root / "session" / "session-dir"
    (mirror / "subagents").mkdir(parents=True)
    (mirror / "tool-results").mkdir()
    (mirror / "workflows" / "scripts").mkdir(parents=True)
    agent_lines = [
        {"type": "user", "uuid": "s1", "parentUuid": None, "agentId": OLD_AGENT, "sessionId": OLD_SID,
         "message": {"role": "user", "content": "sub"}},
        {"type": "assistant", "uuid": "s2", "parentUuid": "s1", "agentId": OLD_AGENT, "sessionId": OLD_SID,
         "message": {"role": "assistant", "content": []}},
    ]
    (mirror / "subagents" / f"agent-{OLD_AGENT}.jsonl").write_text(
        "".join(json.dumps(l) + "\n" for l in agent_lines), encoding="utf-8")
    (mirror / "subagents" / f"agent-{OLD_AGENT}.meta.json").write_text(
        json.dumps({"agentType": "Explore", "toolUseId": "toolu_01", "spawnDepth": 1}), encoding="utf-8")
    (mirror / "tool-results" / "b7.txt").write_text("big", encoding="utf-8")
    (mirror / "workflows" / "scripts" / "wf.js").write_text("js", encoding="utf-8")
    (mirror / "auto-mode-classifier-error.txt").write_text("err", encoding="utf-8")
    return {"layout_version": 2, "session_data": {"session_dir": "session/session-dir/"}}


def test_layout2_mirror_is_restored_with_agents_remapped_and_renamed(tmp_path):
    manifest = _layout2_export(tmp_path / "export")
    target = tmp_path / "claude" / "projects" / "-p" / NEW_SID

    result = import_session_dir(tmp_path / "export", manifest, target, _plan())

    assert result == SessionDirImport(files=5, agents=1)
    agent_file = target / "subagents" / f"agent-{NEW_AGENT}.jsonl"
    records = [json.loads(l) for l in agent_file.read_text(encoding="utf-8").splitlines()]
    assert [r["uuid"] for r in records] == ["n1", "n2"] and records[1]["parentUuid"] == "n1"
    assert {r["agentId"] for r in records} == {NEW_AGENT} and {r["sessionId"] for r in records} == {NEW_SID}
    assert not (target / "subagents" / f"agent-{OLD_AGENT}.jsonl").exists()
    assert json.loads((target / "subagents" / f"agent-{NEW_AGENT}.meta.json").read_text())["toolUseId"] == "toolu_01"
    assert (target / "tool-results" / "b7.txt").read_text(encoding="utf-8") == "big"
    assert (target / "workflows" / "scripts" / "wf.js").is_file()
    assert (target / "auto-mode-classifier-error.txt").is_file()


def test_legacy_layout_agents_are_restored_into_subagents(tmp_path):
    export = tmp_path / "export"
    (export / "session" / "agents").mkdir(parents=True)
    (export / "session" / "agents" / f"agent-{OLD_AGENT}.jsonl").write_text(
        json.dumps({"type": "user", "uuid": "s1", "agentId": OLD_AGENT, "sessionId": OLD_SID}) + "\n", encoding="utf-8")
    (export / "session" / "agents" / "_empty").write_text("", encoding="utf-8")
    manifest = {"session_data": {"agent_sessions": [f"session/agents/agent-{OLD_AGENT}.jsonl"]}}
    target = tmp_path / "target" / NEW_SID

    result = import_session_dir(export, manifest, target, _plan())

    assert result == SessionDirImport(files=1, agents=1)
    restored = json.loads((target / "subagents" / f"agent-{NEW_AGENT}.jsonl").read_text(encoding="utf-8"))
    assert restored["uuid"] == "n1" and restored["agentId"] == NEW_AGENT
    assert not (target / "subagents" / "_empty").exists()


def test_empty_marker_and_missing_mirror_import_nothing(tmp_path):
    export = tmp_path / "export"
    (export / "session" / "session-dir").mkdir(parents=True)
    (export / "session" / "session-dir" / "_empty").write_text("none", encoding="utf-8")
    target = tmp_path / "target" / NEW_SID
    assert import_session_dir(export, {"session_data": {"session_dir": "session/session-dir/"}}, target, _plan()) == SessionDirImport(0, 0)
    assert not target.exists()
    assert import_session_dir(export, {"session_data": {}}, target, _plan()) == SessionDirImport(0, 0)


def test_refuses_to_overwrite_a_populated_target(tmp_path):
    manifest = _layout2_export(tmp_path / "export")
    target = tmp_path / "target" / NEW_SID
    (target / "subagents").mkdir(parents=True)
    (target / "subagents" / "agent-x.jsonl").write_text("{}\n", encoding="utf-8")
    with pytest.raises(FileExistsError, match=str(target)):
        import_session_dir(tmp_path / "export", manifest, target, _plan())


def test_history_records_are_appended_once_with_new_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    export = tmp_path / "export"
    (export / "session").mkdir(parents=True)
    rows = [{"display": "fix it", "pastedContents": {}, "timestamp": 1791945800023, "project": "/old/proj", "sessionId": OLD_SID},
            {"display": "again", "pastedContents": {}, "timestamp": 1791945800099, "project": "/old/proj", "sessionId": OLD_SID}]
    (export / "session" / "history.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    manifest = {"session_data": {"history": "session/history.jsonl"}}
    history = tmp_path / ".claude" / "history.jsonl"
    history.parent.mkdir(parents=True)
    history.write_text(json.dumps({"display": "unrelated", "timestamp": 5, "project": "/x", "sessionId": "other"}) + "\n", encoding="utf-8")

    assert import_history(export, manifest, _plan(), "/new/proj") == 2
    assert import_history(export, manifest, _plan(), "/new/proj") == 0, "second import must not duplicate"

    lines = [json.loads(l) for l in history.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 3
    assert lines[1] == {"display": "fix it", "pastedContents": {}, "timestamp": 1791945800023, "project": "/new/proj", "sessionId": NEW_SID}


def test_history_import_without_history_in_export_is_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert import_history(tmp_path, {"session_data": {}}, _plan(), "/new/proj") == 0
