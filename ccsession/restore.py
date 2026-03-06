from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from ccsession.constants import MAX_DISPLAY_ITEMS
from ccsession.paths import get_import_storage_dir, get_snapshot_dir
from ccsession.utils import parse_iso_timestamp, read_json


def get_snapshot_info() -> dict:
    """Get information about the current pre-import snapshot.

    Returns:
        dict: Snapshot information including:
            - exists: bool - Whether a snapshot exists
            - timestamp: str - When the snapshot was created (ISO format)
            - target_directory: str - The directory that was backed up
            - backup_exists: bool - Whether the snapshot contains actual backup data
            - backup_path: str - Path to the backup content (if exists)
            - age_hours: float - Hours since snapshot was created

    Raises:
        FileNotFoundError: If no snapshot exists
    """
    snapshot_dir = get_snapshot_dir()
    info_path = snapshot_dir / 'snapshot_info.json'

    if not info_path.exists():
        raise FileNotFoundError(
            "No pre-import snapshot found.\n"
            "A snapshot is only created when you run ccsession.py import.\n"
            f"Expected location: {snapshot_dir}"
        )

    info = read_json(info_path)

    # Calculate age
    try:
        snapshot_time = parse_iso_timestamp(info['timestamp'])
        now = datetime.now(snapshot_time.tzinfo)
        age_hours = (now - snapshot_time).total_seconds() / 3600
    except (ValueError, KeyError, TypeError):
        age_hours = None

    # Check for backup content
    backup_path = None
    if info.get('backup_exists'):
        target_dir = Path(info['target_directory'])
        backup_path = snapshot_dir / 'projects' / target_dir.name
        if not backup_path.exists():
            backup_path = None

    return {
        'exists': True,
        'timestamp': info.get('timestamp'),
        'target_directory': info.get('target_directory'),
        'backup_exists': info.get('backup_exists', False),
        'backup_path': str(backup_path) if backup_path else None,
        'age_hours': age_hours
    }


def get_last_import_info() -> dict | None:
    """Get information about the most recent import.

    Returns:
        dict: Import information or None if no imports recorded
    """
    index_path = get_import_storage_dir() / 'index.json'

    if not index_path.exists():
        return None

    index = read_json(index_path)

    imports = index.get('imports', {})
    if not imports:
        return None

    # Get the most recent import
    latest_key = max(imports.keys())
    latest = imports[latest_key]

    return {
        'import_id': latest_key,
        'session_name': latest.get('session_name'),
        'source_path': latest.get('source_path'),
        'imported_at': latest.get('imported_at')
    }


