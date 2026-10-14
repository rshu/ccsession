"""Importing the config snapshot and file history from an export."""
from __future__ import annotations

from pathlib import Path
import os
import sys
from types import SimpleNamespace

import pytest

from ccsession.errors import InvalidExportError
from ccsession.importing.auxiliary import import_file_history
from ccsession.importing.config import add_claude_md_note, import_config, place_file


def _export(root: Path, **snapshot) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    config = {"commands": [], "skills": [], "hooks": [], "agents": [], "rules": [], "settings": None, "claude_md": None}
    config.update(snapshot)
    return {"config_snapshot": config}


def _touch(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Manifest paths are untrusted
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad", ["../outside/secret.md", "/etc/hosts", "config/commands/../../outside/secret.md"])
def test_config_paths_outside_the_export_are_refused(tmp_path, bad):
    export = tmp_path / "export"
    manifest = _export(export, commands=[bad])
    _touch(tmp_path / "outside" / "secret.md", "leak")
    project = tmp_path / "project"
    project.mkdir()

    with pytest.raises(InvalidExportError, match="outside the export|not under config/commands"):
        import_config(export, manifest, project)

    assert not (project / ".claude").exists()


def test_config_path_under_another_type_directory_is_refused(tmp_path):
    """A manifest must not be able to drop a 'command' into .claude/hooks/ or vice versa."""
    export = tmp_path / "export"
    manifest = _export(export, commands=["config/hooks/run.sh"])
    _touch(export / "config" / "hooks" / "run.sh")
    project = tmp_path / "project"
    project.mkdir()

    with pytest.raises(InvalidExportError, match="config/commands"):
        import_config(export, manifest, project)

    assert not (project / ".claude").exists()


@pytest.mark.parametrize("bad", ["../outside/160c@v1", "/etc/hosts"])
def test_file_history_paths_outside_the_export_are_refused(tmp_path, monkeypatch, bad):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    export = tmp_path / "export"
    export.mkdir()
    _touch(tmp_path / "outside" / "160c@v1", "leak")
    manifest = {"session_data": {"file_history": [bad]}}

    with pytest.raises(InvalidExportError, match="outside the export"):
        import_file_history(export, manifest, "new-sid")

    assert not (tmp_path / ".claude" / "file-history" / "new-sid").exists()


def test_file_history_inside_the_export_is_copied(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    export = tmp_path / "export"
    _touch(export / "session" / "file-history" / "160c@v1", "snapshot")
    manifest = {"session_data": {"file_history": ["session/file-history/160c@v1"]}}

    assert import_file_history(export, manifest, "new-sid") == 1
    assert (tmp_path / ".claude" / "file-history" / "new-sid" / "160c@v1").read_text(encoding="utf-8") == "snapshot"


# ---------------------------------------------------------------------------
# Config trees are restored with their relative paths
# ---------------------------------------------------------------------------

def test_skill_directories_are_restored(tmp_path):
    export = tmp_path / "export"
    manifest = _export(export, skills=["config/skills/deploy/SKILL.md", "config/skills/deploy/references/steps.md"])
    _touch(export / "config" / "skills" / "deploy" / "SKILL.md", "# deploy")
    _touch(export / "config" / "skills" / "deploy" / "references" / "steps.md", "1.")
    project = tmp_path / "project"
    project.mkdir()

    summary = import_config(export, manifest, project)

    assert (project / ".claude" / "skills" / "deploy" / "SKILL.md").read_text(encoding="utf-8") == "# deploy"
    assert (project / ".claude" / "skills" / "deploy" / "references" / "steps.md").is_file()
    assert summary["skills"] == 2 and summary["conflicts"] == []
    assert sorted(summary["created"]) == sorted([
        str(project / ".claude" / "skills" / "deploy" / "SKILL.md"),
        str(project / ".claude" / "skills" / "deploy" / "references" / "steps.md"),
    ])


def test_flat_commands_from_a_2_1_0_export_still_land_in_commands(tmp_path):
    export = tmp_path / "export"
    manifest = _export(export, commands=["config/commands/review.md"])
    _touch(export / "config" / "commands" / "review.md", "r")
    project = tmp_path / "project"
    project.mkdir()

    summary = import_config(export, manifest, project)

    assert (project / ".claude" / "commands" / "review.md").is_file()
    assert summary["commands"] == 1


def test_existing_files_are_kept_and_reported_as_conflicts(tmp_path):
    export = tmp_path / "export"
    manifest = _export(export, commands=["config/commands/review.md"])
    _touch(export / "config" / "commands" / "review.md", "theirs")
    project = tmp_path / "project"
    _touch(project / ".claude" / "commands" / "review.md", "mine")

    summary = import_config(export, manifest, project)

    assert (project / ".claude" / "commands" / "review.md").read_text(encoding="utf-8") == "mine"
    assert summary["commands"] == 0 and summary["created"] == []
    assert summary["conflicts"] == [str(project / ".claude" / "commands" / "review.md")]


def test_missing_source_files_are_skipped(tmp_path):
    export = tmp_path / "export"
    export.mkdir()
    manifest = _export(export, rules=["config/rules/absent.md"])
    project = tmp_path / "project"
    project.mkdir()

    summary = import_config(export, manifest, project)

    assert summary["rules"] == 0 and summary["created"] == []


# ---------------------------------------------------------------------------
# CLAUDE.md note
# ---------------------------------------------------------------------------

MANIFEST = {"session_id": "sid-1", "export_timestamp": "2026-10-14T00:00:00Z",
            "original_context": {"user": "u", "repo_path": "/old", "platform": "darwin"}}


def test_claude_md_note_is_appended_once(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("# mine\n", encoding="utf-8")

    assert add_claude_md_note(tmp_path, MANIFEST) is True
    assert add_claude_md_note(tmp_path, MANIFEST) is False

    text = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert text.startswith("# mine\n") and text.count("## Imported Session Context") == 1


def test_claude_md_is_created_when_absent(tmp_path):
    assert add_claude_md_note(tmp_path, MANIFEST) is True
    text = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert text.startswith("# CLAUDE.md") and "sid-1" in text


# ---------------------------------------------------------------------------
# Second review round
# ---------------------------------------------------------------------------

def test_an_entry_naming_the_type_directory_itself_is_refused(tmp_path):
    """A regular file shipped as config/commands would be written over .claude/commands/."""
    export = tmp_path / "export"
    manifest = _export(export, commands=["config/commands"])
    _touch(export / "config" / "commands", "not a directory")
    project = tmp_path / "project"
    project.mkdir()

    with pytest.raises(InvalidExportError):
        import_config(export, manifest, project)

    assert not (project / ".claude").exists()


def test_non_string_entries_are_refused(tmp_path):
    export = tmp_path / "export"
    manifest = _export(export, commands=[5])
    project = tmp_path / "project"
    project.mkdir()

    with pytest.raises(InvalidExportError):
        import_config(export, manifest, project)


def test_created_directories_are_reported(tmp_path):
    export = tmp_path / "export"
    manifest = _export(export, commands=["config/commands/review.md"], skills=["config/skills/deploy/SKILL.md"])
    _touch(export / "config" / "commands" / "review.md", "r")
    _touch(export / "config" / "skills" / "deploy" / "SKILL.md", "s")
    project = tmp_path / "project"
    (project / ".claude" / "commands").mkdir(parents=True)

    summary = import_config(export, manifest, project)

    assert sorted(summary["created_dirs"]) == sorted([
        str(project / ".claude" / "skills"), str(project / ".claude" / "skills" / "deploy")])


def test_created_directories_include_dot_claude_when_it_did_not_exist(tmp_path):
    export = tmp_path / "export"
    manifest = _export(export, commands=["config/commands/review.md"])
    _touch(export / "config" / "commands" / "review.md", "r")
    project = tmp_path / "project"
    project.mkdir()

    summary = import_config(export, manifest, project)

    assert sorted(summary["created_dirs"]) == sorted([str(project / ".claude"), str(project / ".claude" / "commands")])


def test_claude_md_note_tolerates_content_that_is_not_utf8(tmp_path):
    (tmp_path / "CLAUDE.md").write_bytes(b"# caf\xe9\n")

    assert add_claude_md_note(tmp_path, MANIFEST) is True
    assert add_claude_md_note(tmp_path, MANIFEST) is False

    data = (tmp_path / "CLAUDE.md").read_bytes()
    assert data.startswith(b"# caf\xe9\n") and data.count(b"## Imported Session Context") == 1


@pytest.mark.parametrize("snapshot", [["config/commands/a.md"], "config/commands/a.md", 5])
def test_a_config_snapshot_of_the_wrong_shape_is_refused(tmp_path, snapshot):
    export = tmp_path / "export"
    export.mkdir()
    project = tmp_path / "project"
    project.mkdir()

    with pytest.raises(InvalidExportError):
        import_config(export, {"config_snapshot": snapshot}, project)


@pytest.mark.parametrize("value", ["config/commands/a.md", 5, True])
def test_a_config_type_that_is_not_a_list_is_refused(tmp_path, value):
    export = tmp_path / "export"
    export.mkdir()
    project = tmp_path / "project"
    project.mkdir()

    with pytest.raises(InvalidExportError):
        import_config(export, _export(export, commands=value), project)


def test_file_history_never_overwrites_an_existing_snapshot(tmp_path, monkeypatch):
    """With --preserve-session-id the session's file-history directory may already exist."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    existing = tmp_path / ".claude" / "file-history" / "sid"
    _touch(existing / "160c@v1", "local")
    export = tmp_path / "export"
    _touch(export / "session" / "file-history" / "160c@v1", "theirs")
    _touch(export / "session" / "file-history" / "160c@v2", "new")
    manifest = {"session_data": {"file_history": ["session/file-history/160c@v1", "session/file-history/160c@v2"]}}
    created = []

    assert import_file_history(export, manifest, "sid", created=created) == 1

    assert (existing / "160c@v1").read_text(encoding="utf-8") == "local"
    assert (existing / "160c@v2").read_text(encoding="utf-8") == "new"
    assert created == [str(existing / "160c@v2")]


# ---------------------------------------------------------------------------
# CRLF CLAUDE.md
# ---------------------------------------------------------------------------

def test_note_follows_a_crlf_claude_md(tmp_path):
    (tmp_path / "CLAUDE.md").write_bytes(b"# mine\r\nline\r\n")

    assert add_claude_md_note(tmp_path, MANIFEST) is True

    data = (tmp_path / "CLAUDE.md").read_bytes()
    assert b"## Imported Session Context\r\n" in data and b"\n" not in data.replace(b"\r\n", b"")
    assert add_claude_md_note(tmp_path, MANIFEST) is False


def test_note_is_found_after_its_line_endings_were_normalised(tmp_path):
    (tmp_path / "CLAUDE.md").write_bytes(b"# mine\n")
    assert add_claude_md_note(tmp_path, MANIFEST) is True
    data = (tmp_path / "CLAUDE.md").read_bytes()
    (tmp_path / "CLAUDE.md").write_bytes(data.replace(b"\n", b"\r\n"))

    assert add_claude_md_note(tmp_path, MANIFEST) is False


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
@pytest.mark.parametrize("linked_directory", [".claude", ".claude/commands"])
def test_config_files_are_not_written_through_parent_symlinks(tmp_path, linked_directory):
    export = tmp_path / "export"
    manifest = _export(export, commands=["config/commands/review.md"])
    _touch(export / "config" / "commands" / "review.md", "theirs")
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "dotfiles"
    outside.mkdir()
    link = project / linked_directory
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(outside, target_is_directory=True)

    summary = import_config(export, manifest, project)

    assert summary["commands"] == 0
    assert summary["conflicts"] == [str(project / ".claude" / "commands" / "review.md")]
    assert list(outside.iterdir()) == []
    assert link.is_symlink()


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
@pytest.mark.parametrize("linked_directory", ["file-history", "file-history/sid"])
def test_file_history_is_not_written_through_directory_symlinks(tmp_path, monkeypatch, linked_directory):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    export = tmp_path / "export"
    _touch(export / "session" / "file-history" / "160c@v1", "snapshot")
    manifest = {"session_data": {"file_history": ["session/file-history/160c@v1"]}}
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / ".claude" / linked_directory
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(outside, target_is_directory=True)

    with pytest.raises(FileExistsError, match="symlink"):
        import_file_history(export, manifest, "sid")

    assert list(outside.iterdir()) == []
    assert link.is_symlink()


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_a_stale_copy_temporary_symlink_cannot_overwrite_an_external_file(tmp_path):
    source = _touch(tmp_path / "source", "imported")
    target = tmp_path / "review.md"
    outside = _touch(tmp_path / "outside", "private")
    stale = target.with_name(f".{target.name}.ccsession-tmp-{os.getpid()}")
    stale.symlink_to(outside)

    place_file(source, target, kind="config_file")

    assert outside.read_text(encoding="utf-8") == "private"
    assert stale.is_symlink()
    assert not target.is_symlink() and target.read_text(encoding="utf-8") == "imported"


def test_copy_temporary_allocation_is_exclusive_and_keeps_colliding_files(tmp_path, monkeypatch):
    source = _touch(tmp_path / "source", "imported")
    target = tmp_path / "review.md"
    temporary = _touch(target.with_name(f".{target.name}.ccsession-tmp-fixed"), "existing")
    monkeypatch.setattr("ccsession.importing.config.uuid.uuid4", lambda: SimpleNamespace(hex="fixed"))

    with pytest.raises(FileExistsError):
        place_file(source, target, kind="config_file")

    assert temporary.read_text(encoding="utf-8") == "existing"
    assert not target.exists()


def test_a_copy_temporary_file_is_journaled_before_it_is_allocated(tmp_path):
    source = _touch(tmp_path / "source", "imported")
    target = tmp_path / "review.md"
    entries = []

    class Journal:
        def record(self, kind, **fields):
            if kind == "config_file":
                assert not os.path.lexists(fields["tmp"])
            entries.append((kind, fields))

    place_file(source, target, kind="config_file", journal=Journal())

    assert [kind for kind, fields in entries] == ["config_file", "config_file_done"]
    assert entries[0][1]["tmp"].startswith(str(target.with_name(f".{target.name}.ccsession-tmp-")))
    assert not Path(entries[0][1]["tmp"]).exists()
