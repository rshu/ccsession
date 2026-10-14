"""The pre-import snapshot records everything an import will touch; import logs never collide."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from ccsession.importing.import_log import log_import
from ccsession.importing.snapshot import SNAPSHOT_VERSION, create_snapshot, record_import_artifacts
from ccsession.utils import read_json

SID = "1daacb2b-ece9-454d-8640-89d7cbcde89a"


def test_snapshot_records_the_state_of_everything_an_import_touches(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    storage = tmp_path / ".claude-session-imports"
    target = tmp_path / ".claude" / "projects" / "-p"
    target.mkdir(parents=True)
    (target / "old.jsonl").write_text("{}\n", encoding="utf-8")
    project = tmp_path / "proj"
    project.mkdir()
    (project / "CLAUDE.md").write_text("# mine\n", encoding="utf-8")

    snapshot_dir = create_snapshot(target, storage, project_path=project, new_session_id=SID)

    info = read_json(snapshot_dir / "snapshot_info.json")
    assert info["snapshot_version"] == SNAPSHOT_VERSION
    assert info["target_directory"] == str(target) and info["backup_exists"] is True
    assert info["new_session_id"] == SID and info["project_path"] == str(project)
    assert info["history_file"] == {"path": str(tmp_path / ".claude" / "history.jsonl"), "existed": False}
    assert info["file_history_dir"] == {"path": str(tmp_path / ".claude" / "file-history" / SID), "existed": False}
    assert info["claude_md"] == {"path": str(project / "CLAUDE.md"), "existed": True}
    assert info["created_config_files"] == [] and info["claude_md_note"] is None
    assert (snapshot_dir / "projects" / "-p" / "old.jsonl").is_file()
    assert (snapshot_dir / "CLAUDE.md").read_text(encoding="utf-8") == "# mine\n"


def test_record_import_artifacts_updates_the_snapshot_info(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    storage = tmp_path / ".claude-session-imports"
    snapshot_dir = create_snapshot(tmp_path / ".claude" / "projects" / "-p", storage,
                                   project_path=tmp_path / "proj", new_session_id=SID)

    record_import_artifacts(snapshot_dir, created_config_files=["/proj/.claude/commands/a.md"],
                            claude_md_note="\n\n## Imported Session Context\n")

    info = read_json(snapshot_dir / "snapshot_info.json")
    assert info["created_config_files"] == ["/proj/.claude/commands/a.md"]
    assert info["claude_md_note"] == "\n\n## Imported Session Context\n"
    assert info["new_session_id"] == SID, "other fields are kept"


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 10, 14, 12, 0, 0, tzinfo=tz or timezone.utc)


def test_two_imports_in_the_same_second_get_separate_logs(tmp_path):
    storage = tmp_path / "imports"
    manifest = {"session_id": "old", "export_name": "e"}

    with patch("ccsession.importing.import_log.datetime", _FrozenDatetime):
        first = log_import(storage, manifest, "new-1", tmp_path / "p" / "new-1.jsonl", {"n": 1})
        second = log_import(storage, manifest, "new-2", tmp_path / "p" / "new-2.jsonl", {"n": 2})

    assert first != second
    assert read_json(first)["new_session_id"] == "new-1"
    assert read_json(second)["new_session_id"] == "new-2"
    index = json.loads((storage / "index.json").read_text(encoding="utf-8"))
    assert len(index["imports"]) == 2
    assert sorted(index["imports"]) == [first.parent.name, second.parent.name]


def test_snapshot_keeps_a_copy_of_the_prompt_history(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    history = tmp_path / ".claude" / "history.jsonl"
    history.parent.mkdir(parents=True)
    history.write_text('{"display": "earlier"}\n', encoding="utf-8")
    storage = tmp_path / ".claude-session-imports"

    snapshot_dir = create_snapshot(tmp_path / ".claude" / "projects" / "-p", storage,
                                   project_path=tmp_path / "proj", new_session_id=SID)

    assert (snapshot_dir / "history.jsonl").read_text(encoding="utf-8") == '{"display": "earlier"}\n'
    assert read_json(snapshot_dir / "snapshot_info.json")["history_file"]["existed"] is True


def test_record_import_artifacts_merges_what_each_step_reports(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    storage = tmp_path / ".claude-session-imports"
    snapshot_dir = create_snapshot(tmp_path / ".claude" / "projects" / "-p", storage,
                                   project_path=tmp_path / "proj", new_session_id=SID)

    record_import_artifacts(snapshot_dir, appended_history_lines=['{"display": "fix it"}'])
    record_import_artifacts(snapshot_dir, created_config_files=["/p/.claude/commands/a.md"],
                            created_config_dirs=["/p/.claude/commands", "/p/.claude"])
    record_import_artifacts(snapshot_dir, claude_md_note="\n\n## Imported Session Context\n")

    info = read_json(snapshot_dir / "snapshot_info.json")
    assert info["appended_history_lines"] == ['{"display": "fix it"}']
    assert info["created_config_files"] == ["/p/.claude/commands/a.md"]
    assert info["created_config_dirs"] == ["/p/.claude/commands", "/p/.claude"]
    assert info["claude_md_note"] == "\n\n## Imported Session Context\n"


def test_a_log_directory_claimed_by_another_process_is_skipped(tmp_path):
    """The index may not mention a directory another import just created."""
    storage = tmp_path / "imports"
    (storage / "2026-10-14-120000").mkdir(parents=True)
    with patch("ccsession.importing.import_log.datetime", _FrozenDatetime):
        log_path = log_import(storage, {"session_id": "old", "export_name": "e"}, "new-1",
                              tmp_path / "p" / "new-1.jsonl", {})
    assert log_path.parent.name == "2026-10-14-120000-2"


def test_snapshot_records_which_export_it_protects(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    snapshot_dir = create_snapshot(tmp_path / ".claude" / "projects" / "-p", tmp_path / ".claude-session-imports",
                                   project_path=tmp_path / "proj", new_session_id=SID,
                                   export_name="my-export", export_path=tmp_path / "exports" / "my-export")

    info = read_json(snapshot_dir / "snapshot_info.json")
    assert info["export_name"] == "my-export"
    assert info["export_path"] == str(tmp_path / "exports" / "my-export")


def test_log_import_with_a_dangling_storage_symlink_fails_fast(tmp_path):
    import os
    import pytest
    if os.name == "nt":
        pytest.skip("symlinks need privileges on Windows")
    storage = tmp_path / "storage"
    os.symlink(tmp_path / "missing-target", storage)

    with pytest.raises(OSError):
        log_import(storage, {"session_id": "old", "export_name": "e"}, "n", tmp_path / "n.jsonl", {})


def test_an_unreadable_index_still_gets_the_import_logged(tmp_path, capsys):
    storage = tmp_path / "imports"
    storage.mkdir()
    (storage / "index.json").write_text("", encoding="utf-8")

    log_path = log_import(storage, {"session_id": "old", "export_name": "e"}, "new-1", tmp_path / "p" / "new-1.jsonl", {})

    assert read_json(log_path)["new_session_id"] == "new-1"
    index = json.loads((storage / "index.json").read_text(encoding="utf-8"))
    assert list(index["imports"]) == [log_path.parent.name]
    assert list(storage.glob("index.json.corrupt*")), "the unreadable index is kept for inspection"


def test_stale_staging_directories_are_cleared_and_a_stranded_snapshot_recovered(tmp_path, monkeypatch):
    """A killed import leaves pre-import-snapshot.tmp-<pid>; a swap interrupted between
    its two renames leaves the previous snapshot as pre-import-snapshot.old-<pid>."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    storage = tmp_path / ".claude-session-imports"
    (storage / "pre-import-snapshot.tmp-99999").mkdir(parents=True)
    stranded = storage / "pre-import-snapshot.old-99998"
    stranded.mkdir()
    (stranded / "snapshot_info.json").write_text('{"timestamp": "2026-01-01T00:00:00Z"}', encoding="utf-8")

    from ccsession.importing.snapshot import recover_snapshot_slot
    recover_snapshot_slot(storage)

    assert sorted(p.name for p in storage.iterdir()) == ["pre-import-snapshot"]
    assert (storage / "pre-import-snapshot" / "snapshot_info.json").read_text(encoding="utf-8").startswith('{"timestamp": "2026-01-01')


def test_a_failed_swap_puts_the_previous_snapshot_back(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    storage = tmp_path / ".claude-session-imports"
    previous = storage / "pre-import-snapshot"
    previous.mkdir(parents=True)
    (previous / "snapshot_info.json").write_text('{"timestamp": "2026-01-01T00:00:00Z"}', encoding="utf-8")
    import ccsession.importing.snapshot as snapshot_module
    real_replace = snapshot_module.os.replace
    calls = []

    def fail_second(src, dst):
        calls.append(dst)
        if len(calls) == 2:
            raise PermissionError("sharing violation")
        return real_replace(src, dst)

    monkeypatch.setattr(snapshot_module.os, "replace", fail_second)
    import pytest
    with pytest.raises(PermissionError):
        create_snapshot(tmp_path / ".claude" / "projects" / "-p", storage, project_path=tmp_path / "proj", new_session_id=SID)

    assert sorted(p.name for p in storage.iterdir()) == ["pre-import-snapshot"]
    assert (previous / "snapshot_info.json").read_text(encoding="utf-8").startswith('{"timestamp": "2026-01-01')
