"""Roll back the most recent import from the pre-import snapshot."""
from __future__ import annotations

import os
import shutil
import sys
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from ccsession.constants import MAX_DISPLAY_ITEMS
from ccsession.history_file import HistoryBusyError, rewrite_lines
from ccsession.importing.config import note_variants
from ccsession.importing.snapshot import (
    INFO_FILE_NAME, RESTORE_MARKER, SNAPSHOT_DIR_NAME, read_journal, recover_snapshot_slot,
)
from ccsession.output import error, info, prompt, success, warn
from ccsession.paths import get_claude_dir, get_import_storage_dir, get_projects_root, get_snapshot_dir
from ccsession.utils import file_digest, force_rmtree, force_unlink, parse_iso_timestamp, read_json, utc_now_iso

_LEGACY_STORAGE_DIR_NAME = '.claude-session-imports'
# Entries of <claude-dir>/projects/<name>/ that Claude Code reserves for the project
# itself (auto-memory, sync state, aliases); an import never writes them and a
# restore never rolls them back.
_KEPT_ENTRIES = frozenset({'memory', 'tiny_memory', 'bagel', 'cloud-snapshots',
                           'bridge-pointer.json', '.session-aliases'})
_STALE_AFTER_HOURS = 24


# ---------------------------------------------------------------------------
# Locating and reading the snapshot
# ---------------------------------------------------------------------------

def _is_legacy_snapshot(snapshot_dir: Path) -> bool:
    """True for a snapshot written by ccsession 2.1.0 (it records no Claude config dir)."""
    try:
        raw = read_json(snapshot_dir / INFO_FILE_NAME)
    except (OSError, ValueError):
        return False
    return isinstance(raw, dict) and 'claude_dir' not in raw


def find_snapshot_dir() -> Path:
    """The snapshot directory to act on.

    The configured location (``<CLAUDE_CONFIG_DIR>/ccsession-imports/`` or
    ``~/.claude-session-imports/``). When ``CLAUDE_CONFIG_DIR`` is set and that
    storage was never used, a snapshot ccsession 2.1.0 left in
    ``~/.claude-session-imports/`` is used (2.1.0 always wrote there). Once the
    configured storage has been used, that old snapshot is never picked up again.
    """
    configured = get_snapshot_dir()
    try:
        recover_snapshot_slot(configured.parent)
    except OSError:
        pass
    if (configured / INFO_FILE_NAME).exists() or (configured.parent / 'index.json').exists():
        return configured
    legacy = Path.home() / _LEGACY_STORAGE_DIR_NAME / SNAPSHOT_DIR_NAME
    if legacy != configured and (legacy / INFO_FILE_NAME).exists() and _is_legacy_snapshot(legacy):
        return legacy
    return configured


def find_import_storage_dir() -> Path:
    """The import storage that holds the snapshot being acted on (and its index)."""
    snapshot_dir = find_snapshot_dir()
    if (snapshot_dir / INFO_FILE_NAME).exists():
        return snapshot_dir.parent
    return get_import_storage_dir()


def _damaged(info_path: Path, why: str) -> RuntimeError:
    return RuntimeError(
        f"The pre-import snapshot is damaged: {why}.\n"
        f"Check {info_path} before retrying; nothing was changed."
    )


def _validated(raw, info_path: Path) -> dict:
    """snapshot_info.json with every field ccsession relies on type-checked."""
    if not isinstance(raw, dict):
        raise _damaged(info_path, "snapshot_info.json is not a JSON object")
    target = raw.get('target_directory')
    if not isinstance(target, str) or not target:
        raise _damaged(info_path, "it does not name the directory it backed up")
    for field in ('claude_dir', 'project_path', 'new_session_id', 'export_name', 'export_path',
                  'claude_md_note', 'timestamp'):
        if raw.get(field) is not None and not isinstance(raw[field], str):
            raise _damaged(info_path, f"{field} is not text")
    for field in ('created_config_files', 'created_config_dirs', 'appended_history_lines',
                  'created_file_history_files'):
        value = raw.get(field)
        if value is not None and (not isinstance(value, list) or not all(isinstance(v, str) for v in value)):
            raise _damaged(info_path, f"{field} is not a list of text")
    for field in ('history_file', 'file_history_dir', 'claude_md'):
        value = raw.get(field)
        if value is not None and (not isinstance(value, dict) or not isinstance(value.get('path'), str)):
            raise _damaged(info_path, f"{field} does not name a path")
    return raw


