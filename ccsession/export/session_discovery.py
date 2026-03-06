from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from ccsession.constants import MAX_DISPLAY_ITEMS
from ccsession.output import info, detail
from ccsession.paths import get_projects_dir


def get_parent_claude_pid() -> int | None:
    """Get the PID of the parent Claude process if running inside Claude Code."""
    try:
        # Get parent PID of current process
        ppid = os.getppid()
        # Check if parent is a claude process
        result = subprocess.run(['ps', '-p', str(ppid), '-o', 'cmd='],
                              capture_output=True, text=True)
        if 'claude' in result.stdout:
            return ppid
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def identify_current_session(sessions: list[dict], project_dir: str) -> dict | None:
    """Try to identify which session belongs to the current Claude instance."""
    # If we're running inside Claude Code, create a temporary marker
    claude_pid = get_parent_claude_pid()
    if not claude_pid:
        return None

    detail(f"\U0001f4cd Current Claude Code PID: {claude_pid}")

    # First, refresh session modification times
    refreshed_sessions = []
    for session in sessions:
        stat = session['path'].stat()
        refreshed_sessions.append({
            'path': session['path'],
            'mtime': stat.st_mtime,
            'session_id': session['session_id']
        })

    # Create a unique marker file
    marker_content = f"claude_export_marker_{claude_pid}_{time.time()}"
    marker_file = Path(project_dir) / '.claude_export_marker'

    try:
        # Write marker file
        marker_file.write_text(marker_content)
        time.sleep(0.2)  # Give it a moment to register

        # Check which session file was modified after marker creation
        marker_mtime = marker_file.stat().st_mtime

        for session in refreshed_sessions:
            # Re-check modification time
            current_mtime = session['path'].stat().st_mtime
            if current_mtime > marker_mtime:
                detail(f"\u2713 Session {session['session_id'][:8]}... was modified after marker creation")
                # Clean up marker
                marker_file.unlink(missing_ok=True)
                return session

        # Clean up marker
        marker_file.unlink(missing_ok=True)
    except OSError as e:
        info(f"\u26a0\ufe0f  Session identification failed: {e}")
        try:
            marker_file.unlink(missing_ok=True)
        except OSError:
            pass

    return None


def find_project_sessions(project_path: str | Path) -> list[dict]:
    """Find all JSONL session files for the current project."""
    project_path = str(project_path)
    claude_project_dir = get_projects_dir(project_path)

    if not claude_project_dir.exists():
        return []

    # Get all JSONL files sorted by modification time
    jsonl_files = []
    for file in claude_project_dir.glob('*.jsonl'):
        stat = file.stat()
        jsonl_files.append({
            'path': file,
            'mtime': stat.st_mtime,
            'session_id': file.stem
        })

    return sorted(jsonl_files, key=lambda x: x['mtime'], reverse=True)


def find_session_by_id(session_id: str) -> dict | None:
    """Find a session by ID across all projects.

    Searches ~/.claude/projects/*/ for a JSONL file whose stem matches
    the given session_id (exact match or prefix match).

    Returns:
        Session dict with 'path', 'mtime', 'session_id', or None if not found.
    """
    projects_root = Path.home() / '.claude' / 'projects'
    if not projects_root.exists():
        return None

    matches = []
    for project_dir in projects_root.iterdir():
        if not project_dir.is_dir():
            continue
        for file in project_dir.glob('*.jsonl'):
            # Skip agent session files
            if file.name.startswith('agent-'):
                continue
            if file.stem == session_id or file.stem.startswith(session_id):
                stat = file.stat()
                matches.append({
                    'path': file,
                    'mtime': stat.st_mtime,
                    'session_id': file.stem,
                    'project_dir': project_dir.name,
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
        info(f"\u26a0\ufe0f  No active sessions found (modified within {_ACTIVE_SESSION_MAX_AGE} seconds).")
        detail("Available sessions:")
        for i, session in enumerate(sessions[:MAX_DISPLAY_ITEMS]):
            age = int(time.time() - session['mtime'])
            detail(f"  {i+1}. {session['session_id'][:8]}... (modified {age}s ago)")
        info("\U0001f504 Exporting most recent session...")
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
        info("\u26a0\ufe0f  Could not identify specific session via activity. Using most recent.")
    else:
        info("\u26a0\ufe0f  Not running inside Claude Code. Using most recent session.")

    info(f"\U0001f4cc Defaulting to: {active_sessions[0]['session_id']}")
    return active_sessions[0]
