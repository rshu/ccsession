from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
import xml.etree.ElementTree as ET

from ccsession.export.parsers import parse_jsonl_file, extract_message_metadata
from ccsession.export.formatters import _xml_text, format_message_markdown, format_message_xml, prettify_xml
from ccsession.export.collectors import (
    ConfigFile, collect_agent_sessions, collect_file_history, collect_session_env, collect_project_config,
    collect_session_dir_files, collect_history_lines,
)
from ccsession.export.manifest import generate_manifest, generate_rendered_markdown, write_empty_marker
from ccsession.export.trajectory import format_trajectory
from ccsession.output import info, warn
from ccsession.utils import json_line, write_json


def _write_legacy_files(export_dir: Path, session_path: Path, messages: list[dict],
                        metadata: dict) -> None:
    """Write legacy export files (metadata, raw JSONL, markdown, XML, summary)."""
    # Save metadata
    write_json(export_dir / 'session_info.json', metadata)

    # Copy raw JSONL
    shutil.copy2(session_path, export_dir / 'raw_messages.jsonl')

    # Generate markdown conversation
    # The human-readable files tolerate text UTF-8 cannot encode (a lone surrogate from a
    # \ud800 escape in the transcript); the verbatim copies stay lossless.
    md_path = export_dir / 'conversation_full.md'
    with open(md_path, 'w', encoding='utf-8', errors='replace') as f:
        f.write(f"# Claude Code Session Export\n\n")
        f.write(f"**Session ID:** `{metadata['session_id']}`\n")
        f.write(f"**Project:** `{metadata['project_dir']}`\n")
        f.write(f"**Start Time:** {metadata['start_time']}\n")
        f.write(f"**End Time:** {metadata['end_time']}\n")
        f.write(f"**Total Messages:** {metadata['total_messages']}\n")
        f.write(f"**User Messages:** {metadata['user_messages']}\n")
        f.write(f"**Assistant Messages:** {metadata['assistant_messages']}\n")
        f.write(f"**Tool Uses:** {metadata['tool_uses']}\n")
        f.write(f"**Models Used:** {', '.join(metadata['models_used'])}\n\n")
        f.write("---\n\n")

        for msg in messages:
            formatted = format_message_markdown(msg)
            if formatted:
                f.write(formatted)
                f.write("\n\n---\n\n")

    # Generate XML conversation
    root = ET.Element('claude-session')
    root.set('xmlns', 'https://claude.ai/session-export/v1')
    root.set('export-version', '1.0')

    meta_elem = ET.SubElement(root, 'metadata')
    ET.SubElement(meta_elem, 'session-id').text = _xml_text(metadata['session_id'])
    ET.SubElement(meta_elem, 'version').text = _xml_text(messages[0].get('version', '') if messages else '')
    ET.SubElement(meta_elem, 'working-directory').text = _xml_text(metadata['project_dir'])
    ET.SubElement(meta_elem, 'start-time').text = _xml_text(metadata['start_time'])
    ET.SubElement(meta_elem, 'end-time').text = _xml_text(metadata['end_time'])
    ET.SubElement(meta_elem, 'export-time').text = datetime.now(timezone.utc).isoformat()

    stats_elem = ET.SubElement(meta_elem, 'statistics')
    ET.SubElement(stats_elem, 'total-messages').text = str(metadata['total_messages'])
    ET.SubElement(stats_elem, 'user-messages').text = str(metadata['user_messages'])
    ET.SubElement(stats_elem, 'assistant-messages').text = str(metadata['assistant_messages'])
    ET.SubElement(stats_elem, 'tool-uses').text = str(metadata['tool_uses'])

    models_elem = ET.SubElement(stats_elem, 'models-used')
    for model in metadata['models_used']:
        ET.SubElement(models_elem, 'model').text = _xml_text(model)

    messages_elem = ET.SubElement(root, 'messages')
    for msg in messages:
        format_message_xml(msg, messages_elem)

    xml_path = export_dir / 'conversation_full.xml'
    xml_string = prettify_xml(root)
    with open(xml_path, 'w', encoding='utf-8', errors='replace') as f:
        f.write(xml_string)

    # Generate summary
    summary_path = export_dir / 'summary.txt'
    with open(summary_path, 'w', encoding='utf-8', errors='replace') as f:
        f.write(f"Claude Code Session Summary\n")
        f.write(f"==========================\n\n")
        f.write(f"Session ID: {metadata['session_id']}\n")
        f.write(f"Export Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Project Directory: {metadata['project_dir']}\n")
        f.write(f"Duration: {metadata['start_time']} to {metadata['end_time']}\n")
        f.write(f"\nStatistics:\n")
        f.write(f"- Total Messages: {metadata['total_messages']}\n")
        f.write(f"- User Messages: {metadata['user_messages']}\n")
        f.write(f"- Assistant Messages: {metadata['assistant_messages']}\n")
        f.write(f"- Tool Uses: {metadata['tool_uses']}\n")
        f.write(f"- Models: {', '.join(metadata['models_used'])}\n")
        f.write(f"\nExported to: {export_dir}\n")