def _merge_journal(raw: dict, snapshot_dir: Path) -> dict:
    """Combine the end-of-import summary with the journal written before each change.

    Returns a dict of what to undo: files to remove (with the digest a file must
    still match when the journal never saw its copy complete), temporary files,
    directories, history lines and the CLAUDE.md append.
    """
    journal = read_journal(snapshot_dir)

    def files(kind: str, summary: list) -> tuple:
        targets: dict = {path: None for path in summary}
        tmps = []
        done = {e.get('path') for e in journal if e['kind'] == f'{kind}_done'}
        for e in journal:
            if e['kind'] != kind or not isinstance(e.get('path'), str):
                continue
            if isinstance(e.get('tmp'), str):
                tmps.append(e['tmp'])
            if e['path'] in done:
                targets[e['path']] = None
            elif e['path'] not in targets:
                targets[e['path']] = {'size': e.get('size'), 'sha256': e.get('sha256')}
        return targets, tmps

    config_files, config_tmps = files('config_file', raw.get('created_config_files') or [])
    fh_files, fh_tmps = files('file_history_file', raw.get('created_file_history_files') or [])
    config_dirs = list(dict.fromkeys(
        [*(raw.get('created_config_dirs') or []),
         *(e['path'] for e in journal if e['kind'] == 'config_dir' and isinstance(e.get('path'), str))]))
    journal_lines = [e['line'] for e in journal if e['kind'] == 'history_line' and isinstance(e.get('line'), str)]
    claude_md_entries = [e for e in journal if e['kind'] == 'claude_md' and isinstance(e.get('note'), str)]
    return {
        'config_files': config_files,
        'config_tmp_files': config_tmps,
        'created_config_files': list(config_files),
        'created_config_dirs': config_dirs,
        'file_history_files': fh_files,
        'file_history_tmp_files': fh_tmps,
        'created_file_history_files': list(fh_files),
        'appended_history_lines': journal_lines or list(raw.get('appended_history_lines') or []),
        'claude_md_append': claude_md_entries[-1] if claude_md_entries else None,
    }


def get_snapshot_info() -> dict:
    """Get information about the current pre-import snapshot.

    Returns:
        dict: Snapshot information including:
            - exists: bool - Whether a snapshot exists
            - snapshot_dir: str - Where the snapshot lives
            - timestamp: str - When the snapshot was created (ISO format)
            - target_directory: str - The directory that was backed up
            - backup_exists: bool - Whether the snapshot contains actual backup data
            - backup_path: str - Path to the backup content (if exists)
            - age_hours: float - Hours since snapshot was created
            - snapshot_version, claude_dir, project_path, new_session_id, export_name,
              export_path, history_file, file_history_dir, claude_md, claude_md_note,
              and what the import created (merged from its journal) - absent on
              snapshots written by ccsession 2.1.0

    Raises:
        FileNotFoundError: If no snapshot exists
        RuntimeError: If snapshot_info.json is malformed
    """
    snapshot_dir = find_snapshot_dir()
    info_path = snapshot_dir / INFO_FILE_NAME

    if not info_path.exists():
        raise FileNotFoundError(
            "No pre-import snapshot found.\n"
            "A snapshot is only created when you run `ccsession import`.\n"
            f"Expected location: {snapshot_dir}"
        )

    try:
        raw = read_json(info_path)
    except (OSError, ValueError, RecursionError) as e:
        raise _damaged(info_path, f"snapshot_info.json cannot be read ({e})")
    raw = _validated(raw, info_path)

    # Calculate age
    try:
        snapshot_time = parse_iso_timestamp(raw['timestamp'])
        age_hours = (datetime.now(timezone.utc) - snapshot_time).total_seconds() / 3600
    except (ValueError, KeyError, TypeError, AttributeError):
        age_hours = None

    # Check for backup content
    backup_path = None
    if raw.get('backup_exists'):
        candidate = snapshot_dir / 'projects' / Path(raw['target_directory']).name
        if candidate.is_dir() and not candidate.is_symlink():
            backup_path = candidate

    result = {
        'exists': True,
        'snapshot_dir': str(snapshot_dir),
        'timestamp': raw.get('timestamp'),
        'target_directory': raw['target_directory'],
        'backup_exists': bool(raw.get('backup_exists', False)),
        'backup_path': str(backup_path) if backup_path else None,
        'age_hours': age_hours,
        'snapshot_version': raw.get('snapshot_version', 1),
        'claude_dir': raw.get('claude_dir'),
        'project_path': raw.get('project_path'),
        'new_session_id': raw.get('new_session_id'),
        'export_name': raw.get('export_name'),
        'export_path': raw.get('export_path'),
        'history_file': raw.get('history_file'),
        'file_history_dir': raw.get('file_history_dir'),
        'claude_md': raw.get('claude_md'),
        'claude_md_note': raw.get('claude_md_note'),
    }
    result.update(_merge_journal(raw, snapshot_dir))
    return result


