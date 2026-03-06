from __future__ import annotations

import shutil
from pathlib import Path


def _import_config_type(config_type: str, subdir: str, export_path: Path,
                        config_snapshot: dict, project_claude_dir: Path,
                        summary: dict) -> None:
    """Import files for a single config type."""
    files = config_snapshot.get(config_type, [])
    if not files:
        return

    target_dir = project_claude_dir / subdir
    target_dir.mkdir(parents=True, exist_ok=True)

    for relative_path in files:
        source_path = export_path / relative_path
        if not source_path.exists():
            continue

        target_path = target_dir / source_path.name

        if target_path.exists():
            summary['conflicts'].append(str(target_path))
        else:
            shutil.copy2(source_path, target_path)
            summary[config_type] += 1


def import_config(export_path: Path, manifest: dict, project_path: Path) -> dict:
    """Import config files to project .claude/ directory.

    Args:
        export_path: Path to the export directory
        manifest: Parsed manifest dictionary
        project_path: Target project path

    Returns:
        dict: Summary of imported files
    """
    summary = {
        'commands': 0,
        'skills': 0,
        'hooks': 0,
        'agents': 0,
        'rules': 0,
        'conflicts': []
    }

    config_snapshot = manifest.get('config_snapshot', {})
    project_claude_dir = project_path / '.claude'

    for config_type in ('commands', 'skills', 'hooks', 'agents', 'rules'):
        _import_config_type(config_type, config_type, export_path,
                            config_snapshot, project_claude_dir, summary)

    return summary


def add_claude_md_note(project_path: Path, manifest: dict) -> None:
    """Append import context section to CLAUDE.md.

    Args:
        project_path: Target project path
        manifest: Parsed manifest dictionary
    """
    claude_md_path = project_path / 'CLAUDE.md'

    # Prepare import context note
    original_context = manifest.get('original_context', {})
    note = f"""

## Imported Session Context

This session was imported via ccsession from another environment.

**Original environment:**
- User: {original_context.get('user', 'Unknown')}
- Path: {original_context.get('repo_path', 'Unknown')}
- Platform: {original_context.get('platform', 'Unknown')}
- Exported: {manifest.get('export_timestamp', 'Unknown')}
- Session ID: {manifest.get('session_id', 'Unknown')}

Some paths in the conversation history may reference the original environment.
"""

    if claude_md_path.exists():
        # Append to existing file
        with open(claude_md_path, 'a', encoding='utf-8') as f:
            f.write(note)
    else:
        # Create new file
        with open(claude_md_path, 'w', encoding='utf-8') as f:
            f.write(f"# CLAUDE.md\n{note}")
