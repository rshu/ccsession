"""Restore the project's ``.claude/`` configuration from an export."""
from __future__ import annotations

import os
import uuid
from pathlib import Path

from ccsession.errors import InvalidExportError
from ccsession.importing.validation import resolve_export_path
from ccsession.output import warn
from ccsession.utils import copy_file_writable, file_digest

CONFIG_TYPES = ('commands', 'skills', 'hooks', 'agents', 'rules')


def _planned_copies(config_type: str, export_path: Path, relative_paths: list,
                    project_claude_dir: Path) -> list:
    """(source, target) pairs for one config type, with every manifest path checked.

    A manifest is untrusted input: each entry must be a string naming a file inside
    the export and inside ``config/<type>/``, so an export cannot plant files
    elsewhere in the project. Entries whose source file is missing are skipped.
    """
    type_root = (Path(export_path).resolve() / 'config' / config_type)
    planned = []
    for relative_path in relative_paths:
        if not isinstance(relative_path, str):
            raise InvalidExportError(
                f"Manifest config_snapshot.{config_type} contains {relative_path!r}, which is not a path.\n"
                "The export may be corrupted or tampered with."
            )
        source_path = resolve_export_path(export_path, relative_path)
        try:
            relative_target = source_path.relative_to(type_root)
        except ValueError:
            raise InvalidExportError(
                f"Manifest config path {relative_path!r} is not under config/{config_type}/.\n"
                "The export may be corrupted or tampered with."
            )
        if relative_target == Path('.'):
            raise InvalidExportError(
                f"Manifest config path {relative_path!r} names the config/{config_type}/ directory itself.\n"
                "The export may be corrupted or tampered with."
            )
        if source_path.is_file():
            planned.append((source_path, project_claude_dir / config_type / relative_target))
    return planned


def plan_config_import(export_path: Path, manifest: dict, project_path: Path) -> dict:
    """Validate every config path in the manifest and return the copies to make.

    Returns:
        dict: config type -> list of ``(source, target)`` pairs

    Raises:
        InvalidExportError: if any manifest path escapes the export or its type directory.
    """
    config_snapshot = manifest.get('config_snapshot')
    if config_snapshot is None:
        config_snapshot = {}
    if not isinstance(config_snapshot, dict):
        raise InvalidExportError("Manifest config_snapshot is not an object.\n"
                                 "The export may be corrupted or tampered with.")
    project_claude_dir = Path(project_path) / '.claude'
    plan = {}
    for name in CONFIG_TYPES:
        entries = config_snapshot.get(name)
        if entries is None:
            entries = []
        if not isinstance(entries, list):
            raise InvalidExportError(f"Manifest config_snapshot.{name} is not a list.\n"
                                     "The export may be corrupted or tampered with.")
        plan[name] = _planned_copies(name, export_path, entries, project_claude_dir)
    return plan


def _missing_ancestors(directory: Path) -> list:
    """``directory`` and its ancestors that do not exist yet, deepest first."""
    missing = []
    current = directory
    while not os.path.lexists(current):
        missing.append(current)
        if current.parent == current:
            break
        current = current.parent
    return missing


def new_config_summary() -> dict:
    """An empty result for :func:`apply_config_import`."""
    summary: dict = {name: 0 for name in CONFIG_TYPES}
    summary['conflicts'] = []
    summary['created'] = []
    summary['created_dirs'] = []
    return summary


def place_file(source: Path, target: Path, *, journal=None, kind: str) -> None:
    """Copy ``source`` to ``target`` so that a restore can always tell what happened.

    The journal gets the target, a temporary name and the content's digest before
    anything is written; the content goes to the temporary file and is renamed into
    place, so ``target`` either does not exist or holds the whole copy. A ``<kind>_done``
    entry follows. A restore removes a target that has no done entry only when it
    still holds exactly that content, so it never deletes a file someone else put
    there after a failed import.
    """
    tmp = target.with_name(f'.{target.name}.ccsession-tmp-{uuid.uuid4().hex}')
    if journal is not None:
        journal.record(kind, path=str(target), tmp=str(tmp), **file_digest(source))
    created_tmp = False
    try:
        # A stale temporary file or symlink must never be opened for writing. The
        # journal is durable before even this exclusive allocation happens.
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        created_tmp = True
        os.close(fd)
        copy_file_writable(source, tmp)
        os.replace(tmp, target)
    except BaseException:
        if created_tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        raise
    if journal is not None:
        journal.record(f'{kind}_done', path=str(target))