def _import_time(entry) -> datetime:
    try:
        return parse_iso_timestamp(entry.get('imported_at') or '')
    except (ValueError, TypeError, AttributeError):
        return datetime.min.replace(tzinfo=timezone.utc)


def get_last_import_info() -> dict | None:
    """Get information about the most recent logged import.

    Returns:
        dict: Import information or None if no imports recorded
    """
    index_path = find_import_storage_dir() / 'index.json'

    if not index_path.exists():
        return None

    try:
        index = read_json(index_path)
    except (OSError, ValueError, RecursionError):
        return None

    imports = index.get('imports', {}) if isinstance(index, dict) else {}
    if not isinstance(imports, dict):
        return None
    imports = {key: entry for key, entry in imports.items() if isinstance(entry, dict)}
    if not imports:
        return None

    # The most recent import by time; keys are '<timestamp>[-n]' and do not sort
    latest_key = max(imports, key=lambda key: (_import_time(imports[key]), key))
    latest = imports[latest_key]

    return {
        'import_id': latest_key,
        'session_name': latest.get('session_name'),
        'source_path': latest.get('source_path'),
        'imported_at': latest.get('imported_at')
    }


# ---------------------------------------------------------------------------
# Checks: a restore deletes things, so every recorded path is verified first
# ---------------------------------------------------------------------------

def _canonical(path) -> Path:
    """Absolute with '.' and '..' collapsed (a relative path is taken from the current
    directory, which is how a 2.1.0 snapshot recorded a relative CLAUDE_CONFIG_DIR)."""
    return Path(os.path.abspath(str(path)))


def _has_dot_dot(path) -> bool:
    return any(part == '..' for part in Path(path).parts)


def _is_canonical_uuid(value) -> bool:
    try:
        return str(uuid.UUID(value)) == value
    except (TypeError, ValueError, AttributeError):
        return False


def _same_dir(a, b) -> bool:
    return os.path.normcase(os.path.realpath(str(a))) == os.path.normcase(os.path.realpath(str(b)))


def _inside(path, root: Path) -> bool:
    """``path`` is ``root`` or below it, spelled without '..'."""
    if _has_dot_dot(path) or not Path(path).is_absolute():
        return False
    p = Path(path)
    return p == root or root in p.parents


def _check_claude_dir(snapshot_info: dict) -> None:
    """A snapshot is only restored with the Claude config directory it was taken for."""
    recorded = snapshot_info.get('claude_dir')
    if recorded and not _same_dir(_canonical(recorded), get_claude_dir()):
        info_path = Path(snapshot_info['snapshot_dir']) / INFO_FILE_NAME
        raise RuntimeError(
            f"Refusing to restore: this snapshot was taken for the Claude config directory {recorded}, "
            f"which is a different Claude config directory from the current one ({get_claude_dir()}).\n"
            "The config directory appears to have been moved or copied, so the paths the snapshot "
            f"records no longer describe this one. Check {info_path} before retrying; nothing was changed."
        )


def _target_dir(snapshot_info: dict) -> Path:
    return _canonical(snapshot_info['target_directory'])


def _check_target_dir(target_dir: Path, snapshot_info: dict) -> None:
    """The recorded target is replaced wholesale, so it must be exactly
    ``<claude-dir>/projects/<name>`` for the Claude directory the snapshot was taken
    for; a 2.1.0 snapshot (which did not record it) must match the current one."""
    recorded = snapshot_info.get('claude_dir')
    expected_root = _canonical(recorded) / 'projects' if recorded else get_projects_root()
    if target_dir.name in ('', '.', '..') or target_dir.parent != expected_root:
        hint = ("" if recorded else
                "\nThis snapshot was written by an older ccsession; run the restore with the "
                "CLAUDE_CONFIG_DIR that was in effect when the import ran.")
        raise RuntimeError(
            f"Refusing to restore: {snapshot_info['target_directory']} is not a project directory "
            f"under {expected_root}.{hint}\n"
            f"Check {Path(snapshot_info['snapshot_dir']) / INFO_FILE_NAME} before retrying; nothing was changed."
        )


