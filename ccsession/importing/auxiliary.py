from __future__ import annotations

import shutil
from pathlib import Path

from ccsession.paths import get_file_history_dir


def import_file_history(export_path: Path, manifest: dict, new_session_id: str) -> int:
    """Import file history snapshots to ~/.claude/file-history/<sessionId>/.

    Args:
        export_path: Path to the export directory
        manifest: Parsed manifest dictionary
        new_session_id: New session UUID

    Returns:
        int: Number of files imported
    """
    file_history_list = manifest.get('session_data', {}).get('file_history', [])
    if not file_history_list:
        return 0

    # Target directory
    target_dir = get_file_history_dir(new_session_id)
    target_dir.mkdir(parents=True, exist_ok=True)

    count = 0
    for fh_relative in file_history_list:
        source_path = export_path / fh_relative
        if source_path.exists():
            target_path = target_dir / source_path.name
            shutil.copy2(source_path, target_path)
            count += 1

    return count
