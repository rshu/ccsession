from __future__ import annotations

import fnmatch
import json
import os
from dataclasses import dataclass
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
    return {path.stem[len('agent-'):]: path for path in sorted(subagents_dir.glob('agent-*.jsonl'))
            if path.is_file()}


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
    return [cf.source for cf in _collect_config_tree(session_dir, None)]


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

    if not file_history_dir.is_dir():
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

    if session_env_dir.is_dir():
        # Check if directory has any files
        files = list(session_env_dir.iterdir())
        if files:
            return session_env_dir

    return None


@dataclass(frozen=True)
class ConfigFile:
    """One file of the project's ``.claude/`` configuration.

    ``relative`` is the POSIX path below ``.claude/<type>/``; the export mirrors it
    under ``config/<type>/`` and the import restores it at the same place, so skill
    directories (``skills/<name>/SKILL.md``) and namespaced commands survive.
    """

    source: Path
    relative: str


# (type, glob) -- ``None`` collects every file. Claude Code reads commands, agents and
# rules as Markdown; skills and hooks are directories with arbitrary supporting files.
_CONFIG_TYPES = [
    ('commands', '*.md'),
    ('skills', None),
    ('hooks', None),
    ('agents', '*.md'),
    ('rules', '*.md'),
]
CONFIG_TYPE_NAMES = tuple(name for name, _ in _CONFIG_TYPES)


def _collect_config_tree(root: Path, pattern: str | None) -> list[ConfigFile]:
    """Files under ``root`` matching ``pattern``, following symlinked directories.

    Claude Code loads a skill (or command directory) that is a symlink, so the export
    must include what is behind it; relative paths keep each link's name. Only
    links to a directory already in the current branch are skipped, preventing
    cycles while preserving aliases to shared skills.
    """
    if not root.is_dir():
        return []
    files = []
    ancestors = {str(root): frozenset()}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
        real = os.path.realpath(dirpath)
        branch = ancestors.pop(dirpath, frozenset())
        if real in branch:
            dirnames[:] = []
            continue
        dirnames.sort()
        for dirname in dirnames:
            ancestors[os.path.join(dirpath, dirname)] = branch | {real}
        for filename in filenames:
            if pattern and not fnmatch.fnmatch(filename, pattern):
                continue
            path = Path(dirpath) / filename
            if path.is_file():
                files.append(ConfigFile(path, path.relative_to(root).as_posix()))
    return sorted(files, key=lambda cf: cf.relative.split('/'))


def collect_project_config(project_path: str | Path) -> dict:
    """Collect the project's ``.claude/`` configuration.

    Returns dict with config type -> list of :class:`ConfigFile`, plus ``settings``
    and ``claude_md`` as paths (or None).
    """
    project_path = Path(project_path)
    config: dict = {name: [] for name in CONFIG_TYPE_NAMES}
    config['settings'] = None
    config['claude_md'] = None

    claude_dir = project_path / '.claude'

    for name, pattern in _CONFIG_TYPES:
        config[name] = _collect_config_tree(claude_dir / name, pattern)

    # Settings (not settings.local.json)
    settings_file = claude_dir / 'settings.json'
    if settings_file.is_file():
        config['settings'] = settings_file

    # CLAUDE.md
    claude_md = project_path / 'CLAUDE.md'
    if claude_md.is_file():
        config['claude_md'] = claude_md

    return config
