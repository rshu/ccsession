"""Restore a session's per-session directory and prompt history from an export."""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from ccsession.importing.remap import RemapPlan, remap_record, remap_records
from ccsession.importing.session_io import read_session_jsonl
from ccsession.importing.validation import resolve_export_path
from ccsession.paths import get_history_file

_EMPTY_MARKER = '_empty'


@dataclass(frozen=True)
class SessionDirImport:
    """What `import_session_dir` restored."""

    files: int
    agents: int


def import_session_dir(export_path: Path, manifest: dict, target_session_dir: Path,
                       plan: RemapPlan) -> SessionDirImport:
    """Restore ``<project-dir>/<session-id>/`` from an export.

    The export carries a verbatim mirror under ``session/session-dir/``. Every
    ``.jsonl`` under ``subagents/`` is a transcript and every ``.json`` there a
    sidecar: both are rewritten through ``plan`` (file names, which carry the agent
    id, never change). Every other file is copied as is.

    Raises:
        FileExistsError: if ``target_session_dir`` already contains files.
    """
    sources = list(_iter_sources(export_path, manifest))
    if not sources:
        return SessionDirImport(files=0, agents=0)
    if target_session_dir.exists() and any(target_session_dir.iterdir()):
        raise FileExistsError(
            f"Session directory already exists and is not empty: {target_session_dir}\n"
            "Import aborted to prevent mixing two sessions' files."
        )

    files = agents = 0
    for source, relative in sources:
        target = target_session_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if relative.parent.name == 'subagents' and source.suffix == '.jsonl':
            _write_jsonl(remap_records(read_session_jsonl(source), plan), target)
            agents += 1
        elif relative.parent.name == 'subagents' and source.suffix == '.json':
            _write_json(remap_record(_read_json(source), plan), target)
        else:
            shutil.copy2(source, target)
        files += 1
    return SessionDirImport(files=files, agents=agents)


def import_history(export_path: Path, manifest: dict, plan: RemapPlan,
                   new_project_path: str | Path) -> int:
    """Append the session's prompt-history records to ``<claude-dir>/history.jsonl``.

    Records are rewritten to the new session id and project path. A record whose
    ``sessionId``, ``timestamp`` and ``display`` already exist in the history file is
    skipped so a repeated import does not duplicate prompts. Returns the number of
    records added.
    """
    relative = manifest.get('session_data', {}).get('history')
    if not relative:
        return 0
    source = resolve_export_path(export_path, relative)
    if not source.is_file():
        return 0

    history_file = get_history_file()
    existing: set = set()
    if history_file.is_file():
        for record in read_session_jsonl(history_file):
            existing.add(_history_key(record))

    added = 0
    history_file.parent.mkdir(parents=True, exist_ok=True)
    with open(history_file, 'a', encoding='utf-8') as out:
        for record in read_session_jsonl(source):
            rewritten = remap_record(record, plan)
            rewritten['sessionId'] = plan.new_session_id
            rewritten['project'] = str(new_project_path)
            key = _history_key(rewritten)
            if key in existing:
                continue
            existing.add(key)
            out.write(json.dumps(rewritten, ensure_ascii=False) + '\n')
            added += 1
    return added


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
            yield source, source.relative_to(root)


def _read_json(path: Path) -> dict:
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def _write_json(data: dict, path: Path) -> None:
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)


def _write_jsonl(records: list, path: Path) -> None:
    with open(path, 'w', encoding='utf-8') as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + '\n')


def _history_key(record: dict) -> tuple:
    return (record.get('sessionId'), record.get('timestamp'), record.get('display'))
