from __future__ import annotations

import os
from pathlib import Path


_NORMALIZE_TABLE = str.maketrans({'/': '-', '\\': '-', ':': '-', '.': '-', '_': '-'})


def get_normalized_project_dir(project_path: str | Path) -> str:
    """Get the normalized Claude project directory name for a given path.

    Replicates Claude Code's path normalization:
    - / -> -
    - \\ -> -
    - : -> -
    - . -> -
    - _ -> -
    - Unix paths: prefix with -
    - Windows paths: no prefix
    """
    project_path = str(project_path)
    if os.name != 'nt':
        project_path = project_path.replace('\\', '/')

    project_dir_name = project_path.translate(_NORMALIZE_TABLE)

    if project_dir_name.startswith('-'):
        project_dir_name = project_dir_name[1:]

    if os.name == 'nt':
        return project_dir_name
    else:
        return f'-{project_dir_name}'


def get_projects_dir(project_path: str | Path) -> Path:
    """Get ~/.claude/projects/<normalized-path>/ for the given project."""
    normalized_dir = get_normalized_project_dir(str(project_path))
    return Path.home() / '.claude' / 'projects' / normalized_dir


def get_file_history_dir(session_id: str) -> Path:
    """Get ~/.claude/file-history/<session_id>/."""
    return Path.home() / '.claude' / 'file-history' / session_id


def get_todos_dir() -> Path:
    """Get ~/.claude/todos/."""
    return Path.home() / '.claude' / 'todos'


def get_plans_dir() -> Path:
    """Get ~/.claude/plans/."""
    return Path.home() / '.claude' / 'plans'


def get_session_env_dir(session_id: str) -> Path:
    """Get ~/.claude/session-env/<session_id>/."""
    return Path.home() / '.claude' / 'session-env' / session_id


def get_import_storage_dir() -> Path:
    """Get ~/.claude-session-imports/."""
    return Path.home() / '.claude-session-imports'


def get_snapshot_dir() -> Path:
    """Get ~/.claude-session-imports/pre-import-snapshot/."""
    return get_import_storage_dir() / 'pre-import-snapshot'
