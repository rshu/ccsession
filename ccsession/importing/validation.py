from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from ccsession.constants import MANIFEST_LAYOUT_VERSION
from ccsession.errors import InvalidExportError

_VERSION_PROBE_TIMEOUT_SECONDS = 10


def validate_manifest(export_path: Path) -> dict:
    """Validate .ccsession-manifest.json exists and is valid.

    Args:
        export_path: Path to the export directory

    Returns:
        dict: Parsed manifest content

    Raises:
        InvalidExportError: If manifest is missing or invalid
    """
    manifest_path = export_path / '.ccsession-manifest.json'

    if not manifest_path.exists():
        raise InvalidExportError(
            f"No .ccsession-manifest.json found in {export_path}.\n"
            "This does not appear to be a valid ccsession export."
        )

    try:
        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError) as e:
        raise InvalidExportError(f"Invalid manifest JSON: {e}")
    if not isinstance(manifest, dict):
        raise InvalidExportError("Invalid manifest: the top level is not a JSON object.")

    # Validate required fields
    required_fields = ['ccsession_version', 'session_id', 'session_data']
    missing_fields = [f for f in required_fields if f not in manifest]

    if missing_fields:
        raise InvalidExportError(
            f"Manifest validation failed:\n"
            f"  Missing required fields: {', '.join(missing_fields)}\n"
            "The export may be corrupted or manually modified."
        )

    layout_version = manifest.get('layout_version')
    if not isinstance(layout_version, int) or layout_version < MANIFEST_LAYOUT_VERSION:
        raise InvalidExportError(
            f"This export uses layout_version {layout_version!r}, older than the Claude Code 2.1 "
            f"layout this ccsession writes ({MANIFEST_LAYOUT_VERSION}).\n"
            "Re-export the session with the current ccsession."
        )
    if layout_version > MANIFEST_LAYOUT_VERSION:
        raise InvalidExportError(
            f"This export uses layout_version {layout_version}, newer than this ccsession "
            f"understands ({MANIFEST_LAYOUT_VERSION}).\n"
            "Upgrade ccsession: pip install --upgrade ccsession-cli"
        )

    _check_manifest_shape(manifest)
    return manifest


def _check_manifest_shape(manifest: dict) -> None:
    """Refuse a manifest whose fields have the wrong type, before any of them is used."""
    def bad(field: str, expected: str):
        return InvalidExportError(
            f"Manifest field {field} is not {expected}.\n"
            "The export may be corrupted or tampered with."
        )

    if not isinstance(manifest.get('session_id'), str) or not manifest['session_id']:
        raise bad('session_id', 'a non-empty string')
    for field in ('original_context', 'config_snapshot', 'statistics'):
        if manifest.get(field) is not None and not isinstance(manifest[field], dict):
            raise bad(field, 'an object')
    repo_path = (manifest.get('original_context') or {}).get('repo_path')
    if repo_path is not None and not isinstance(repo_path, str):
        raise bad('original_context.repo_path', 'a path')
    session_data = manifest.get('session_data')
    if not isinstance(session_data, dict):
        raise bad('session_data', 'an object')
    for field in ('main_session', 'session_dir', 'history', 'session_env'):
        value = session_data.get(field)
        if value is not None and not isinstance(value, str):
            raise bad(f'session_data.{field}', 'a path')
    for field in ('agent_sessions', 'agent_meta', 'file_history'):
        value = session_data.get(field)
        if value is not None and (not isinstance(value, list) or not all(isinstance(v, str) for v in value)):
            raise bad(f'session_data.{field}', 'a list of paths')


def check_version_compatibility(manifest: dict) -> tuple:
    """Check Claude Code version compatibility.

    Args:
        manifest: Parsed manifest dictionary

    Returns:
        tuple: (is_compatible: bool, warning_message: str or None)
    """
    # Get current Claude Code version. shutil.which finds npm's claude.cmd shim on
    # Windows (CreateProcess would not); the timeout keeps a wedged CLI from
    # blocking the import, and a closed stdin keeps it from waiting for input.
    executable = _find_claude_executable()
    current_version = None
    if executable:
        try:
            extra = {}
            if sys.platform == 'win32':
                # npm's claude.cmd runs a bare `node`, which cmd.exe would look up in
                # the current directory first: run it from its own directory instead.
                extra = {'cwd': os.path.dirname(os.path.abspath(executable)),
                         'env': {**os.environ, 'NoDefaultCurrentDirectoryInExePath': '1'}}
            result = subprocess.run([executable, '--version'], capture_output=True, text=True,
                                    timeout=_VERSION_PROBE_TIMEOUT_SECONDS, stdin=subprocess.DEVNULL, **extra)
            current_version = _parse_version(result.stdout) if result.returncode == 0 else None
        except (subprocess.SubprocessError, OSError):
            current_version = None

    export_version = manifest.get('claude_code_version')

    if not current_version:
        return True, "Could not determine current Claude Code version."

    if not export_version:
        return True, "Export manifest does not specify Claude Code version."

    if current_version != export_version:
        return True, (
            f"Version mismatch detected:\n"
            f"  Session created with: Claude Code {export_version}\n"
            f"  Your version: Claude Code {current_version}\n"
            "Proceeding may have compatibility issues."
        )

    return True, None


_VERSION_RE = re.compile(r'\d+\.\d+\.\d+(?:[-+][\w.-]+)?')


def _find_claude_executable() -> str | None:
    """``claude`` on PATH, or None.

    On Windows ``shutil.which`` searches the current directory before PATH and
    accepts ``.cmd``/``.bat`` files, so an export or project directory could supply
    the program that gets run; a hit inside the current directory is ignored there.
    """
    executable = shutil.which('claude')
    if executable and sys.platform == 'win32':
        try:
            # The directory the hit was found in, not where a symlink would lead
            found_in = os.path.realpath(os.path.dirname(os.path.abspath(executable)))
            if os.path.normcase(found_in) == os.path.normcase(os.path.realpath(os.getcwd())):
                return None
        except OSError:
            return None
    return executable


def _parse_version(output: str) -> str | None:
    """Extract a semantic version from `claude --version` output.

    The CLI prints e.g. "2.1.287 (Claude Code)"; only the version token is wanted.
    Returns None when no version-looking token is present.
    """
    match = _VERSION_RE.search(output)
    return match.group(0) if match else None


def resolve_export_path(export_path: Path, relative: str) -> Path:
    """Resolve a manifest-supplied relative path and prove it stays inside the export.

    Exports are meant to be shared, so a manifest is untrusted input: ``../`` or an
    absolute path must not let an import read or copy anything outside the export
    directory.

    Raises:
        InvalidExportError: if the path escapes ``export_path``.
    """
    if not isinstance(relative, str) or not relative:
        raise InvalidExportError(
            f"Manifest path {relative!r} is not a path.\n"
            "The export may be corrupted or tampered with."
        )
    root = Path(export_path).resolve()
    try:
        candidate = (root / relative).resolve()
    except (OSError, RuntimeError, ValueError) as e:
        raise InvalidExportError(f"Manifest path {relative!r} cannot be resolved: {e}") from e
    if candidate != root and root not in candidate.parents:
        raise InvalidExportError(
            f"Manifest path {relative!r} points outside the export directory {root}.\n"
            "The export may be corrupted or tampered with."
        )
    return candidate
