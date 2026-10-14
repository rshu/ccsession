from __future__ import annotations

import json
from pathlib import Path

from ccsession.paths import (
    get_file_history_dir, get_plans_dir, get_todos_dir, get_session_env_dir,
)


def collect_agent_sessions(claude_project_dir: Path, session_id: str) -> dict[str, Path]:
    """Collect all sub-agent transcript files belonging to a session.

    Two on-disk layouts exist:
      1. Per-session (current): <project-dir>/<session-id>/subagents/agent-*.jsonl
         Every file in this folder belongs to the session by construction.
      2. Legacy flat: <project-dir>/agent-*.jsonl, shared by all sessions of the
         project; a file belongs to the session if its first line's sessionId matches.

    Files are deliberately not required to be referenced from the main transcript:
    background and async agents often leave no agentId there, yet their transcripts
    still exist on disk and must be exported.

    Args:
        claude_project_dir: The ~/.claude/projects/<normalized>/ directory
        session_id: The session UUID

    Returns dict with agent_id -> file_path mapping. Per-session files take precedence.
    """
    agents: dict[str, Path] = {}

    if not claude_project_dir.exists():
        return agents

    for agent_file in _iter_agent_files(claude_project_dir / session_id / 'subagents'):
        agents.setdefault(_agent_id_from_path(agent_file), agent_file)

    for agent_file in _iter_agent_files(claude_project_dir):
        agent_id = _agent_id_from_path(agent_file)
        if agent_id in agents:
            continue
        if _first_line_session_id(agent_file) == session_id:
            agents[agent_id] = agent_file

    return agents


def _iter_agent_files(directory: Path):
    """Yield agent-*.jsonl transcripts in a directory, skipping compaction snapshots."""
    if not directory.exists():
        return
    for agent_file in sorted(directory.glob('agent-*.jsonl')):
        if _agent_id_from_path(agent_file).startswith('compact-'):
            continue
        yield agent_file


def _agent_id_from_path(agent_file: Path) -> str:
    return agent_file.stem[len('agent-'):]


def _first_line_session_id(agent_file: Path) -> str | None:
    """Return the sessionId recorded on the first line of a transcript, if readable."""
    try:
        with open(agent_file, 'r', encoding='utf-8') as f:
            first_line = f.readline()
        if not first_line:
            return None
        data = json.loads(first_line)
    except (json.JSONDecodeError, OSError):
        return None
    return data.get('sessionId') if isinstance(data, dict) else None


def collect_tool_results(claude_project_dir: Path, session_id: str) -> list[Path]:
    """Collect tool-result sidecar files for a session.

    These are stored at ~/.claude/projects/<normalized>/<session-id>/tool-results/*.txt

    Args:
        claude_project_dir: The ~/.claude/projects/<normalized>/ directory
        session_id: The session UUID

    Returns list of file paths or empty list if none.
    """
    tool_results_dir = claude_project_dir / session_id / 'tool-results'

    if not tool_results_dir.exists():
        return []

    return sorted(f for f in tool_results_dir.iterdir() if f.is_file())


def collect_file_history(session_id: str) -> list[Path]:
    """Collect file history snapshots for a session.

    Returns list of file paths or empty list if none.
    """
    file_history_dir = get_file_history_dir(session_id)

    if not file_history_dir.exists():
        return []

    files = []
    for f in file_history_dir.iterdir():
        if f.is_file():
            files.append(f)

    return files


def collect_plan_file(slug: str | None) -> Path | None:
    """Collect plan file for a session by slug.

    Returns file path or None if not found.
    """
    if not slug:
        return None

    plan_file = get_plans_dir() / f'{slug}.md'

    if plan_file.exists():
        return plan_file

    return None


def collect_todos(session_id: str) -> list[Path]:
    """Collect todo files for a session.

    Returns list of file paths or empty list if none.
    """
    todos_dir = get_todos_dir()

    if not todos_dir.exists():
        return []

    files = []
    for f in todos_dir.glob(f'{session_id}-*.json'):
        files.append(f)

    return files


def collect_session_env(session_id: str) -> Path | None:
    """Collect session environment data.

    Returns directory path if exists and non-empty, None otherwise.
    """
    session_env_dir = get_session_env_dir(session_id)

    if session_env_dir.exists():
        # Check if directory has any files
        files = list(session_env_dir.iterdir())
        if files:
            return session_env_dir

    return None


_CONFIG_TYPES = [
    # (key, directory_name, glob_pattern)
    ('skills', 'skills', '*.md'),
    ('hooks', 'hooks', None),      # None means collect all files
    ('agents', 'agents', '*.md'),
    ('rules', 'rules', '*.md'),
]


def collect_project_config(project_path: str | Path) -> dict:
    """Collect project configuration files.

    Returns dict with config type -> list of file paths.
    """
    project_path = Path(project_path)
    config = {
        'commands': [],
        'skills': [],
        'hooks': [],
        'agents': [],
        'rules': [],
        'settings': None,
        'claude_md': None
    }

    claude_dir = project_path / '.claude'

    # Commands - special case: check both .claude/commands/ and commands/
    for commands_dir in [claude_dir / 'commands', project_path / 'commands']:
        if commands_dir.exists():
            for f in commands_dir.glob('*.md'):
                config['commands'].append(f)

    # Standard config types
    for key, dirname, glob_pattern in _CONFIG_TYPES:
        config_dir = claude_dir / dirname
        if config_dir.exists():
            if glob_pattern:
                for f in config_dir.glob(glob_pattern):
                    config[key].append(f)
            else:
                for f in config_dir.iterdir():
                    if f.is_file():
                        config[key].append(f)

    # Settings (not settings.local.json)
    settings_file = claude_dir / 'settings.json'
    if settings_file.exists():
        config['settings'] = settings_file

    # CLAUDE.md
    claude_md = project_path / 'CLAUDE.md'
    if claude_md.exists():
        config['claude_md'] = claude_md

    return config