def _check_backup(snapshot_info: dict) -> None:
    if snapshot_info['backup_exists'] and not snapshot_info['backup_path']:
        expected = Path(snapshot_info['snapshot_dir']) / 'projects' / Path(snapshot_info['target_directory']).name
        raise RuntimeError(
            "Refusing to restore: the snapshot is damaged (it records a backup of the project "
            f"directory, but {expected} is missing or not a directory).\n"
            "Deleting the current content would lose the sessions that existed before the import."
        )


def _expected_history_file(snapshot_info: dict) -> Path | None:
    claude_dir = snapshot_info.get('claude_dir')
    return _canonical(claude_dir) / 'history.jsonl' if claude_dir else None


def _expected_claude_md(snapshot_info: dict) -> Path | None:
    project = snapshot_info.get('project_path')
    if not project or not Path(project).is_absolute():
        return None
    return _canonical(project) / 'CLAUDE.md'


def _config_root(snapshot_info: dict) -> Path | None:
    project = snapshot_info.get('project_path')
    if not project or not Path(project).is_absolute():
        return None
    return _canonical(project) / '.claude'


def _file_history_dir(snapshot_info: dict) -> Path | None:
    """The imported session's file-history directory, if the snapshot names exactly that."""
    file_history = snapshot_info.get('file_history_dir')
    claude_dir = snapshot_info.get('claude_dir')
    sid = snapshot_info.get('new_session_id')
    if not file_history or not claude_dir or not _is_canonical_uuid(sid):
        return None
    path = Path(file_history['path'])
    expected = _canonical(claude_dir) / 'file-history' / sid
    return expected if not _has_dot_dot(path) and _canonical(path) == expected else None


# ---------------------------------------------------------------------------
# Planning: what a restore will do
# ---------------------------------------------------------------------------

def _signature(path: Path):
    """Cheap content fingerprint: size and mtime for a file, the sizes of every file
    for a directory (an in-place same-size rewrite inside a directory is not seen)."""
    if path.is_file():
        st = path.stat()
        return ('file', st.st_size, int(st.st_mtime))
    if path.is_dir():
        return ('dir', tuple(sorted((p.relative_to(path).as_posix(), p.stat().st_size)
                                    for p in path.rglob('*') if p.is_file())))
    return None


def _plan_project_dir(target_dir: Path, backup_path: Path | None) -> dict:
    """Top-level entries of the project directory grouped by what restore does to them."""
    current = {p.name: p for p in target_dir.iterdir()} if target_dir.is_dir() else {}
    backup = {p.name: p for p in backup_path.iterdir()} if backup_path and backup_path.is_dir() else {}
    plan = {'deleted': [], 'rolled_back': [], 'restored': [],
            'kept': sorted(name for name in current if name in _KEPT_ENTRIES)}
    for name in sorted(current):
        if name in _KEPT_ENTRIES:
            continue
        if name not in backup:
            plan['deleted'].append(name)
        elif _signature(current[name]) != _signature(backup[name]):
            plan['rolled_back'].append(name)
    plan['restored'] = sorted(name for name in backup if name not in current and name not in _KEPT_ENTRIES)
    return plan


def _print_list(show, heading: str, names: list) -> None:
    if not names:
        return
    show(f"\n{heading} ({len(names)}):")
    for name in names[:MAX_DISPLAY_ITEMS]:
        show(f"  - {name}")
    if len(names) > MAX_DISPLAY_ITEMS:
        show(f"  ... and {len(names) - MAX_DISPLAY_ITEMS} more")


def _describe_import(show, snapshot_info: dict, indent: str = "  ") -> None:
    """Which import this snapshot undoes: recorded in the snapshot itself, or for a
    2.1.0 snapshot, the most recent entry of the import index."""
    if snapshot_info.get('new_session_id'):
        show(f"\nImport being undone:")
        show(f"{indent}- Export: {snapshot_info.get('export_name') or 'unknown'}")
        if snapshot_info.get('export_path'):
            show(f"{indent}- From: {snapshot_info['export_path']}")
        show(f"{indent}- Imported session: {snapshot_info['new_session_id']}")
        return
    last_import = get_last_import_info()
    if last_import:
        show(f"\nMost recent import:")
        show(f"{indent}- Session: {last_import['session_name']}")
        show(f"{indent}- Imported: {last_import['imported_at']}")


