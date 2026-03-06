from __future__ import annotations

import shutil
from pathlib import Path

from ccsession.paths import get_file_history_dir, get_todos_dir, get_plans_dir
from ccsession.utils import read_json, write_json


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


def import_todos(export_path: Path, manifest: dict, new_session_id: str) -> int:
    """Import todos to ~/.claude/todos/.

    Args:
        export_path: Path to the export directory
        manifest: Parsed manifest dictionary
        new_session_id: New session UUID

    Returns:
        int: Number of todo files imported
    """
    todos_path = manifest.get('session_data', {}).get('todos')
    if not todos_path:
        return 0

    source_path = export_path / todos_path
    if not source_path.exists():
        return 0

    # Target directory
    target_dir = get_todos_dir()
    target_dir.mkdir(parents=True, exist_ok=True)

    # Read and update session ID in todos
    try:
        todos = read_json(source_path)
    except (ValueError, OSError):
        return 0

    # Write with new session ID in filename
    write_json(target_dir / f'{new_session_id}-todos.json', todos)

    return 1


def import_plan(export_path: Path, manifest: dict) -> bool:
    """Import plan file to ~/.claude/plans/<slug>.md.

    Args:
        export_path: Path to the export directory
        manifest: Parsed manifest dictionary

    Returns:
        bool: True if plan was imported
    """
    plan_path = manifest.get('session_data', {}).get('plan_file')
    if not plan_path:
        return False

    source_path = export_path / plan_path
    if not source_path.exists():
        return False

    # Get slug from manifest
    slug = manifest.get('session_slug')
    if not slug:
        return False

    # Target directory
    target_dir = get_plans_dir()
    target_dir.mkdir(parents=True, exist_ok=True)

    target_path = target_dir / f'{slug}.md'

    # Don't overwrite existing plan
    if target_path.exists():
        print(f"  \u26a0\ufe0f  Plan file already exists: {target_path}")
        return False

    shutil.copy2(source_path, target_path)
    return True
