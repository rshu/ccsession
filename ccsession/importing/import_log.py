from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from ccsession.utils import utc_now_iso, read_json, write_json


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
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d-%H%M%S')
    log_dir = import_storage_dir / timestamp
    log_dir.mkdir(parents=True, exist_ok=True)

    log_content = {
        'import_timestamp': utc_now_iso(),
        'original_session_id': manifest.get('session_id'),
        'new_session_id': new_session_id,
        'original_export_name': manifest.get('export_name'),
        'target_session_file': str(target_path),
        'summary': summary
    }

    log_path = log_dir / 'import.log'
    write_json(log_path, log_content)

    # Update index
    index_path = import_storage_dir / 'index.json'
    if index_path.exists():
        index = read_json(index_path)
    else:
        index = {'last_snapshot_taken': None, 'imports': {}}

    index['imports'][timestamp] = {
        'session_name': manifest.get('export_name'),
        'source_path': str(target_path.parent),
        'imported_at': log_content['import_timestamp']
    }
    index['last_snapshot_taken'] = utc_now_iso()

    write_json(index_path, index)

    return log_path
