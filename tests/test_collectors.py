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


# ---------------------------------------------------------------------------
# Project config is mirrored as a tree, the way Claude Code lays it out
# ---------------------------------------------------------------------------

from ccsession.export.collectors import ConfigFile, collect_project_config  # noqa: E402


def _touch(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_skills_are_collected_as_directories(tmp_path):
    """Claude Code skills live at .claude/skills/<name>/SKILL.md with supporting files."""
    skill = _touch(tmp_path / ".claude" / "skills" / "deploy" / "SKILL.md")
    ref = _touch(tmp_path / ".claude" / "skills" / "deploy" / "references" / "steps.md")

    config = collect_project_config(tmp_path)

    assert config["skills"] == [ConfigFile(skill, "deploy/SKILL.md"), ConfigFile(ref, "deploy/references/steps.md")]


def test_nested_commands_keep_their_sub_path(tmp_path):
    top = _touch(tmp_path / ".claude" / "commands" / "top.md")
    nested = _touch(tmp_path / ".claude" / "commands" / "team" / "review.md")
    _touch(tmp_path / ".claude" / "commands" / "notes.txt")  # not a command

    config = collect_project_config(tmp_path)

    assert config["commands"] == [ConfigFile(nested, "team/review.md"), ConfigFile(top, "top.md")]


def test_project_level_commands_directory_is_not_claude_config(tmp_path):
    """Only .claude/commands/ is read by Claude Code; a top-level commands/ folder is unrelated."""
    _touch(tmp_path / "commands" / "stray.md")

    assert collect_project_config(tmp_path)["commands"] == []


def test_hooks_agents_and_rules_are_collected_recursively(tmp_path):
    hook = _touch(tmp_path / ".claude" / "hooks" / "pre" / "lint.sh")
    agent = _touch(tmp_path / ".claude" / "agents" / "reviewer.md")
    rule = _touch(tmp_path / ".claude" / "rules" / "python" / "style.md")

    config = collect_project_config(tmp_path)

    assert config["hooks"] == [ConfigFile(hook, "pre/lint.sh")]
    assert config["agents"] == [ConfigFile(agent, "reviewer.md")]
    assert config["rules"] == [ConfigFile(rule, "python/style.md")]


import os  # noqa: E402
import sys  # noqa: E402

import pytest  # noqa: E402


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_symlinked_skill_directories_are_collected(tmp_path):
    """Claude Code loads a skill directory that is a symlink (shared skills)."""
    shared = tmp_path / "shared" / "team-skill"
    _touch(shared / "SKILL.md")
    _touch(shared / "helper.py")
    (tmp_path / "proj" / ".claude" / "skills").mkdir(parents=True)
    os.symlink(shared, tmp_path / "proj" / ".claude" / "skills" / "team-skill")
    os.symlink(tmp_path / "proj" / ".claude" / "skills", shared / "loop")  # a cycle must not hang

    skills = collect_project_config(tmp_path / "proj")["skills"]

    assert sorted(cf.relative for cf in skills) == ["team-skill/SKILL.md", "team-skill/helper.py"]