def restore_snapshot(force: bool = False) -> dict:
    """Restore from pre-import snapshot.

    This is a DESTRUCTIVE operation that:
    1. Removes the current state of the target directory
    2. Restores the pre-import state (or leaves empty if no prior content)

    Args:
        force: Skip confirmation prompt (DANGEROUS)

    Returns:
        dict: Restore summary

    Raises:
        FileNotFoundError: If no snapshot exists
        RuntimeError: If restore fails
    """
    snapshot_info = get_snapshot_info()
    target_dir = Path(snapshot_info['target_directory'])
    snapshot_dir = get_snapshot_dir()

    # Show what will happen
    print("\n" + "=" * 60)
    print("\u26a0\ufe0f  PRE-IMPORT SNAPSHOT RESTORE")
    print("=" * 60)
    print(f"\nSnapshot created: {snapshot_info['timestamp']}")
    if snapshot_info['age_hours'] is not None:
        print(f"Snapshot age: {snapshot_info['age_hours']:.1f} hours ago")
    print(f"\nTarget directory: {target_dir}")

    if snapshot_info['backup_exists']:
        print(f"\nRestore action: REPLACE current content with snapshot backup")
        print(f"Backup location: {snapshot_info['backup_path']}")
    else:
        print(f"\nRestore action: DELETE imported content (directory was empty before)")

    # Show what will be lost
    last_import = get_last_import_info()
    if last_import:
        print(f"\nMost recent import:")
        print(f"  - Session: {last_import['session_name']}")
        print(f"  - Imported: {last_import['imported_at']}")

    # List current session files that will be affected
    if target_dir.exists():
        session_files = list(target_dir.glob('*.jsonl'))
        if session_files:
            print(f"\nSession files that will be affected ({len(session_files)}):")
            for sf in session_files[:MAX_DISPLAY_ITEMS]:
                print(f"  - {sf.name}")
            if len(session_files) > MAX_DISPLAY_ITEMS:
                print(f"  ... and {len(session_files) - MAX_DISPLAY_ITEMS} more")

    print("\n" + "-" * 60)
    print("\u26a0\ufe0f  WARNING: This operation is DESTRUCTIVE and IRREVERSIBLE!")
    print("    Any sessions created AFTER the import will be LOST.")
    print("-" * 60)

    # Confirmation
    if not force:
        print("\nTo proceed, type 'RESTORE' (all caps): ", end='')
        confirmation = input().strip()

        if confirmation != 'RESTORE':
            print("\n\u274c Restore cancelled. You typed:", repr(confirmation))
            return {'restored': False, 'reason': 'cancelled'}

    # Perform restore
    print("\n\U0001f504 Restoring...")

    try:
        if snapshot_info['backup_exists'] and snapshot_info['backup_path']:
            backup_path = Path(snapshot_info['backup_path'])

            # Remove current target directory
            if target_dir.exists():
                shutil.rmtree(target_dir)
                print(f"   \u2713 Removed current: {target_dir}")

            # Restore from backup
            shutil.copytree(backup_path, target_dir)
            print(f"   \u2713 Restored from: {backup_path}")

        else:
            # No prior content - just delete the target directory
            if target_dir.exists():
                shutil.rmtree(target_dir)
                print(f"   \u2713 Removed: {target_dir}")
            else:
                print(f"   \u2713 Directory already empty: {target_dir}")

        # Clean up snapshot after successful restore
        if snapshot_dir.exists():
            shutil.rmtree(snapshot_dir)
            print(f"   \u2713 Cleaned up snapshot")

        print("\n\u2705 Restore complete!")
        print("   The state before the import has been restored.")

        return {
            'restored': True,
            'target_directory': str(target_dir),
            'had_backup': snapshot_info['backup_exists']
        }

    except Exception as e:
        print(f"\n\u274c Restore failed: {e}")
        print("   The snapshot has NOT been deleted.")
        print("   You may need to manually restore from:")
        print(f"   {snapshot_dir}")
        raise RuntimeError(f"Restore failed: {e}")


def show_info() -> int:
    """Display snapshot information without restoring."""
    try:
        info = get_snapshot_info()
    except FileNotFoundError as e:
        print(f"\u274c {e}")
        return 1

    print("\n\U0001f4f8 Pre-Import Snapshot Information")
    print("=" * 50)
    print(f"Snapshot exists: Yes")
    print(f"Created: {info['timestamp']}")
    if info['age_hours'] is not None:
        print(f"Age: {info['age_hours']:.1f} hours")
    print(f"\nTarget directory: {info['target_directory']}")
    print(f"Had existing content: {'Yes' if info['backup_exists'] else 'No'}")

    if info['backup_path']:
        print(f"Backup location: {info['backup_path']}")
        # Show backup contents
        backup_path = Path(info['backup_path'])
        if backup_path.exists():
            session_files = list(backup_path.glob('*.jsonl'))
            print(f"\nBackup contains {len(session_files)} session file(s)")

    last_import = get_last_import_info()
    if last_import:
        print(f"\nMost recent import:")
        print(f"  Session: {last_import['session_name']}")
        print(f"  Imported: {last_import['imported_at']}")

    print(f"\nTo restore: python ccsession.py restore --restore")

    return 0
