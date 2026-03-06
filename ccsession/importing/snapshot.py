from __future__ import annotations

import shutil
from pathlib import Path

from ccsession.utils import utc_now_iso, write_json


def create_snapshot(target_dir: Path, import_storage_dir: Path) -> Path:
    """Create pre-import backup of the target directory.

    Args:
        target_dir: Directory to backup
        import_storage_dir: Base directory for import storage

    Returns:
        Path: Path to the snapshot directory
    """
    snapshot_dir = import_storage_dir / 'pre-import-snapshot'

    # Remove old snapshot if exists
    if snapshot_dir.exists():
        shutil.rmtree(snapshot_dir)

    snapshot_dir.mkdir(parents=True, exist_ok=True)

    # Backup target directory if it exists
    if target_dir.exists():
        target_backup = snapshot_dir / 'projects' / target_dir.name
        target_backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(target_dir, target_backup)

    # Record snapshot timestamp
    write_json(snapshot_dir / 'snapshot_info.json', {
        'timestamp': utc_now_iso(),
        'target_directory': str(target_dir),
        'backup_exists': target_dir.exists()
    })

    return snapshot_dir