def _age_text(hours: float) -> str:
    return f"{hours / 24:.0f} days" if hours >= 48 else f"{hours:.0f} hours"


def _warn_if_stale(snapshot_info: dict) -> None:
    hours = snapshot_info['age_hours']
    if hours is not None and hours > _STALE_AFTER_HOURS:
        warn(f"⚠️  This snapshot is {_age_text(hours)} old: everything written under the target "
             "directory since then is affected.")


def _print_plan(show, snapshot_info: dict, target_dir: Path, backup_path: Path | None, plan: dict) -> None:
    show("\n" + "=" * 60)
    show("⚠️  PRE-IMPORT SNAPSHOT RESTORE")
    show("=" * 60)
    show(f"\nSnapshot created: {snapshot_info['timestamp']}")
    if snapshot_info['age_hours'] is not None:
        show(f"Snapshot age: {snapshot_info['age_hours']:.1f} hours ago")
    _warn_if_stale(snapshot_info)
    show(f"\nTarget directory: {target_dir}")

    if backup_path:
        show(f"\nRestore action: REPLACE current content with snapshot backup")
        show(f"Backup location: {backup_path}")
    else:
        show(f"\nRestore action: DELETE imported content (directory was empty before)")

    _describe_import(show, snapshot_info)

    _print_list(show, "Session files that will be deleted (not in the snapshot)", plan['deleted'])
    _print_list(show, "Session files that will be rolled back to the snapshot (changed since)", plan['rolled_back'])
    _print_list(show, "Session files that will be restored from the snapshot (deleted since)", plan['restored'])
    if plan['kept']:
        show(f"\nKept as they are now: {', '.join(name + '/' for name in plan['kept'])} "
             "(Claude Code's project memory and state are never rolled back)")

    extras = _other_artifacts(snapshot_info)
    if extras:
        show("\nAlso undone:")
        for line in extras:
            show(f"  - {line}")

    show("\n" + "-" * 60)
    show("⚠️  WARNING: This operation is DESTRUCTIVE and IRREVERSIBLE!")
    show("    Everything written under the target directory since the import is lost:")
    show("    sessions created afterwards AND turns added to sessions that existed before.")
    show("-" * 60)


def _other_artifacts(snapshot_info: dict) -> list:
    """Human-readable lines for the non-project-dir items a restore will undo."""
    lines = []
    history = snapshot_info.get('history_file')
    appended = snapshot_info.get('appended_history_lines') or []
    expected_history = _expected_history_file(snapshot_info)
    if (history and appended and expected_history and _canonical(history['path']) == expected_history
            and expected_history.is_file()):
        lines.append(f"{len(appended)} prompt-history line(s) the import appended to {expected_history}")
    fh_dir = _file_history_dir(snapshot_info)
    if fh_dir and fh_dir.exists():
        if not snapshot_info['file_history_dir'].get('existed'):
            lines.append(f"file-history directory {fh_dir}")
        elif snapshot_info.get('file_history_files'):
            lines.append(f"{len(snapshot_info['file_history_files'])} file-history snapshot(s) "
                         f"the import added to {fh_dir}")
    root = _config_root(snapshot_info)
    created = [p for p in snapshot_info.get('config_files', {}) if root and _inside(p, root) and Path(p).is_file()]
    if created:
        shown = ', '.join(Path(p).name for p in created[:MAX_DISPLAY_ITEMS])
        more = f" and {len(created) - MAX_DISPLAY_ITEMS} more" if len(created) > MAX_DISPLAY_ITEMS else ''
        lines.append(f"{len(created)} config file(s) created by the import: {shown}{more}")
    claude_md = _expected_claude_md(snapshot_info)
    if (claude_md and claude_md.is_file() and snapshot_info.get('claude_md')
            and (snapshot_info.get('claude_md_append') or snapshot_info.get('claude_md_note'))):
        lines.append(f"the import note in {claude_md}")
    return lines


# ---------------------------------------------------------------------------
# Undo steps
# ---------------------------------------------------------------------------

