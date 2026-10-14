import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ccsession.export.collectors import collect_agent_sessions, collect_history_lines, collect_session_dir_files

SESSION_ID = "11111111-2222-3333-4444-555555555555"
OTHER_SESSION_ID = "99999999-8888-7777-6666-555555555555"


def _write_agent_file(path: Path, session_id: str, agent_id: str) -> Path:
    """Write a sub-agent transcript whose first line mirrors a real one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    first_line = {
        "agentId": agent_id,
        "cwd": "/home/user/project",
        "entrypoint": "cli",
        "gitBranch": "main",
        "isSidechain": True,
        "message": {"role": "user", "content": "Do the subtask"},
        "parentUuid": None,
        "promptId": "prompt-1",
        "sessionId": session_id,
        "slug": "some-slug",
        "timestamp": "2026-03-02T10:00:00Z",
        "type": "user",
        "userType": "external",
        "uuid": "sub-u1",
        "version": "2.1.287",
    }
    path.write_text(json.dumps(first_line) + "\n", encoding="utf-8")
    return path


def test_collects_subagent_file_never_referenced_by_main_transcript(tmp_path):
    """Async/background agents leave no agentId in the main transcript, but their
    file still sits in the session's own subagents/ folder and must be exported."""
    agent_id = "a1b2c3d4e5f6a7b8c"
    agent_file = _write_agent_file(
        tmp_path / SESSION_ID / "subagents" / f"agent-{agent_id}.jsonl", SESSION_ID, agent_id)

    result = collect_agent_sessions(tmp_path, SESSION_ID)

    assert result == {agent_id: agent_file}


def test_meta_json_sidecars_are_not_collected_as_agents(tmp_path):
    agent_id = "f1f1f1f1f1f1f1f1f"
    subagents = tmp_path / SESSION_ID / "subagents"
    _write_agent_file(subagents / f"agent-{agent_id}.jsonl", SESSION_ID, agent_id)
    (subagents / f"agent-{agent_id}.meta.json").write_text('{"status": "completed"}', encoding="utf-8")

    result = collect_agent_sessions(tmp_path, SESSION_ID)

    assert set(result) == {agent_id}


def test_legacy_flat_layout_matches_agent_files_by_session_id(tmp_path):
    """In the old flat layout every session's agents share one folder; the first
    line's sessionId is what says which session a file belongs to."""
    mine, theirs = "ccccccccccccccccc", "ddddddddddddddddd"
    mine_file = _write_agent_file(tmp_path / f"agent-{mine}.jsonl", SESSION_ID, mine)
    _write_agent_file(tmp_path / f"agent-{theirs}.jsonl", OTHER_SESSION_ID, theirs)

    result = collect_agent_sessions(tmp_path, SESSION_ID)

    assert result == {mine: mine_file}


def test_per_session_file_wins_over_legacy_duplicate(tmp_path):
    agent_id = "eeeeeeeeeeeeeeeee"
    new_style = _write_agent_file(
        tmp_path / SESSION_ID / "subagents" / f"agent-{agent_id}.jsonl", SESSION_ID, agent_id)
    _write_agent_file(tmp_path / f"agent-{agent_id}.jsonl", SESSION_ID, agent_id)

    result = collect_agent_sessions(tmp_path, SESSION_ID)

    assert result == {agent_id: new_style}


def test_session_dir_files_are_collected_recursively_and_sorted(tmp_path):
    sess = tmp_path / SESSION_ID
    (sess / "subagents").mkdir(parents=True)
    (sess / "workflows" / "scripts").mkdir(parents=True)
    (sess / "tool-results").mkdir()
    files = [
        sess / "subagents" / "agent-a1a1a1a1a1a1a1a1a.jsonl",
        sess / "subagents" / "agent-a1a1a1a1a1a1a1a1a.meta.json",
        sess / "tool-results" / "bvce53z33.txt",
        sess / "workflows" / "wf_02478d01-87f.json",
        sess / "workflows" / "scripts" / "review-wf_02478d01-87f.js",
        sess / "auto-mode-classifier-error.txt",
    ]
    for f in files:
        f.write_text("x", encoding="utf-8")

    assert collect_session_dir_files(tmp_path, SESSION_ID) == sorted(files)


def test_session_dir_files_is_empty_when_dir_is_absent(tmp_path):
    assert collect_session_dir_files(tmp_path, SESSION_ID) == []


def test_history_lines_for_session_are_returned_in_order(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    history = tmp_path / ".claude" / "history.jsonl"
    history.parent.mkdir(parents=True)
    rows = [
        {"display": "first", "pastedContents": {}, "timestamp": 1791945800023, "project": "/home/user/proj", "sessionId": SESSION_ID},
        {"display": "other", "pastedContents": {}, "timestamp": 1791945800024, "project": "/home/user/proj", "sessionId": OTHER_SESSION_ID},
        {"display": "second", "pastedContents": {}, "timestamp": 1791945800025, "project": "/home/user/proj", "sessionId": SESSION_ID},
    ]
    history.write_text("".join(json.dumps(r) + "\n" for r in rows) + "{broken\n", encoding="utf-8")

    assert [r["display"] for r in collect_history_lines(SESSION_ID)] == ["first", "second"]


def test_history_lines_is_empty_without_history_file(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert collect_history_lines(SESSION_ID) == []
