from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from ccsession.constants import MANIFEST_LAYOUT_VERSION


def validate_manifest(export_path: Path) -> dict:
    """Validate .ccsession-manifest.json exists and is valid.

    Args:
        export_path: Path to the export directory

    Returns:
        dict: Parsed manifest content

    Raises:
        ImportError: If manifest is missing or invalid
    """
    manifest_path = export_path / '.ccsession-manifest.json'

    if not manifest_path.exists():
        raise ImportError(
            f"No .ccsession-manifest.json found in {export_path}.\n"
            "This does not appear to be a valid ccsession export."
        )

    try:
        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest = json.load(f)
    except json.JSONDecodeError as e:
        raise ImportError(f"Invalid manifest JSON: {e}")

    # Validate required fields
    required_fields = ['ccsession_version', 'session_id', 'session_data']
    missing_fields = [f for f in required_fields if f not in manifest]

    if missing_fields:
        raise ImportError(
            f"Manifest validation failed:\n"
            f"  Missing required fields: {', '.join(missing_fields)}\n"
            "The export may be corrupted or manually modified."
        )

    # Exports from ccsession 2.0.0 predate layout_version; treat them as layout 1.
    layout_version = manifest.get('layout_version', 1)
    if not isinstance(layout_version, int) or layout_version < 1:
        raise ImportError(f"Manifest has an invalid layout_version: {layout_version!r}")
    if layout_version > MANIFEST_LAYOUT_VERSION:
        raise ImportError(
            f"This export uses layout_version {layout_version}, newer than this ccsession "
            f"understands ({MANIFEST_LAYOUT_VERSION}).\n"
            "Upgrade ccsession: pip install --upgrade ccsession-cli"
        )
    manifest['layout_version'] = layout_version

    return manifest


def check_version_compatibility(manifest: dict) -> tuple:
    """Check Claude Code version compatibility.

    Args:
        manifest: Parsed manifest dictionary

    Returns:
        tuple: (is_compatible: bool, warning_message: str or None)
    """
    # Get current Claude Code version
    try:
        result = subprocess.run(['claude', '--version'], capture_output=True, text=True)
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
        ImportError: if the path escapes ``export_path``.
    """
    root = Path(export_path).resolve()
    candidate = (root / relative).resolve()
    if candidate != root and root not in candidate.parents:
        raise ImportError(
            f"Manifest path {relative!r} points outside the export directory {root}.\n"
            "The export may be corrupted or tampered with."
        )
    return candidate
