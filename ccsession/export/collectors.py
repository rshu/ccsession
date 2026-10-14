from __future__ import annotations

import json
from pathlib import Path

from ccsession.paths import get_file_history_dir, get_session_env_dir, get_history_file


def collect_agent_sessions(claude_project_dir: Path, session_id: str) -> dict[str, Path]:
    """Collect the sub-agent transcripts of a session.

    Claude Code 2.1 writes them to ``<project-dir>/<session-id>/subagents/agent-<id>.jsonl``,
    so every transcript in that folder belongs to the session by construction. Files
    are deliberately not required to be referenced from the main transcript: background
    and async agents often leave no agentId there, yet their transcripts still exist.

    Returns dict with agent_id -> file_path mapping, sorted by agent id.
    """
    subagents_dir = claude_project_dir / session_id / 'subagents'
    if not subagents_dir.is_dir():
        return {}
    return {path.stem[len('agent-'):]: path for path in sorted(subagents_dir.glob('agent-*.jsonl'))}


def collect_session_dir_files(claude_project_dir: Path, session_id: str) -> list[Path]:
    """Collect every file under the per-session directory.

    Claude Code 2.1 keeps sub-agent transcripts and their ``.meta.json`` sidecars,
    tool-result sidecars, Workflow runs and loose diagnostics under
    ``<project-dir>/<session-id>/``. The export mirrors that tree verbatim, so
    this returns regular files recursively, sorted for stable output.
    """
    session_dir = claude_project_dir / session_id
    if not session_dir.is_dir():
        return []
    return sorted(p for p in session_dir.rglob('*') if p.is_file())


def collect_history_lines(session_id: str) -> list[dict]:
    """Return the prompt-history records that belong to a session.

    ``<claude-dir>/history.jsonl`` holds one record per prompt with a
    ``sessionId``; the CLI uses it for prompt recall. Unparseable lines are skipped.
    """
    history_file = get_history_file()
    if not history_file.is_file():
        return []
    records: list[dict] = []
    with open(history_file, 'r', encoding='utf-8') as f:
        for line in f:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict) and record.get('sessionId') == session_id:
                records.append(record)
    return records


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
