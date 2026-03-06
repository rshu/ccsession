from __future__ import annotations

import json
import subprocess
from pathlib import Path


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
        current_version = result.stdout.strip().split()[-1] if result.returncode == 0 else None
    except (subprocess.SubprocessError, OSError, IndexError):
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
