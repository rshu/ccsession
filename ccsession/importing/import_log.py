from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from ccsession.output import warn
from ccsession.utils import ensure_private_dir, utc_now_iso, read_json, write_json


def _claim_log_dir(import_storage_dir: Path, existing_keys, base: str) -> Path:
    """Create ``<storage>/<base>/``, or ``<base>-2``, ``<base>-3``, ... when two imports
    land in the same second. The directory is the lock: ``mkdir`` without
    ``exist_ok`` fails for a concurrent import that claimed the same key. The
    storage directory itself must already exist."""
    key, n = base, 2
    while True:
        if key not in existing_keys:
            try:
                (import_storage_dir / key).mkdir(mode=0o700, exist_ok=False)
                return ensure_private_dir(import_storage_dir / key)
            except FileExistsError:
                pass
        key = f'{base}-{n}'
        n += 1


def _read_index(import_storage_dir: Path, stamp: str) -> dict:
    """index.json, or a fresh one when it is missing or unreadable (the unreadable
    file is kept as ``index.json.corrupt-<stamp>`` for inspection)."""
    index_path = import_storage_dir / 'index.json'
    if not index_path.exists():
        return {'last_snapshot_taken': None, 'imports': {}}
    try:
        index = read_json(index_path)
        if not isinstance(index, dict) or not isinstance(index.get('imports', {}), dict):
            raise ValueError("not an index object")
    except (OSError, ValueError) as e:
        corrupt = index_path.with_name(f'index.json.corrupt-{stamp}')
        try:
            index_path.replace(corrupt)
            warn(f"⚠️  The import index was unreadable ({e}); kept it as {corrupt} and started a new one")
        except OSError:
            warn(f"⚠️  The import index was unreadable ({e}); starting a new one")
        return {'last_snapshot_taken': None, 'imports': {}}
    index.setdefault('imports', {})
    return index


def log_import(import_storage_dir: Path, manifest: dict, new_session_id: str,
               target_path: Path, summary: dict) -> Path:
    """Log import details for recovery.

    Args:
        import_storage_dir: Base directory for import storage
        manifest: Parsed manifest dictionary
        new_session_id: New session UUID
        target_path: Path to imported session file
        summary: Import summary dictionary

    Returns:
        Path: Path to the import log
    """
    ensure_private_dir(import_storage_dir)
    base = datetime.now(timezone.utc).strftime('%Y-%m-%d-%H%M%S')
    index = _read_index(import_storage_dir, base)

    log_dir = _claim_log_dir(import_storage_dir, index['imports'], base)
    key = log_dir.name

    log_content = {
        'import_timestamp': utc_now_iso(),
        'original_session_id': manifest.get('session_id'),
        'new_session_id': new_session_id,
        'original_export_name': manifest.get('export_name'),
        'target_session_file': str(target_path),
        'summary': summary
    }

    log_path = log_dir / 'import.log'
    write_json(log_path, log_content, private=True)

    index['imports'][key] = {
        'session_name': manifest.get('export_name'),
        'source_path': str(target_path.parent),
        'imported_at': log_content['import_timestamp']
    }
    index['last_snapshot_taken'] = utc_now_iso()

    write_json(import_storage_dir / 'index.json', index, private=True)

    return log_path