def apply_config_import(plan: dict, summary: dict | None = None, *, journal=None) -> dict:
    """Copy the planned files. Existing files, and symlinks (even dangling ones), are
    never overwritten or written through.

    ``summary`` may be a caller-owned :func:`new_config_summary` dict, updated as
    each file lands. With a ``journal`` every directory and file is recorded there
    *before* it is created (see :func:`place_file`).

    Returns:
        dict: per-type counts, ``conflicts`` (paths left alone), ``created`` (files
        written) and ``created_dirs`` (directories made for them, including
        ``.claude/`` itself when it did not exist), so a restore can remove exactly
        those.
    """
    if summary is None:
        summary = new_config_summary()

    for name in CONFIG_TYPES:
        for source_path, target_path in plan.get(name, []):
            if os.path.lexists(target_path) or any(
                    parent.is_symlink() or (os.path.lexists(parent) and not parent.is_dir())
                    for parent in target_path.parents):
                summary['conflicts'].append(str(target_path))
                continue
            for directory in reversed(_missing_ancestors(target_path.parent)):
                if journal is not None:
                    journal.record('config_dir', path=str(directory))
                if str(directory) not in summary['created_dirs']:
                    summary['created_dirs'].append(str(directory))
                directory.mkdir()
            place_file(source_path, target_path, journal=journal, kind='config_file')
            summary['created'].append(str(target_path))
            summary[name] += 1

    return summary


def import_config(export_path: Path, manifest: dict, project_path: Path) -> dict:
    """Import config files to the project's ``.claude/`` directory.

    Files keep the path they had below ``config/<type>/`` in the export (so
    ``config/skills/deploy/SKILL.md`` becomes ``.claude/skills/deploy/SKILL.md``).
    Nothing is written until every manifest path has been validated.
    """
    return apply_config_import(plan_config_import(export_path, manifest, project_path))


def claude_md_note(manifest: dict) -> str:
    """The import-context section appended to the project's CLAUDE.md."""
    original_context = manifest.get('original_context') or {}
    return f"""

## Imported Session Context

This session was imported via ccsession from another environment.

**Original environment:**
- User: {original_context.get('user', 'Unknown')}
- Path: {original_context.get('repo_path', 'Unknown')}
- Platform: {original_context.get('platform', 'Unknown')}
- Exported: {manifest.get('export_timestamp', 'Unknown')}
- Session ID: {manifest.get('session_id', 'Unknown')}

Some paths in the conversation history may reference the original environment.
"""


def claude_md_note_bytes(note: str) -> bytes:
    """The note as bytes; text UTF-8 cannot encode becomes '?'."""
    return note.encode('utf-8', 'replace')


def note_variants(note: str) -> list:
    """The note as it may appear in CLAUDE.md: with LF or with CRLF line endings."""
    lf = claude_md_note_bytes(note).replace(b'\r\n', b'\n')
    return [lf, lf.replace(b'\n', b'\r\n')]


def _uses_crlf(data: bytes) -> bool:
    crlf = data.count(b'\r\n')
    return crlf > 0 and crlf * 2 >= data.count(b'\n')


def _append_bytes(path: Path, data: bytes) -> None:
    with open(path, 'ab') as f:
        f.write(data)


def add_claude_md_note(project_path: Path, manifest: dict, *, journal=None) -> bool:
    """Append the import-context section to CLAUDE.md, creating the file if needed.

    The note uses the file's own line endings, and an existing note is recognised
    with either ending, so importing the same export twice leaves one note. The file
    is handled as bytes, so one that is not valid UTF-8 is otherwise untouched. A
    CLAUDE.md that is a dangling symlink is left alone. With a ``journal``, the
    file's size and the note are recorded before writing, so a restore can undo
    even a partly written note.

    Returns:
        bool: whether a note was written
    """
    path = Path(project_path) / 'CLAUDE.md'
    note = claude_md_note(manifest)
    if path.is_symlink() and not path.exists():
        warn(f"   \u26a0\ufe0f  {path} is a symlink to a missing file; the import note was not added")
        return False

    if path.exists():
        data = path.read_bytes()
        if any(variant in data for variant in note_variants(note)):
            return False
        lf, crlf = note_variants(note)
        payload = crlf if _uses_crlf(data) else lf
        created = False
        size_before = len(data)
    else:
        payload = b"# CLAUDE.md\n" + note_variants(note)[0]
        created = True
        size_before = 0

    if journal is not None:
        journal.record('claude_md', path=str(path), size_before=size_before,
                       note=payload.decode('utf-8'), created=created)
    _append_bytes(path, payload)
    return True
