"""The pre-import snapshot: enough state to undo one import completely."""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from ccsession.paths import get_claude_dir, get_file_history_dir, get_history_file
from ccsession.utils import (
    ensure_private_dir, force_rmtree, json_line, open_private, read_json, utc_now_iso, write_json,
)

SNAPSHOT_VERSION = 2
SNAPSHOT_DIR_NAME = 'pre-import-snapshot'
INFO_FILE_NAME = 'snapshot_info.json'
JOURNAL_FILE_NAME = 'journal.jsonl'
# Present while a restore of this snapshot is changing things; a new import must not
# replace the snapshot until that restore has finished.
RESTORE_MARKER = 'RESTORE_IN_PROGRESS'

# What an import reports at the end (the journal records the same things as they happen)
_LIST_ARTIFACTS = ('created_config_files', 'created_config_dirs', 'appended_history_lines',
                   'created_file_history_files')


class ImportJournal:
    """Append-only record, inside the snapshot, of every write an import makes.

    Each entry is written and flushed to disk *before* the write it describes, so
    whatever ends the import (an exception, Ctrl-C, SIGTERM, a closed terminal,
    SIGKILL) the restore knows exactly what may have been created.
    """

    def __init__(self, snapshot_dir: Path):
        self.path = Path(snapshot_dir) / JOURNAL_FILE_NAME

    def record(self, kind: str, **fields) -> None:
        line = json_line({'kind': kind, **fields})
        # Owner-only: entries can hold copies of prompt-history lines (Claude Code keeps those 0600)
        fd = open_private(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND)
        with os.fdopen(fd, 'wb') as f:
            f.write(line.encode('utf-8') + b'\n')
            f.flush()
            os.fsync(f.fileno())


def read_journal(snapshot_dir: Path) -> list:
    """The journal's entries; a torn last line (process killed mid-write) is ignored."""
    path = Path(snapshot_dir) / JOURNAL_FILE_NAME
    if not path.is_file():
        return []
    entries = []
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict) and isinstance(entry.get('kind'), str):
                entries.append(entry)
    return entries


def recover_snapshot_slot(import_storage_dir: Path) -> None:
    """Clean up after an import that was killed while building or swapping a snapshot.

    A snapshot stranded as ``pre-import-snapshot.old-<pid>`` (the swap was cut off
    between its two renames) is put back when the slot is empty; every other
    staging directory is a partial copy and is removed. Imports must not run
    concurrently, so no staging directory can belong to a live import.
    """
    storage = Path(import_storage_dir)
    if not storage.is_dir():
        return
    slot = storage / SNAPSHOT_DIR_NAME
    stranded = sorted((p for p in storage.glob(f'{SNAPSHOT_DIR_NAME}.old-*') if p.is_dir()),
                      key=lambda p: p.stat().st_mtime)
    if not slot.exists() and stranded:
        os.replace(stranded.pop(), slot)
    for leftover in [*storage.glob(f'{SNAPSHOT_DIR_NAME}.tmp-*'), *stranded]:
        force_rmtree(leftover, ignore_errors=True)


