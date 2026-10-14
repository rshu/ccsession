"""Restore a session's per-session directory and prompt history from an export."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from ccsession.errors import InvalidExportError
from ccsession.importing.remap import RemapPlan, remap_record, remap_records
from ccsession.history_file import append_lines
from ccsession.importing.session_io import json_line, read_session_jsonl
from ccsession.importing.validation import resolve_export_path
from ccsession.paths import get_history_file
from ccsession.utils import copy_file_writable

_EMPTY_MARKER = '_empty'


@dataclass(frozen=True)
class SessionDirImport:
    """What `import_session_dir` restored."""

    files: int
    agents: int


@dataclass(frozen=True)
class PreparedFile:
    """One file of the session-directory mirror, ready to be written."""

    relative: Path
    kind: str          # 'jsonl' (records), 'json' (object) or 'copy' (source path)
    payload: object


def read_agent_transcripts(export_path: Path, manifest: dict) -> dict[str, list[dict]]:
    """Every transcript the mirror will restore, keyed by its source path.

    The mirror is authoritative: an omitted or incomplete agent_sessions inventory
    must not leave restored records outside the UUID map.
    """
    return {str(source.resolve()): read_session_jsonl(source)
            for source, relative in _iter_sources(export_path, manifest)
            if relative.parent.name == 'subagents' and relative.suffix == '.jsonl'}


def prepare_session_dir(export_path: Path, manifest: dict, plan: RemapPlan) -> list:
    """Read and rewrite the whole session-directory mirror without writing anything.

    Every ``.jsonl`` under ``subagents/`` is a transcript and every ``.json`` there a
    sidecar: both are parsed and rewritten through ``plan`` (file names, which carry
    the agent id, never change). Every other file is copied as is. Doing this before
    the pre-import snapshot means a malformed export is refused while nothing has
    changed.

    Raises:
        InvalidExportError: if a path escapes the export, a file is not UTF-8/JSON,
            or a record is nested too deeply to process.
    """
    prepared = []
    for source, relative in _iter_sources(export_path, manifest):
        name = relative.as_posix()
        try:
            if relative.parent.name == 'subagents' and source.suffix == '.jsonl':
                prepared.append(PreparedFile(relative, 'jsonl', remap_records(read_session_jsonl(source), plan)))
            elif relative.parent.name == 'subagents' and source.suffix == '.json':
                prepared.append(PreparedFile(relative, 'json', remap_record(_read_json(source), plan)))
            else:
                prepared.append(PreparedFile(relative, 'copy', source))
        except UnicodeDecodeError as e:
            raise InvalidExportError(f"Session file {name} is not valid UTF-8: {e}")
        except RecursionError:
            raise InvalidExportError(f"Session file {name} holds a record nested too deeply to process.")
        except (ValueError, OSError) as e:
            raise InvalidExportError(f"Sub-agent sidecar {name} is not valid JSON: {e}")
    return prepared


def write_session_dir(prepared: list, target_session_dir: Path) -> SessionDirImport:
    """Write a :func:`prepare_session_dir` result into ``target_session_dir``.

    Raises:
        FileExistsError: if ``target_session_dir`` already contains files.
    """
    if not prepared:
        return SessionDirImport(files=0, agents=0)
    if target_session_dir.is_symlink():
        raise FileExistsError(f"Session directory is a symlink: {target_session_dir}\n"
                              "Import aborted to prevent writing outside the session directory.")
    if target_session_dir.exists() and any(target_session_dir.iterdir()):
        raise FileExistsError(
            f"Session directory already exists and is not empty: {target_session_dir}\n"
            "Import aborted to prevent mixing two sessions' files."
        )

    files = agents = 0
    for item in prepared:
        target = target_session_dir / item.relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if item.kind == 'jsonl':
            _write_jsonl(item.payload, target)
            agents += 1
        elif item.kind == 'json':
            _write_json(item.payload, target)
        else:
            copy_file_writable(item.payload, target)
        files += 1
    return SessionDirImport(files=files, agents=agents)


def import_session_dir(export_path: Path, manifest: dict, target_session_dir: Path,
                       plan: RemapPlan) -> SessionDirImport:
    """Restore ``<project-dir>/<session-id>/`` from an export (prepare, then write).

    Raises:
        InvalidExportError: see :func:`prepare_session_dir`.
        FileExistsError: if ``target_session_dir`` already contains files.
    """
    return write_session_dir(prepare_session_dir(export_path, manifest, plan), target_session_dir)


def read_export_history(export_path: Path, manifest: dict) -> list:
    """The prompt-history records carried by an export, read before anything is written.

    Lines that are not JSON objects are skipped (Claude Code skips them as well).

    Raises:
        InvalidExportError: if the path escapes the export or the file is not UTF-8.
    """
    relative = manifest.get('session_data', {}).get('history')
    if not relative:
        return []
    source = resolve_export_path(export_path, relative)
    if not source.is_file():
        return []
    try:
        return read_session_jsonl(source)
    except UnicodeDecodeError as e:
        raise InvalidExportError(f"The export's prompt history {relative} is not valid UTF-8: {e}")
    except RecursionError:
        raise InvalidExportError("The export's prompt history holds a record nested too deeply to process.")


def _existing_history_keys(history_file: str) -> set:
    """Keys of the records already in the user's history; tolerant of anything odd in it."""
    keys: set = set()
    if not os.path.isfile(history_file):
        return keys
    with open(history_file, 'r', encoding='utf-8', errors='replace', newline='') as f:
        for line in f:
            try:
                record = json.loads(line)
            except (json.JSONDecodeError, RecursionError):
                continue
            if isinstance(record, dict):
                keys.add(_history_key(record))
    return keys