def _copy_files_to_dir(files: list, target_dir: Path, empty_message: str) -> None:
    """Copy files flat into a directory, or write an empty marker if no files."""
    target_dir.mkdir(exist_ok=True)
    if files:
        for f in files:
            shutil.copy2(f, target_dir / f.name)
    else:
        write_empty_marker(target_dir, empty_message)


def _copy_config_tree(files: list[ConfigFile], target_dir: Path, empty_message: str) -> None:
    """Mirror config files under ``target_dir`` keeping their relative paths."""
    target_dir.mkdir(exist_ok=True)
    if not files:
        write_empty_marker(target_dir, empty_message)
        return
    for cf in files:
        target = target_dir / cf.relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(cf.source, target)


def _check_export_name(name) -> None:
    """An export name is one plain directory name; anything else could place (and,
    on failure, remove) the export outside its parent directory."""
    if (not isinstance(name, str) or name in ('', '.', '..') or '/' in name or '\\' in name
            or '\0' in name or os.path.isabs(name) or os.path.splitdrive(name)[0]):
        raise ValueError(f"Invalid export name {name!r}: use a single directory name, without '/', '\\' or '..'")


def _default_export_root(project_path: Path) -> Path:
    """Where ``.claude-sessions/`` goes when no ``--output-dir`` is given.

    A session exported by id may belong to a project that has since been deleted or
    moved; recreating that directory just to hold the export would be surprising, so
    the current working directory is used instead.
    """
    if project_path.is_dir():
        return project_path
    warn(f"⚠️  Project directory {project_path} does not exist; exporting under {Path.cwd()}")
    return Path.cwd()


def export_session(session_info: dict, project_path: str | Path,
                   export_name: str | None = None,
                   output_dir: str | Path | None = None,
                   mode: str = 'portable') -> tuple[Path, dict | None]:
    """Export a session.

    Args:
        session_info: Session information dictionary with 'path' and 'session_id'
        project_path: Path to the project directory
        export_name: Name for the export folder (auto-generated if None)
        output_dir: Custom output directory (overrides default location)
        mode: Export mode - 'portable' (full structure) or 'classic' (legacy files only)

    Returns:
        Tuple of (export_dir, manifest) where manifest is None for classic mode.
    """
    project_path = Path(project_path)

    # Parse the session file
    messages, metadata = parse_jsonl_file(session_info['path'])

    # Get session ID — prefer the filename-based ID (canonical) over JSONL-internal sessionId
    session_id = session_info['session_id']
    metadata['session_id'] = session_id
    msg_meta = extract_message_metadata(messages)
    slug = msg_meta['slug']

    if export_name is not None:
        _check_export_name(export_name)

    # Auto-generate export name if not provided
    if not export_name:
        timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d_%H-%M-%S')
        export_name = f"{timestamp}_{session_id[:8]}" if mode == 'classic' else timestamp

    # Determine output directory
    if output_dir:
        export_dir = Path(output_dir) / export_name
    elif mode == 'portable':
        export_dir = _default_export_root(project_path) / '.claude-sessions' / export_name
    else:
        export_dir = Path.home() / 'claude_sessions' / 'exports' / export_name

    # Only a directory this call created may be removed if the export fails
    export_dir.parent.mkdir(parents=True, exist_ok=True)
    try:
        export_dir.mkdir()
        created_dir = True
    except FileExistsError:
        created_dir = False
    try:
        return _write_export(export_dir, session_info, project_path, messages, metadata, msg_meta,
                             session_id=session_id, slug=slug, export_name=export_name, mode=mode)
    except BaseException:
        # Never leave a half-written export behind (it would look importable but is not)
        if created_dir:
            shutil.rmtree(export_dir, ignore_errors=True)
        raise