def create_snapshot(target_dir: Path, import_storage_dir: Path, *,
                    project_path: str | Path, new_session_id: str,
                    export_name: str | None = None, export_path: str | Path | None = None) -> Path:
    """Record the pre-import state of everything the import is about to touch.

    The project directory ``<claude-dir>/projects/<name>/`` is copied in full, and
    so are ``history.jsonl`` and the project's ``CLAUDE.md`` (for manual recovery).
    For the rest only prior existence is recorded: the import then writes an
    :class:`ImportJournal` entry before each change, and a restore undoes exactly
    what the journal lists.

    The new snapshot is built next to the old one and swapped in only when complete;
    if anything fails, the previous import's snapshot is left (or put back) in place.

    Raises:
        RuntimeError: if a restore of the current snapshot never finished; replacing
            it would lose the only copy of the sessions that restore was bringing back.

    Returns:
        Path: the snapshot directory
    """
    ensure_private_dir(import_storage_dir)
    recover_snapshot_slot(import_storage_dir)
    snapshot_dir = import_storage_dir / SNAPSHOT_DIR_NAME
    if (snapshot_dir / RESTORE_MARKER).exists():
        raise RuntimeError(
            "A restore of the previous import did not finish, and its snapshot holds the only copy "
            "of the sessions it was bringing back.\n"
            "Run `ccsession restore --restore` to finish it first (or delete "
            f"{snapshot_dir} to give that up), then import again."
        )

    building = import_storage_dir / f'{SNAPSHOT_DIR_NAME}.tmp-{os.getpid()}'
    force_rmtree(building, ignore_errors=True)
    try:
        building.mkdir(mode=0o700)
        ensure_private_dir(building)
        _fill_snapshot(building, target_dir, project_path=project_path, new_session_id=new_session_id,
                       export_name=export_name, export_path=export_path)
    except BaseException:
        force_rmtree(building, ignore_errors=True)
        raise

    retired = import_storage_dir / f'{SNAPSHOT_DIR_NAME}.old-{os.getpid()}'
    force_rmtree(retired, ignore_errors=True)
    moved_old = False
    try:
        if snapshot_dir.exists():
            os.replace(snapshot_dir, retired)
            moved_old = True
        os.replace(building, snapshot_dir)
    except BaseException:
        if moved_old and not snapshot_dir.exists():
            os.replace(retired, snapshot_dir)
        force_rmtree(building, ignore_errors=True)
        raise
    force_rmtree(retired, ignore_errors=True)
    return snapshot_dir


def _fill_snapshot(snapshot_dir: Path, target_dir: Path, *, project_path, new_session_id,
                   export_name, export_path) -> None:
    backup_exists = target_dir.exists()
    if backup_exists:
        target_backup = snapshot_dir / 'projects' / target_dir.name
        target_backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(target_dir, target_backup, symlinks=True)

    history_file = get_history_file()
    history_existed = history_file.is_file()
    if history_existed:
        shutil.copy2(history_file, snapshot_dir / 'history.jsonl')

    file_history_dir = get_file_history_dir(new_session_id)
    claude_md = Path(project_path) / 'CLAUDE.md'
    claude_md_existed = os.path.lexists(claude_md)
    if claude_md.is_file():
        shutil.copy2(claude_md, snapshot_dir / 'CLAUDE.md')

    info = {
        'snapshot_version': SNAPSHOT_VERSION,
        'timestamp': utc_now_iso(),
        'target_directory': str(target_dir),
        'backup_exists': backup_exists,
        'claude_dir': str(get_claude_dir()),
        'project_path': str(project_path),
        'new_session_id': new_session_id,
        'export_name': export_name,
        'export_path': str(export_path) if export_path is not None else None,
        'history_file': {'path': str(history_file), 'existed': history_existed},
        'file_history_dir': {'path': str(file_history_dir), 'existed': file_history_dir.exists()},
        'claude_md': {'path': str(claude_md), 'existed': claude_md_existed},
        'claude_md_note': None,
    }
    for field in _LIST_ARTIFACTS:
        info[field] = []
    os.close(open_private(snapshot_dir / JOURNAL_FILE_NAME, os.O_WRONLY | os.O_CREAT))
    write_json(snapshot_dir / INFO_FILE_NAME, info, private=True)


def record_import_artifacts(snapshot_dir: Path, *, created_config_files: list | None = None,
                            created_config_dirs: list | None = None,
                            appended_history_lines: list | None = None,
                            created_file_history_files: list | None = None,
                            claude_md_note: str | None = None) -> None:
    """Summarise in snapshot_info.json what the import created (the journal already
    holds the same information, entry by entry). Only the arguments given are
    updated; the file is replaced atomically."""
    info_path = snapshot_dir / INFO_FILE_NAME
    info = read_json(info_path)
    updates = {
        'created_config_files': created_config_files,
        'created_config_dirs': created_config_dirs,
        'appended_history_lines': appended_history_lines,
        'created_file_history_files': created_file_history_files,
    }
    for field, value in updates.items():
        if value is not None:
            info[field] = [str(v) for v in value]
    if claude_md_note is not None:
        info['claude_md_note'] = claude_md_note
    write_json(info_path, info, private=True)
