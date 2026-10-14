from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

from ccsession.constants import MAX_DISPLAY_ITEMS
from ccsession.output import info, detail, warn
from ccsession.paths import get_projects_dir, get_projects_root


def get_parent_claude_pid() -> int | None:
    """Get the PID of the parent Claude process if running inside Claude Code."""
    try:
        # Get parent PID of current process
        ppid = os.getppid()
        # Check if parent is a claude process
        # -ww: unlimited width on both GNU and BSD ps; otherwise procps truncates
        # to $COLUMNS (which pytest and some CI shells set to 80) and hides the end
        result = subprocess.run(['ps', '-ww', '-p', str(ppid), '-o', 'args='],
                              capture_output=True, text=True)
        if 'claude' in result.stdout:
            return ppid
    except (OSError, subprocess.SubprocessError):
        pass
    return None


_IDENTIFY_WAIT_SECONDS = 0.2


def _mtime_or_none(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def identify_current_session(sessions: list[dict], project_dir: str) -> dict | None:
    """Try to identify which session belongs to the current Claude instance.

    Claude Code appends to the live transcript while a tool runs, so the transcript
    whose modification time advances during a short wait is the current session.
    Nothing is written anywhere: the comparison is between two readings of each
    file's own mtime, which also makes it independent of filesystem timestamp
    resolution. A transcript that cannot be read is skipped.
    """
    claude_pid = get_parent_claude_pid()
    if not claude_pid:
        return None

    detail(f"\U0001f4cd Current Claude Code PID: {claude_pid}")

    before = {session['session_id']: _mtime_or_none(session['path']) for session in sessions}
    time.sleep(_IDENTIFY_WAIT_SECONDS)

    changed = []
    for session in sessions:
        earlier = before[session['session_id']]
        now = _mtime_or_none(session['path'])
        if earlier is not None and now is not None and now > earlier:
            changed.append({'path': session['path'], 'mtime': now, 'session_id': session['session_id']})

    if not changed:
        return None
    changed.sort(key=lambda s: s['mtime'], reverse=True)
    detail(f"\u2713 Session {changed[0]['session_id'][:8]}... was written to during the wait")
    return changed[0]


def find_project_sessions(project_path: str | Path) -> list[dict]:
    """Find all JSONL session files for the current project."""
    project_path = str(project_path)
    claude_project_dir = get_projects_dir(project_path)

    if not claude_project_dir.exists():
        return []

    # Get all JSONL files sorted by modification time. Flat agent-*.jsonl files
    # (pre-2.1 sub-agent transcripts) are never main sessions.
    jsonl_files = []
    for file in claude_project_dir.glob('*.jsonl'):
        if file.name.startswith('agent-') or not file.is_file():
            continue
        stat = file.stat()
        jsonl_files.append({
            'path': file,
            'mtime': stat.st_mtime,
            'session_id': file.stem
        })

    return sorted(jsonl_files, key=lambda x: x['mtime'], reverse=True)


def read_session_cwd(session_path: Path) -> str | None:
    """Return the working directory recorded in a transcript, or None.

    Scans records in order and stops at the first one carrying ``cwd``; bad
    lines are skipped so a truncated final line cannot hide the answer.
    """
    try:
        with open(session_path, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                cwd = record.get('cwd') if isinstance(record, dict) else None
                if isinstance(cwd, str) and cwd:
                    return cwd
    except OSError:
        return None
    return None


def find_session_by_id(session_id: str) -> dict | None:
    """Find a session by ID across all projects.

    Searches ~/.claude/projects/*/ for a JSONL file whose stem matches
    the given session_id (exact match or prefix match).

    Returns:
        Session dict with 'path', 'mtime', 'session_id', or None if not found.
    """
    projects_root = get_projects_root()
    if not projects_root.exists():
        return None

    matches = []
    for project_dir in projects_root.iterdir():
        if not project_dir.is_dir():
            continue
        for file in project_dir.glob('*.jsonl'):
            # Skip agent session files
            if file.name.startswith('agent-') or not file.is_file():
                continue
            if file.stem == session_id or file.stem.startswith(session_id):
                stat = file.stat()
                matches.append({
                    'path': file,
                    'mtime': stat.st_mtime,
                    'session_id': file.stem,
                    'project_dir': project_dir.name,
                    'project_path': read_session_cwd(file),
                })

    if not matches:
        return None

    if len(matches) == 1:
        return matches[0]

    # Exact match takes priority
    for m in matches:
        if m['session_id'] == session_id:
            return m

    # Multiple prefix matches — return most recent
    matches.sort(key=lambda x: x['mtime'], reverse=True)
    return matches[0]


def find_active_session(sessions: list[dict], max_age_seconds: int = 300) -> dict | None:
    """Find the most recently active session (modified within max_age_seconds)."""
    if not sessions:
        return None

    current_time = time.time()
    active_sessions = []

    for session in sessions:
        age = current_time - session['mtime']
        if age <= max_age_seconds:
            active_sessions.append(session)

    return active_sessions


_ACTIVE_SESSION_MAX_AGE = 300  # seconds


def select_session(sessions: list[dict], project_dir: str | None = None) -> dict:
    """Select which session to export.

    Encapsulates selection logic: active session filtering, PID-based
    identification, and fallback to most recent.

    Args:
        sessions: List of session dicts (must be non-empty)
        project_dir: Project directory path (for PID-based identification)

    Returns:
        The selected session dict.
    """
    active_sessions = find_active_session(sessions, _ACTIVE_SESSION_MAX_AGE)

    if not active_sessions:
        warn(f"\u26a0\ufe0f  No active sessions found (modified within {_ACTIVE_SESSION_MAX_AGE} seconds); "
             f"exporting the most recent one: {sessions[0]['session_id']}")
        detail("Available sessions:")
        for i, session in enumerate(sessions[:MAX_DISPLAY_ITEMS]):
            age = int(time.time() - session['mtime'])
            detail(f"  {i+1}. {session['session_id'][:8]}... (modified {age}s ago)")
        return sessions[0]

    if len(active_sessions) == 1:
        return active_sessions[0]

    # Multiple active sessions
    info(f"\U0001f50d Found {len(active_sessions)} active sessions:")
    for i, session in enumerate(active_sessions):
        age = int(time.time() - session['mtime'])
        detail(f"  {i+1}. {session['session_id'][:8]}... (modified {age}s ago)")

    info("\U0001f3af Attempting to identify current session...")

    if project_dir:
        current_session = identify_current_session(sessions, project_dir)
        if current_session:
            info(f"\u2705 Successfully identified current session: {current_session['session_id']}")
            return current_session

    claude_pid = get_parent_claude_pid()
    if claude_pid:
        detail(f"\U0001f50d Running in Claude Code (PID: {claude_pid})")
        warn(f"\u26a0\ufe0f  Could not identify which active session is this one; "
             f"exporting the most recent: {active_sessions[0]['session_id']}")
    else:
        warn(f"\u26a0\ufe0f  Not running inside Claude Code; exporting the most recent active session: "
             f"{active_sessions[0]['session_id']}")
    return active_sessions[0]
