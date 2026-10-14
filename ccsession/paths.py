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


def get_claude_dir() -> Path:
    """Return Claude Code's config directory.

    Honours ``CLAUDE_CONFIG_DIR`` the same way the CLI does; an unset or empty
    value means ``~/.claude``.
    """
    configured = os.environ.get('CLAUDE_CONFIG_DIR', '').strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / '.claude'


def get_projects_root() -> Path:
    """Get <claude-dir>/projects/."""
    return get_claude_dir() / 'projects'


def get_projects_dir(project_path: str | Path) -> Path:
    """Get <claude-dir>/projects/<normalized-path>/ for the given project."""
    return get_projects_root() / get_normalized_project_dir(str(project_path))


def get_session_dir(project_path: str | Path, session_id: str) -> Path:
    """Get the per-session directory <claude-dir>/projects/<normalized>/<session_id>/."""
    return get_projects_dir(project_path) / session_id


def get_file_history_dir(session_id: str) -> Path:
    """Get <claude-dir>/file-history/<session_id>/."""
    return get_claude_dir() / 'file-history' / session_id


def get_session_env_dir(session_id: str) -> Path:
    """Get <claude-dir>/session-env/<session_id>/."""
    return get_claude_dir() / 'session-env' / session_id


def get_history_file() -> Path:
    """Get <claude-dir>/history.jsonl (prompt history shown by the CLI)."""
    return get_claude_dir() / 'history.jsonl'


def get_import_storage_dir() -> Path:
    """Get ~/.claude-session-imports/."""
    return Path.home() / '.claude-session-imports'


def get_snapshot_dir() -> Path:
    """Get ~/.claude-session-imports/pre-import-snapshot/."""
    return get_import_storage_dir() / 'pre-import-snapshot'