def rewrite_history_records(records: list, plan: RemapPlan, new_project_path: str | Path) -> list:
    """The export's history records rewritten to the new session id and project path.

    Raises:
        InvalidExportError: if a record is nested too deeply to process.
    """
    rewritten = []
    try:
        for record in records:
            new = remap_record(record, plan)
            new['sessionId'] = plan.new_session_id
            new['project'] = str(new_project_path)
            rewritten.append(new)
    except RecursionError:
        raise InvalidExportError("The export's prompt history holds a record nested too deeply to process.")
    return rewritten


def append_history(records: list, plan: RemapPlan, new_project_path: str | Path,
                   *, appended: list | None = None, journal=None) -> list:
    """Append prompt-history records to ``<claude-dir>/history.jsonl``.

    Records are rewritten to the new session id and project path. A record whose
    ``sessionId``, ``timestamp`` and ``display`` already exist in the history file is
    skipped so a repeated import does not duplicate prompts. The append holds Claude
    Code's history lock. Each line is recorded in ``journal`` and added to
    ``appended`` (a caller-owned list) just before it is written, so even after a
    failure part-way the restore knows exactly which lines to remove.

    Returns:
        list: the lines written, without their newline
    """
    if appended is None:
        appended = []
    rewritten = rewrite_history_records(records, plan, new_project_path)
    if not rewritten:
        return appended

    history_file = get_history_file()

    def lines():
        existing = _existing_history_keys(os.path.realpath(history_file))
        for record in rewritten:
            key = _history_key(record)
            if key in existing:
                continue
            existing.add(key)
            yield json_line(record)

    def before_each(line: str) -> None:
        if journal is not None:
            journal.record('history_line', line=line)
        appended.append(line)

    append_lines(history_file, lines(), before_each=before_each)
    return appended


def import_history(export_path: Path, manifest: dict, plan: RemapPlan,
                   new_project_path: str | Path) -> int:
    """Read the export's prompt history and append it; returns the number of records added."""
    return len(append_history(read_export_history(export_path, manifest), plan, new_project_path))


def validate_session_dir_sources(export_path: Path, manifest: dict) -> int:
    """Check every file the session-directory mirror would restore, before any write.

    Confines the mirror path to the export and parses each sub-agent ``.json``
    sidecar, so a corrupt export is refused before the pre-import snapshot is taken.
    Returns the number of files that would be restored.

    Raises:
        InvalidExportError: if the mirror path escapes the export or a sidecar is not JSON.
    """
    count = 0
    for source, relative in _iter_sources(export_path, manifest):
        if relative.parent.name == 'subagents' and source.suffix == '.json':
            try:
                _read_json(source)
            except (ValueError, OSError) as e:
                raise InvalidExportError(f"Sub-agent sidecar {relative.as_posix()} is not valid JSON: {e}")
        elif relative.parent.name == 'subagents' and source.suffix == '.jsonl':
            try:
                read_session_jsonl(source)
            except UnicodeDecodeError as e:
                raise InvalidExportError(f"Sub-agent transcript {relative.as_posix()} is not valid UTF-8: {e}")
        count += 1
    return count


def _iter_sources(export_path: Path, manifest: dict) -> Iterator[tuple]:
    """Yield (source_file, relative_target_path) pairs for the files to restore."""
    session_data = manifest.get('session_data', {})
    mirror = session_data.get('session_dir')
    if not mirror:
        return
    root = resolve_export_path(export_path, mirror)
    if not root.is_dir():
        return
    for source in sorted(p for p in root.rglob('*') if p.is_file()):
        if source.name != _EMPTY_MARKER:
            # A mirror can contain file symlinks even though its root is confined.
            # Check each resolved source before reading or copying its contents.
            resolve_export_path(export_path, str(source.relative_to(Path(export_path).resolve())))
            yield source, source.relative_to(root)


def _read_json(path: Path) -> dict:
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("the top level is not a JSON object")
    return data


def _write_json(data: dict, path: Path) -> None:
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write(json_line(data))


def _write_jsonl(records: list, path: Path) -> None:
    with open(path, 'w', encoding='utf-8', newline='') as f:
        for record in records:
            f.write(json_line(record) + '\n')


def _history_key(record: dict) -> tuple:
    """(sessionId, timestamp, display) as strings, so odd value types still hash."""
    parts = []
    for field in ('sessionId', 'timestamp', 'display'):
        try:
            parts.append(json.dumps(record.get(field), sort_keys=True, ensure_ascii=False))
        except (TypeError, ValueError, RecursionError):
            parts.append(repr(record.get(field)))
    return tuple(parts)