def _replace_project_dir(target_dir: Path, backup_path: Path | None) -> None:
    """Make ``target_dir`` match the backup, leaving ``_KEPT_ENTRIES`` exactly as they are.

    The restored tree is built in a staging directory next to the target first; the
    kept entries are moved into it and the two are swapped by rename. If anything
    fails before the swap, the project directory is left as it was.
    """
    parent = target_dir.parent
    staging = parent / f'.ccsession-restore-{target_dir.name}-{os.getpid()}'
    aside = parent / f'.ccsession-discard-{target_dir.name}-{os.getpid()}'
    force_rmtree(staging, ignore_errors=True)
    force_rmtree(aside, ignore_errors=True)

    def skip_kept(directory, names):
        return [n for n in names if n in _KEPT_ENTRIES] if _canonical(directory) == _canonical(backup_path) else []

    try:
        if backup_path:
            shutil.copytree(backup_path, staging, symlinks=True, ignore=skip_kept)
        else:
            parent.mkdir(parents=True, exist_ok=True)
            staging.mkdir()
    except BaseException:
        force_rmtree(staging, ignore_errors=True)
        raise

    moved = []
    swapped_out = False
    try:
        if target_dir.exists():
            for name in sorted(_KEPT_ENTRIES):
                if os.path.lexists(target_dir / name):
                    os.replace(target_dir / name, staging / name)
                    moved.append(name)
            os.replace(target_dir, aside)
            swapped_out = True
        os.replace(staging, target_dir)
    except BaseException:
        if swapped_out and not target_dir.exists():
            os.replace(aside, target_dir)
        for name in moved:
            if os.path.lexists(staging / name) and not os.path.lexists(target_dir / name):
                os.replace(staging / name, target_dir / name)
        force_rmtree(staging, ignore_errors=True)
        raise
    force_rmtree(aside, ignore_errors=True)
    if aside.exists():
        warn(f"⚠️  Could not remove {aside}; delete it by hand")
    if not backup_path and not any(target_dir.iterdir()):
        target_dir.rmdir()


def _undo_history(snapshot_info: dict) -> int:
    """Drop exactly the prompt-history lines the import appended (and a line it was
    cut off writing); everything else, including prompts typed into the imported
    session afterwards, stays. Runs under Claude Code's history lock."""
    recorded = snapshot_info.get('appended_history_lines') or []
    history = snapshot_info.get('history_file')
    if not recorded or not history:
        return 0
    expected = _expected_history_file(snapshot_info)
    if expected is None or _has_dot_dot(history['path']) or _canonical(history['path']) != expected:
        warn(f"⚠️  Not touching {history['path']}: it is not the prompt history of {snapshot_info.get('claude_dir')}")
        return 0
    if not expected.is_file():
        return 0

    def decide(lines: list) -> list:
        to_remove = Counter(recorded)
        kept = []
        for i, raw in enumerate(lines):
            key = raw.rstrip(b'\r\n').decode('utf-8', 'surrogateescape')
            if to_remove.get(key):
                to_remove[key] -= 1
                continue
            is_torn_tail = i == len(lines) - 1 and not raw.endswith(b'\n') and key
            if is_torn_tail and any(n > 0 and line.startswith(key) for line, n in to_remove.items()):
                continue
            kept.append(raw)
        return kept

    try:
        return rewrite_lines(expected, decide, remove_if_empty=not history.get('existed'))
    except HistoryBusyError as e:
        warn(f"⚠️  {e}; the imported prompt-history lines were left in place")
        return 0


def _remove_recorded_files(targets: dict, tmps: list, root: Path, what: str) -> int:
    """Remove files the import wrote under ``root``.

    A file whose copy the journal saw complete is removed; one whose copy never
    completed is removed only if it still holds exactly the content the import was
    copying (anything else was put there by someone else). Symlinks are never
    removed.
    """
    removed = 0
    for path_str, digest in targets.items():
        path = Path(path_str)
        if not _inside(path, root):
            warn(f"⚠️  Not deleting {path}: it is outside {root}")
            continue
        if path.is_symlink() or not path.is_file():
            continue
        if digest is not None:
            try:
                if file_digest(path) != digest:
                    warn(f"⚠️  Left {path} in place: it is not the {what} the import was writing")
                    continue
            except OSError:
                continue
        force_unlink(path)
        removed += 1
    for tmp in tmps:
        if _inside(tmp, root) and os.path.lexists(tmp) and not os.path.islink(tmp):
            force_unlink(tmp)
    return removed