def _write_export(export_dir: Path, session_info: dict, project_path: Path, messages: list,
                  metadata: dict, msg_meta: dict, *, session_id: str, slug, export_name: str,
                  mode: str) -> tuple[Path, dict | None]:
    """Write every file of the export into ``export_dir``."""
    # Write legacy files (both modes)
    info("\U0001f4dd Writing legacy files...")
    _write_legacy_files(export_dir, session_info['path'], messages, metadata)

    if mode == 'classic':
        return export_dir, None

    # =========================================================================
    # Portable mode: collect and write enhanced structure
    # =========================================================================
    info("\U0001f4e6 Collecting session data...")

    # The claude project dir is the parent of the session file
    # (e.g., ~/.claude/projects/-home-user-project/)
    claude_project_dir = session_info['path'].parent

    agent_sessions = collect_agent_sessions(claude_project_dir, session_id)
    file_history = collect_file_history(session_id)
    session_env = collect_session_env(session_id)
    session_dir_root = claude_project_dir / session_id
    session_dir_files = collect_session_dir_files(claude_project_dir, session_id)
    history_lines = collect_history_lines(session_id)

    session_files = {
        'agents': agent_sessions,
        'file_history': file_history,
        'session_env': session_env,
        'session_dir_root': session_dir_root,
        'session_dir_files': session_dir_files,
        'history': history_lines,
    }

    # Collect project config
    info("\U0001f4e6 Collecting project config...")
    config_files = collect_project_config(project_path)

    # Generate manifest
    manifest = generate_manifest(
        session_id, slug, export_name, metadata, msg_meta,
        session_files, config_files, project_path
    )

    # Write session data
    info("\U0001f4dd Writing session data...")

    session_dir = export_dir / 'session'
    session_dir.mkdir(exist_ok=True)

    # Main session
    shutil.copy2(session_info['path'], session_dir / 'main.jsonl')

    # File history
    _copy_files_to_dir(file_history, session_dir / 'file-history',
                       "No file history snapshots for this session.")

    # Verbatim mirror of <project-dir>/<session-id>/ (sub-agents + meta, tool results, workflows, diagnostics)
    mirror_dir = session_dir / 'session-dir'
    mirror_dir.mkdir(exist_ok=True)
    if session_dir_files:
        for source in session_dir_files:
            target = mirror_dir / source.relative_to(session_dir_root)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    else:
        write_empty_marker(mirror_dir, "No per-session directory for this session.")
    if history_lines:
        with open(session_dir / 'history.jsonl', 'w', encoding='utf-8', newline='') as f:
            for record in history_lines:
                f.write(json_line(record) + '\n')

    # Session env
    session_env_dir = session_dir / 'session-env'
    session_env_dir.mkdir(exist_ok=True)
    if session_env:
        for env_file in session_env.iterdir():
            if env_file.is_file():
                shutil.copy2(env_file, session_env_dir / env_file.name)
    else:
        write_empty_marker(session_env_dir, "No session environment data.")

    # Write config snapshot
    info("\U0001f4dd Writing config snapshot...")

    config_dir = export_dir / 'config'
    config_dir.mkdir(exist_ok=True)

    _CONFIG_SNAPSHOT_TYPES = [
        ('commands', 'commands', "No custom commands configured."),
        ('skills', 'skills', "No custom skills configured."),
        ('hooks', 'hooks', "No hooks configured."),
        ('agents', 'agents', "No custom agents configured."),
        ('rules', 'rules', "No custom rules configured."),
    ]

    for config_key, subdir, empty_msg in _CONFIG_SNAPSHOT_TYPES:
        _copy_config_tree(config_files[config_key], config_dir / subdir, empty_msg)

    if config_files['settings']:
        shutil.copy2(config_files['settings'], config_dir / 'settings.json')
    else:
        (config_dir / 'settings.json').write_text('{}', encoding='utf-8')

    if config_files['claude_md']:
        shutil.copy2(config_files['claude_md'], config_dir / 'CLAUDE.md')
    else:
        (config_dir / 'CLAUDE.md').write_text('# No CLAUDE.md\n\nNo CLAUDE.md file in project.\n', encoding='utf-8')

    # Write trajectory, manifest, and RENDERED.md
    info("\U0001f4dd Writing trajectory.json...")
    trajectory = format_trajectory(
        messages, metadata, msg_meta,
        agent_sessions=agent_sessions,
    )
    write_json(export_dir / 'trajectory.json', trajectory)

    info("\U0001f4dd Writing manifest and RENDERED.md...")
    write_json(export_dir / '.ccsession-manifest.json', manifest)

    rendered_md = generate_rendered_markdown(messages, metadata, manifest)
    rendered_path = export_dir / 'RENDERED.md'
    with open(rendered_path, 'w', encoding='utf-8', errors='replace') as f:
        f.write(rendered_md)

    return export_dir, manifest
