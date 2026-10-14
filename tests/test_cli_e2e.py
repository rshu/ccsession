"""Exercise installed-style commands across isolated export/import/restore stores."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from ccsession.paths import get_normalized_project_dir


REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "tests" / "fixtures" / "claude-2.1.287"
SID = "7f6738b0-d2cb-44ae-a806-09860af58e1f"


def _run(config, project, *args, input=""):
    env = dict(os.environ)
    env.pop("CLAUDE_CODE_PROJECT_DIR_NAME", None)
    env.update(CLAUDE_CONFIG_DIR=str(config), PYTHONPATH=str(REPO))
    return subprocess.run(
        [sys.executable, "-m", "ccsession", *map(str, args)],
        cwd=project, env=env, input=input, capture_output=True, text=True, timeout=30,
    )


def _ok(result):
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Traceback" not in result.stderr
    return result


@pytest.fixture
def cli_source(tmp_path):
    config = tmp_path / "source-config"
    shutil.copytree(FIXTURE, config)
    project = (tmp_path / "source project").resolve()
    project.mkdir()
    session = config / "projects" / "-tmp-e2e-proj" / f"{SID}.jsonl"
    for transcript in session.parent.rglob("*.jsonl"):
        records = [json.loads(line) for line in transcript.read_text(encoding="utf-8").splitlines()]
        for record in records:
            if "cwd" in record:
                record["cwd"] = str(project)
        transcript.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    session.parent.rename(config / "projects" / get_normalized_project_dir(project))

    for category, name in (
        ("commands", "nested/review.md"), ("skills", "review/SKILL.md"),
        ("hooks", "check.py"), ("agents", "review.md"), ("rules", "nested/style.md"),
    ):
        path = project / ".claude" / category / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"fixture {category}\n", encoding="utf-8")
    (project / ".claude" / "settings.json").write_text('{"fixture": true}', encoding="utf-8")
    (project / "CLAUDE.md").write_text("Source project instructions\n", encoding="utf-8")
    for category, name in (("file-history", "snapshot@v1"), ("session-env", "env.json")):
        path = config / category / SID / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture data\n")
    sidecar = config / "projects" / get_normalized_project_dir(project) / SID / "tool-results" / "result.txt"
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_bytes(b"tool result\n")
    return config, project


@pytest.mark.parametrize("flags", [(), ("--preserve-session-id",), ("--skip-config",), ("--skip-auxiliary",)])
def test_cli_round_trip_and_restore(tmp_path, cli_source, flags):
    source_config, source_project = cli_source
    export_root = tmp_path / "exports"
    exported = export_root / "portable"
    _ok(_run(source_config, source_project, "--verbose", "export", "--session-id", SID,
             "--output-dir", export_root, "--export-name", "portable"))
    manifest = json.loads((exported / ".ccsession-manifest.json").read_text(encoding="utf-8"))
    assert manifest["session_id"] == SID and manifest["layout_version"] == 2
    assert (exported / "session" / "session-env" / "env.json").read_bytes() == b"fixture data\n"
    assert (exported / "session" / "session-dir" / "tool-results" / "result.txt").read_bytes() == b"tool result\n"
    ET.parse(exported / "conversation_full.xml")

    target_config = tmp_path / "target-config"
    target_project = (tmp_path / "target project").resolve()
    target_project.mkdir()
    (target_project / "CLAUDE.md").write_text("Existing instructions\n", encoding="utf-8")
    project_store = target_config / "projects" / get_normalized_project_dir(target_project)
    project_store.mkdir(parents=True)
    (project_store / "prior.jsonl").write_bytes(b"original session\n")
    (project_store / "memory").mkdir()
    (project_store / "memory" / "note.md").write_bytes(b"initial memory\n")
    history = target_config / "history.jsonl"
    history.write_bytes(b'{"display":"existing"}\n')

    imported = _ok(_run(target_config, target_project, "--quiet", "import", exported,
                        "--non-interactive", *flags))
    session_id = next(line.split("Session ID: ")[1].strip() for line in imported.stdout.splitlines()
                      if "Session ID: " in line)
    if "--preserve-session-id" in flags:
        assert session_id == SID
    else:
        assert session_id != SID
    transcript = project_store / f"{session_id}.jsonl"
    records = [json.loads(line) for line in transcript.read_text(encoding="utf-8").splitlines()]
    assert {r["cwd"] for r in records if "cwd" in r} == {str(target_project)}
    original = [json.loads(line) for line in (exported / "session" / "main.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r.get("message") for r in records] == [r.get("message") for r in original]
    agents = list((project_store / session_id / "subagents").glob("agent-*.jsonl"))
    assert agents
    for agent in agents:
        subrecords = [json.loads(line) for line in agent.read_text(encoding="utf-8").splitlines()]
        assert {r["cwd"] for r in subrecords if "cwd" in r} == {str(target_project)}
        assert {r["sessionId"] for r in subrecords if "sessionId" in r} == {session_id}
        uuids = {r["uuid"] for r in subrecords if "uuid" in r}
        assert all(r.get("parentUuid") is None or r["parentUuid"] in uuids for r in subrecords)
        original_sub = [json.loads(line) for line in
                        (exported / "session" / "session-dir" / "subagents" / agent.name).read_text(encoding="utf-8").splitlines()]
        assert [r.get("message") for r in subrecords] == [r.get("message") for r in original_sub]
        old_uuids = {r["uuid"] for r in original_sub if "uuid" in r}
        if "--preserve-session-id" in flags:
            assert uuids == old_uuids
        else:
            assert uuids.isdisjoint(old_uuids)
    assert (project_store / session_id / "tool-results" / "result.txt").read_bytes() == b"tool result\n"
    assert (project_store / "prior.jsonl").read_bytes() == b"original session\n"
    if "--skip-config" in flags:
        assert not (target_project / ".claude").exists()
        assert (target_project / "CLAUDE.md").read_text(encoding="utf-8") == "Existing instructions\n"
    else:
        assert (target_project / ".claude" / "skills" / "review" / "SKILL.md").is_file()
        assert not (target_project / ".claude" / "settings.json").exists()
        assert "Source project instructions" not in (target_project / "CLAUDE.md").read_text(encoding="utf-8")
    if "--skip-auxiliary" in flags:
        assert not (target_config / "file-history" / session_id).exists()
        assert history.read_bytes() == b'{"display":"existing"}\n'
    else:
        assert (target_config / "file-history" / session_id / "snapshot@v1").read_bytes() == b"fixture data\n"
        assert any(json.loads(line).get("sessionId") == session_id
                   for line in history.read_text(encoding="utf-8").splitlines())

    snapshot = target_config / "ccsession-imports" / "pre-import-snapshot"
    snapshot_before = (snapshot / "snapshot_info.json").read_bytes()
    if "--preserve-session-id" in flags:
        conflict = _run(target_config, target_project, "import", exported,
                        "--non-interactive", "--preserve-session-id")
        assert conflict.returncode == 1 and "already exists" in conflict.stderr
        assert (snapshot / "snapshot_info.json").read_bytes() == snapshot_before

    _ok(_run(target_config, target_project, "restore"))
    assert transcript.exists(), "showing the restore plan must not change files"
    declined = _run(target_config, target_project, "restore", "--restore")
    assert declined.returncode == 1 and transcript.exists()

    # Changes made after import have different restore semantics: ordinary sessions
    # roll back, whereas project memory, later prompt history and instructions survive.
    (project_store / "prior.jsonl").write_bytes(b"later turn\n")
    (project_store / "later.jsonl").write_bytes(b"later session\n")
    (project_store / "memory" / "note.md").write_bytes(b"later memory\n")
    later_history = json.dumps({"display": "later prompt", "sessionId": session_id}) + "\n"
    with history.open("a", encoding="utf-8") as stream:
        stream.write(later_history)
    with (target_project / "CLAUDE.md").open("a", encoding="utf-8") as stream:
        stream.write("Later instructions\n")

    _ok(_run(target_config, target_project, "restore", "--restore", "--yes"))
    assert not transcript.exists() and not (project_store / session_id).exists()
    assert not (project_store / "later.jsonl").exists()
    assert (project_store / "prior.jsonl").read_bytes() == b"original session\n"
    assert (project_store / "memory" / "note.md").read_bytes() == b"later memory\n"
    assert history.read_text(encoding="utf-8") == '{"display":"existing"}\n' + later_history
    assert (target_project / "CLAUDE.md").read_text(encoding="utf-8") == "Existing instructions\nLater instructions\n"
    assert not (target_project / ".claude").exists()
    assert not (target_config / "file-history" / session_id).exists()
    assert not snapshot.exists()


def test_cli_classic_and_existing_destination(tmp_path, cli_source):
    config, project = cli_source
    output = tmp_path / "exports"
    args = ("export", "--session-id", SID, "--output-dir", output,
            "--export-name", "classic", "--mode", "classic")
    _ok(_run(config, project, *args))
    exported = output / "classic"
    assert not (exported / ".ccsession-manifest.json").exists()
    before = {p.name: p.read_bytes() for p in exported.iterdir()}
    ET.parse(exported / "conversation_full.xml")
    conflict = _run(config, project, *args)
    assert conflict.returncode == 1 and "already exists" in conflict.stderr
    assert {p.name: p.read_bytes() for p in exported.iterdir()} == before


def test_cli_project_discovery_and_invalid_import(tmp_path, cli_source):
    config, project = cli_source
    _ok(_run(config, project, "export", "--output-dir", tmp_path / "exports", "--export-name", "discovered"))
    exported = tmp_path / "exports" / "discovered"
    target_config = tmp_path / "target-config"
    manifest_path = exported / ".ccsession-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["session_data"]["main_session"] = "../outside.jsonl"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    failed = _run(target_config, project, "import", exported, "--non-interactive")
    assert failed.returncode == 1 and "Import validation failed" in failed.stderr
    assert "Traceback" not in failed.stderr
    assert not target_config.exists(), "invalid imports must fail before any write"