def _undo_file_history(snapshot_info: dict) -> int:
    """Remove what the import added under ``<claude-dir>/file-history/<session-id>/``.

    The directory is deleted when the import created it; when it already existed
    (``--preserve-session-id``) only the snapshots the import added are removed.
    Nothing happens unless the recorded path is exactly that directory for a
    UUID session id.
    """
    file_history = snapshot_info.get('file_history_dir')
    if not file_history:
        return 0
    path = _file_history_dir(snapshot_info)
    if path is None:
        warn(f"⚠️  Not touching {file_history['path']}: it is not the file-history directory "
             "of an imported session")
        return 0
    if not path.is_dir() or path.is_symlink():
        return 0
    if not file_history.get('existed'):
        force_rmtree(path)
        return 1
    return _remove_recorded_files(snapshot_info.get('file_history_files') or {},
                                  snapshot_info.get('file_history_tmp_files') or [], path, 'file-history snapshot')


def _undo_config_files(snapshot_info: dict) -> int:
    """Remove the config files and directories the import created, and nothing else."""
    config_root = _config_root(snapshot_info)
    if config_root is None:
        return 0
    removed = _remove_recorded_files(snapshot_info.get('config_files') or {},
                                     snapshot_info.get('config_tmp_files') or [], config_root, 'config file')
    # Deepest first, so a parent is empty by the time it is reached
    for created in sorted((snapshot_info.get('created_config_dirs') or []), key=lambda p: -len(Path(p).parts)):
        path = Path(created)
        if _inside(path, config_root) and path.is_dir() and not path.is_symlink() and not any(path.iterdir()):
            path.rmdir()
    return removed


def _undo_claude_md(snapshot_info: dict) -> str | None:
    """Remove the import note (even a partly written one); later edits are kept."""
    recorded = snapshot_info.get('claude_md')
    entry = snapshot_info.get('claude_md_append')
    note = (entry or {}).get('note') or snapshot_info.get('claude_md_note')
    if not recorded or not note:
        return None
    path = _expected_claude_md(snapshot_info)
    if path is None or _has_dot_dot(recorded['path']) or _canonical(recorded['path']) != path:
        warn(f"⚠️  Not touching {recorded['path']}: it is not the project's CLAUDE.md")
        return None
    if not path.is_file():
        return None

    data = path.read_bytes()
    variants = note_variants(note)
    new = None
    size_before = (entry or {}).get('size_before')
    if isinstance(size_before, int) and 0 <= size_before <= len(data):
        tail = data[size_before:]
        if not tail:
            return None
        if any(v.startswith(tail) for v in variants):
            new = data[:size_before]
    if new is None:
        for variant in variants:
            if variant in data:
                new = data.replace(variant, b'', 1)
                break
    if new is None:
        warn(f"⚠️  The import note was not found in {path}; left unchanged")
        return None

    created = entry.get('created') if entry else not recorded.get('existed')
    if created and new.strip() in (b'', b'# CLAUDE.md') and not path.is_symlink():
        force_unlink(path)
        return f"removed {path} (created by the import)"
    path.write_bytes(new)
    return f"removed the import note from {path}"


