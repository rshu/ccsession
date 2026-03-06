from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
import xml.etree.ElementTree as ET

from ccsession.export.parsers import parse_jsonl_file, extract_message_metadata
from ccsession.export.formatters import format_message_markdown, format_message_xml, prettify_xml
from ccsession.export.collectors import (
    collect_agent_sessions, collect_file_history, collect_plan_file,
    collect_todos, collect_session_env, collect_tool_results, collect_project_config,
)
from ccsession.export.manifest import generate_manifest, generate_rendered_markdown, write_empty_marker
from ccsession.export.trajectory import format_trajectory
from ccsession.utils import write_json


def _write_legacy_files(export_dir: Path, session_path: Path, messages: list[dict],
                        metadata: dict) -> None:
    """Write legacy export files (metadata, raw JSONL, markdown, XML, summary)."""
    # Save metadata
    write_json(export_dir / 'session_info.json', metadata)

    # Copy raw JSONL
    shutil.copy2(session_path, export_dir / 'raw_messages.jsonl')

    # Generate markdown conversation
    md_path = export_dir / 'conversation_full.md'
    with open(md_path, 'w', encoding='utf-8') as f:
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
    ET.SubElement(meta_elem, 'session-id').text = metadata['session_id']
    ET.SubElement(meta_elem, 'version').text = messages[0].get('version', '') if messages else ''
    ET.SubElement(meta_elem, 'working-directory').text = metadata['project_dir']
    ET.SubElement(meta_elem, 'start-time').text = metadata['start_time']
    ET.SubElement(meta_elem, 'end-time').text = metadata['end_time']
    ET.SubElement(meta_elem, 'export-time').text = datetime.now(timezone.utc).isoformat()

    stats_elem = ET.SubElement(meta_elem, 'statistics')
    ET.SubElement(stats_elem, 'total-messages').text = str(metadata['total_messages'])
    ET.SubElement(stats_elem, 'user-messages').text = str(metadata['user_messages'])
    ET.SubElement(stats_elem, 'assistant-messages').text = str(metadata['assistant_messages'])
    ET.SubElement(stats_elem, 'tool-uses').text = str(metadata['tool_uses'])

    models_elem = ET.SubElement(stats_elem, 'models-used')
    for model in metadata['models_used']:
        ET.SubElement(models_elem, 'model').text = model

    messages_elem = ET.SubElement(root, 'messages')
    for msg in messages:
        format_message_xml(msg, messages_elem)

    xml_path = export_dir / 'conversation_full.xml'
    xml_string = prettify_xml(root)
    with open(xml_path, 'w', encoding='utf-8') as f:
        f.write(xml_string)

    # Generate summary
    summary_path = export_dir / 'summary.txt'
    with open(summary_path, 'w', encoding='utf-8') as f:
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
    """Copy files to a directory, or write an empty marker if no files."""
    target_dir.mkdir(exist_ok=True)
    if files:
        for f in files:
            shutil.copy2(f, target_dir / f.name)
    else:
        write_empty_marker(target_dir, empty_message)


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

    # Auto-generate export name if not provided
    if not export_name:
        timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d_%H-%M-%S')
        export_name = f"{timestamp}_{session_id[:8]}" if mode == 'classic' else timestamp

    # Determine output directory
    if output_dir:
        export_dir = Path(output_dir) / export_name
    elif mode == 'portable':
        export_dir = project_path / '.claude-sessions' / export_name
    else:
        export_dir = Path.home() / 'claude_sessions' / 'exports' / export_name

    export_dir.mkdir(parents=True, exist_ok=True)

    # Write legacy files (both modes)
    print("\U0001f4dd Writing legacy files...")
    _write_legacy_files(export_dir, session_info['path'], messages, metadata)

    if mode == 'classic':
        return export_dir, None

    # =========================================================================
    # Portable mode: collect and write enhanced structure
    # =========================================================================
    print("\U0001f4e6 Collecting session data...")

    # The claude project dir is the parent of the session file
    # (e.g., ~/.claude/projects/-home-rshu-ccsession/)
    claude_project_dir = session_info['path'].parent

    agent_sessions = collect_agent_sessions(claude_project_dir, session_id, messages)
    file_history = collect_file_history(session_id)
    plan_file = collect_plan_file(slug)
    todos = collect_todos(session_id)
    session_env = collect_session_env(session_id)
    tool_results = collect_tool_results(claude_project_dir, session_id)

    session_files = {
        'agents': agent_sessions,
        'file_history': file_history,
        'plan': plan_file,
        'todos': todos,
        'session_env': session_env,
        'tool_results': tool_results,
    }

    # Collect project config
    print("\U0001f4e6 Collecting project config...")
    config_files = collect_project_config(project_path)

    # Generate manifest
    manifest = generate_manifest(
        session_id, slug, export_name, metadata, msg_meta,
        session_files, config_files, project_path
    )

    # Write session data
    print("\U0001f4dd Writing session data...")

    session_dir = export_dir / 'session'
    session_dir.mkdir(exist_ok=True)

    # Main session
    shutil.copy2(session_info['path'], session_dir / 'main.jsonl')

    # Agent sessions
    agents_dir = session_dir / 'agents'
    agents_dir.mkdir(exist_ok=True)
    if agent_sessions:
        for agent_id, agent_path in agent_sessions.items():
            shutil.copy2(agent_path, agents_dir / f'agent-{agent_id}.jsonl')
    else:
        write_empty_marker(agents_dir, "No agent sessions for this export.")

    # File history
    _copy_files_to_dir(file_history, session_dir / 'file-history',
                       "No file history snapshots for this session.")

    # Plan file
    if plan_file:
        shutil.copy2(plan_file, session_dir / 'plan.md')
    else:
        (session_dir / 'plan.md').write_text("# No Plan\n\nNo plan file was created for this session.\n", encoding='utf-8')

    # Todos
    if todos:
        all_todos = []
        for todo_file in todos:
            try:
                with open(todo_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        all_todos.extend(data)
                    else:
                        all_todos.append(data)
            except (json.JSONDecodeError, OSError):
                pass
        write_json(session_dir / 'todos.json', all_todos)
    else:
        write_json(session_dir / 'todos.json', [])

    # Tool results
    _copy_files_to_dir(tool_results, session_dir / 'tool-results',
                       "No tool-result sidecars for this session.")

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
    print("\U0001f4dd Writing config snapshot...")

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
        _copy_files_to_dir(config_files[config_key], config_dir / subdir, empty_msg)

    if config_files['settings']:
        shutil.copy2(config_files['settings'], config_dir / 'settings.json')
    else:
        (config_dir / 'settings.json').write_text('{}', encoding='utf-8')

    if config_files['claude_md']:
        shutil.copy2(config_files['claude_md'], config_dir / 'CLAUDE.md')
    else:
        (config_dir / 'CLAUDE.md').write_text('# No CLAUDE.md\n\nNo CLAUDE.md file in project.\n', encoding='utf-8')

    # Write trajectory, manifest, and RENDERED.md
    print("\U0001f4dd Writing trajectory.json...")
    trajectory = format_trajectory(
        messages, metadata, msg_meta,
        agent_sessions=agent_sessions,
    )
    write_json(export_dir / 'trajectory.json', trajectory)

    print("\U0001f4dd Writing manifest and RENDERED.md...")
    write_json(export_dir / '.ccsession-manifest.json', manifest)

    rendered_md = generate_rendered_markdown(messages, metadata, manifest)
    rendered_path = export_dir / 'RENDERED.md'
    with open(rendered_path, 'w', encoding='utf-8') as f:
        f.write(rendered_md)

    return export_dir, manifest
