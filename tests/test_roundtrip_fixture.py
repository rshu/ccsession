"""Export → import round trip over a real (sanitized) Claude Code 2.1.287 session."""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from ccsession.export.exporter import export_session
from ccsession.export.session_discovery import find_session_by_id
from ccsession.importing.importer import import_session
from ccsession.paths import get_projects_dir

FIXTURE = Path(__file__).parent / "fixtures" / "claude-2.1.287"
SID = "7f6738b0-d2cb-44ae-a806-09860af58e1f"
PROJECT = "/tmp/e2e/proj"
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
REF_KEY_RE = re.compile(r"(uuid|Uuid|UUID|Uuids|messageId|MessageId)$")
# Account-level identifiers that look like references but never name a record
NON_REFERENCE_KEYS = {"organizationUuid", "ownerOrganizationUuid", "ownerAccountUuid", "accountUuid"}


def _records(path: Path) -> list:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _dangling_references(records: list) -> dict:
    """Count reference values that look like uuids but match no record uuid."""
    uuids = {r["uuid"] for r in records if "uuid" in r}
    dangling: dict = {}

    def walk(value, key=None):
        if isinstance(value, dict):
            for k, v in value.items():
                if k != "message":
                    walk(v, k)
        elif isinstance(value, list):
            for v in value:
                walk(v, key)
        elif (isinstance(value, str) and key and key != "uuid" and key not in NON_REFERENCE_KEYS
              and REF_KEY_RE.search(key) and UUID_RE.match(value) and value not in uuids):
            dangling[key] = dangling.get(key, 0) + 1

    for r in records:
        walk(r)
    return dangling


def _strings_outside_message(records: list):
    """Yield every (key, string) pair in the records, skipping the frozen message subtree."""
    def walk(value, key=None):
        if isinstance(value, dict):
            for k, v in value.items():
                if k != "message":
                    yield from walk(v, k)
        elif isinstance(value, list):
            for v in value:
                yield from walk(v, key)
        elif isinstance(value, str):
            yield key, value
    for r in records:
        yield from walk(r)


def _survivors(records: list, old_values: set) -> dict:
    """Old identifiers that are still present anywhere outside message content."""
    found: dict = {}
    for key, value in _strings_outside_message(records):
        if value in old_values:
            found[f"{key}={value[:8]}"] = found.get(f"{key}={value[:8]}", 0) + 1
    return found


@pytest.fixture
def source_claude_dir(tmp_path, monkeypatch):
    claude = tmp_path / "source-claude"
    shutil.copytree(FIXTURE, claude)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude))
    return claude


def test_fixture_is_the_expected_session():
    main = _records(FIXTURE / "projects" / "-tmp-e2e-proj" / f"{SID}.jsonl")
    assert {r.get("version") for r in main if "version" in r} == {"2.1.287"}
    assert _dangling_references(main) == {}, "fixture must be internally consistent"
    assert list((FIXTURE / "projects" / "-tmp-e2e-proj" / SID / "subagents").glob("agent-*.jsonl"))


def test_export_then_import_keeps_every_reference_resolvable(tmp_path, monkeypatch, source_claude_dir):
    session = find_session_by_id(SID)
    export_dir, manifest = export_session(session, PROJECT, export_name="rt", output_dir=tmp_path / "exports")
    assert manifest["layout_version"] == 2 and manifest["claude_code_version"] == "2.1.287"
    assert len(manifest["session_data"]["agent_sessions"]) == 1

    target_claude = tmp_path / "target-claude"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(target_claude))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "target-home")
    project = (tmp_path / "newproj").resolve()
    project.mkdir()
    with patch("ccsession.importing.importer.check_version_compatibility", return_value=(True, None)):
        summary = import_session(export_dir, project_path=project, non_interactive=True)

    new_sid = summary["session_id"]
    main = _records(Path(summary["session_file"]))
    original = _records(FIXTURE / "projects" / "-tmp-e2e-proj" / f"{SID}.jsonl")
    old_uuids = {r["uuid"] for r in original if "uuid" in r} | {SID}
    assert _dangling_references(main) == {}
    assert _survivors(main, old_uuids) == {}, "no old record uuid or old session id may survive outside message"
    assert {r["sessionId"] for r in main if "sessionId" in r} == {new_sid}
    assert {r["cwd"] for r in main if "cwd" in r} == {str(project)}
    session_dir = get_projects_dir(project) / new_sid
    agents = list((session_dir / "subagents").glob("agent-*.jsonl"))
    assert len(agents) == 1 and agents[0].with_name(agents[0].name[:-6] + ".meta.json").is_file()
    new_agent = agents[0].stem[len("agent-"):]
    assert new_agent == "a9ba8b4d8b37efc78", "agent ids are stable across import"
    sub = _records(agents[0])
    assert _dangling_references(sub) == {}
    assert _survivors(sub, old_uuids) == {}
    assert {r["agentId"] for r in sub} == {new_agent}
    linked = [r["toolUseResult"]["agentId"] for r in main
              if isinstance(r.get("toolUseResult"), dict) and r["toolUseResult"].get("agentId")]
    assert linked == [new_agent]
    history = _records(target_claude / "history.jsonl")
    assert history and history[-1]["sessionId"] == new_sid


def test_preserved_id_round_trip_keeps_ids_and_moves_paths(tmp_path, monkeypatch, source_claude_dir):
    session = find_session_by_id(SID)
    export_dir, _ = export_session(session, PROJECT, export_name="rt", output_dir=tmp_path / "exports")
    target_claude = tmp_path / "target-claude"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(target_claude))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "target-home")
    project = (tmp_path / "newproj").resolve()
    project.mkdir()
    with patch("ccsession.importing.importer.check_version_compatibility", return_value=(True, None)):
        summary = import_session(export_dir, project_path=project, preserve_session_id=True, non_interactive=True)

    assert summary["session_id"] == SID
    main = _records(Path(summary["session_file"]))
    original = _records(FIXTURE / "projects" / "-tmp-e2e-proj" / f"{SID}.jsonl")
    assert [r.get("uuid") for r in main] == [r.get("uuid") for r in original]
    assert {r["cwd"] for r in main if "cwd" in r} == {str(project)}
    assert list((get_projects_dir(project) / SID / "subagents").glob("agent-*.jsonl"))