def restore_snapshot(force: bool = False) -> dict:
    """Restore the state recorded by the pre-import snapshot.

    This is a DESTRUCTIVE operation: the project directory is put back to the
    snapshot copy (or removed if it did not exist), Claude Code's own project
    entries under it excepted, then the prompt-history lines, file-history
    snapshots, config files and CLAUDE.md note of the import are undone.

    Args:
        force: Skip confirmation prompt (DANGEROUS)

    Returns:
        dict: Restore summary

    Raises:
        FileNotFoundError: If no snapshot exists
        RuntimeError: If the snapshot is malformed or names an unexpected target, or the restore fails
    """
    snapshot_info = get_snapshot_info()
    snapshot_dir = Path(snapshot_info['snapshot_dir'])
    _check_claude_dir(snapshot_info)
    target_dir = _target_dir(snapshot_info)
    _check_target_dir(target_dir, snapshot_info)
    _check_backup(snapshot_info)

    backup_path = Path(snapshot_info['backup_path']) if snapshot_info['backup_path'] else None
    plan = _plan_project_dir(target_dir, backup_path)

    # The plan is what the user is confirming, so it is shown even under --quiet
    show = info if force else prompt
    _print_plan(show, snapshot_info, target_dir, backup_path, plan)

    # Confirmation
    if not force:
        stdin = sys.stdin
        if stdin is None or not stdin.isatty():
            error("\n❌ Standard input is not a terminal, so the RESTORE confirmation cannot be read.")
            error("   Re-run with --yes to skip the prompt once you have read the plan above.")
            return {'restored': False, 'reason': 'no-tty'}
        try:
            confirmation = input("\nTo proceed, type 'RESTORE' (all caps): ").strip()
        except (EOFError, RuntimeError):
            confirmation = ''

        if confirmation != 'RESTORE':
            prompt(f"\n❌ Restore cancelled. You typed: {confirmation!r}")
            return {'restored': False, 'reason': 'cancelled'}

    # Perform restore
    info("\n\U0001f504 Restoring...")

    try:
        # Until the snapshot is removed at the end, a new import must not replace it
        (snapshot_dir / RESTORE_MARKER).write_text(utc_now_iso(), encoding='utf-8')

        had_target = target_dir.exists()
        _replace_project_dir(target_dir, backup_path)
        if backup_path:
            info(f"   ✓ Restored {target_dir} from: {backup_path}")
        elif had_target:
            info(f"   ✓ Removed the imported content of {target_dir}")
        else:
            info(f"   ✓ Directory already empty: {target_dir}")
        if plan['kept']:
            info(f"   ✓ Kept {', '.join(name + '/' for name in plan['kept'])} as it is")

        history_removed = _undo_history(snapshot_info)
        if history_removed:
            info(f"   ✓ Removed {history_removed} prompt-history line(s)")
        if _undo_file_history(snapshot_info):
            info(f"   ✓ Removed the imported file history")
        config_removed = _undo_config_files(snapshot_info)
        if config_removed:
            info(f"   ✓ Removed {config_removed} config file(s)")
        claude_md_result = _undo_claude_md(snapshot_info)
        if claude_md_result:
            info(f"   ✓ {claude_md_result}")

        # Clean up snapshot after successful restore
        force_rmtree(snapshot_dir)
        info(f"   ✓ Cleaned up snapshot")
    except BaseException as e:
        error(f"\n❌ The restore did not finish: {e or type(e).__name__}")
        error("   The snapshot has NOT been deleted and still holds the pre-import state:")
        error(f"   {snapshot_dir}")
        error("   Fix the cause, then run `ccsession restore --restore` again.")
        error("   Do not run `ccsession import` first: a new import would replace this snapshot.")
        if isinstance(e, Exception):
            raise RuntimeError(f"Restore failed: {e}") from e
        raise

    success("\n✅ Restore complete!")
    info("   The state before the import has been restored.")

    return {
        'restored': True,
        'target_directory': str(target_dir),
        'had_backup': snapshot_info['backup_exists'],
        'history_lines_removed': history_removed,
        'config_files_removed': config_removed,
        'claude_md': claude_md_result,
    }


def show_info() -> int:
    """Display snapshot information without restoring.

    The summary is the command's result, so it is printed even under ``--quiet``;
    the longer breakdown is informational, and problems are warnings.
    """
    try:
        snapshot_info = get_snapshot_info()
    except FileNotFoundError as e:
        error(f"❌ {e}")
        return 1

    success("\n\U0001f4f8 Pre-Import Snapshot Information")
    success("=" * 50)
    success(f"Created: {snapshot_info['timestamp']}")
    if snapshot_info['age_hours'] is not None:
        info(f"Age: {snapshot_info['age_hours']:.1f} hours")
    _warn_if_stale(snapshot_info)
    success(f"Target directory: {snapshot_info['target_directory']}")
    info(f"Snapshot location: {snapshot_info['snapshot_dir']}")
    info(f"Had existing content: {'Yes' if snapshot_info['backup_exists'] else 'No'}")
    if snapshot_info['backup_exists'] and not snapshot_info['backup_path']:
        warn("⚠️  The snapshot is damaged: its copy of the project directory is missing, "
             "so a restore will refuse to run.")

    if snapshot_info['backup_path']:
        info(f"Backup location: {snapshot_info['backup_path']}")
        backup_path = Path(snapshot_info['backup_path'])
        session_files = [p for p in backup_path.glob('*.jsonl') if not p.name.startswith('agent-')]
        info(f"\nBackup contains {len(session_files)} session file(s)")

    _describe_import(info, snapshot_info)
    extras = _other_artifacts(snapshot_info)
    if extras:
        info("A restore also undoes:")
        for line in extras:
            info(f"  - {line}")
    elif snapshot_info['snapshot_version'] < 2:
        info("\nThis snapshot was written by an older ccsession: a restore rolls back the project directory only.")
    if (Path(snapshot_info['snapshot_dir']) / RESTORE_MARKER).exists():
        warn("⚠️  A restore of this snapshot did not finish; run it again before importing.")

    success(f"\nTo restore: ccsession restore --restore")

    return 0
