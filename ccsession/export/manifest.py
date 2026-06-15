from __future__ import annotations

import getpass
import sys
from pathlib import Path

from ccsession import CCSESSION_VERSION
from ccsession.utils import utc_now_iso, parse_iso_timestamp
from ccsession.export.formatters import format_message_markdown


def generate_manifest(session_id: str, slug: str | None, export_name: str, metadata: dict,
                     message_metadata: dict, session_files: dict, config_files: dict,
                     project_path: str | Path) -> dict:
    """Generate the .ccsession-manifest.json content.

    Args:
        message_metadata: dict with 'version', 'git_branch', 'slug' from extract_message_metadata()
    """
    manifest = {
        "ccsession_version": CCSESSION_VERSION,
        "export_timestamp": utc_now_iso(),
        "session_id": session_id,
        "session_slug": slug,
        "export_name": export_name,
        "claude_code_version": message_metadata.get('version'),

        "original_context": {
            "user": getpass.getuser(),
            "platform": sys.platform,
            "repo_path": str(project_path),
            "git_branch": message_metadata.get('git_branch')
        },

        "session_data": {
            "main_session": "session/main.jsonl",
            "agent_sessions": [f"session/agents/{Path(f).name}" for f in session_files.get('agents', {}).values()],
            "file_history": [f"session/file-history/{Path(f).name}" for f in session_files.get('file_history', [])],
            "plan_file": "session/plan.md" if session_files.get('plan') else None,
            "todos": "session/todos.json" if session_files.get('todos') else None,
            "session_env": "session/session-env/" if session_files.get('session_env') else None,
            "tool_results": [f"session/tool-results/{Path(f).name}" for f in session_files.get('tool_results', [])]
        },

        "config_snapshot": {
            "commands": [f"config/commands/{Path(f).name}" for f in config_files.get('commands', [])],
            "skills": [f"config/skills/{Path(f).name}" for f in config_files.get('skills', [])],
            "hooks": [f"config/hooks/{Path(f).name}" for f in config_files.get('hooks', [])],
            "agents": [f"config/agents/{Path(f).name}" for f in config_files.get('agents', [])],
            "rules": [f"config/rules/{Path(f).name}" for f in config_files.get('rules', [])],
            "settings": "config/settings.json" if config_files.get('settings') else None,
            "claude_md": "config/CLAUDE.md" if config_files.get('claude_md') else None
        },

        "statistics": {
            "message_count": metadata['total_messages'],
            "user_messages": metadata['user_messages'],
            "assistant_messages": metadata['assistant_messages'],
            "tool_uses": metadata['tool_uses'],
            "duration_seconds": None,  # Could calculate from timestamps
            "models_used": metadata['models_used']
        }
    }

    # Calculate duration if we have timestamps
    if metadata.get('start_time') and metadata.get('end_time'):
        try:
            start = parse_iso_timestamp(metadata['start_time'])
            end = parse_iso_timestamp(metadata['end_time'])
            manifest['statistics']['duration_seconds'] = int((end - start).total_seconds())
        except (ValueError, TypeError, KeyError):
            pass

    return manifest


def generate_rendered_markdown(messages: list[dict], metadata: dict, manifest: dict) -> str:
    """Generate RENDERED.md - a GitHub-optimized view of the session."""
    lines = []

    # Header
    lines.append(f"# Claude Code Session: {manifest['export_name']}")
    lines.append("")
    lines.append(f"> Exported from ccsession v{CCSESSION_VERSION}")
    lines.append("")

    # Session info table
    lines.append("## Session Info")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("|-------|-------|")
    lines.append(f"| Session ID | `{manifest['session_id']}` |")
    if manifest['session_slug']:
        lines.append(f"| Session Name | {manifest['session_slug']} |")
    lines.append(f"| Project | `{manifest['original_context']['repo_path']}` |")
    if manifest['original_context']['git_branch']:
        lines.append(f"| Git Branch | `{manifest['original_context']['git_branch']}` |")
    lines.append(f"| Claude Code | v{manifest['claude_code_version']} |")
    lines.append(f"| Messages | {manifest['statistics']['message_count']} |")
    lines.append(f"| Tool Uses | {manifest['statistics']['tool_uses']} |")
    if manifest['statistics']['duration_seconds']:
        duration = manifest['statistics']['duration_seconds']
        if duration > 3600:
            duration_str = f"{duration // 3600}h {(duration % 3600) // 60}m"
        elif duration > 60:
            duration_str = f"{duration // 60}m {duration % 60}s"
        else:
            duration_str = f"{duration}s"
        lines.append(f"| Duration | {duration_str} |")
    lines.append(f"| Models | {', '.join(manifest['statistics']['models_used'])} |")
    lines.append("")

    # Session data summary
    lines.append("## Session Data")
    lines.append("")
    lines.append("| Component | Status |")
    lines.append("|-----------|--------|")
    lines.append(f"| Main Session | \u2705 `session/main.jsonl` |")
    agent_count = len(manifest['session_data']['agent_sessions'])
    agent_status = f"\u2705 {agent_count} files" if agent_count else "\u2796 None"
    lines.append(f"| Agent Sessions | {agent_status} |")
    fh_count = len(manifest['session_data']['file_history'])
    fh_status = f"\u2705 {fh_count} snapshots" if fh_count else "\u2796 None"
    lines.append(f"| File History | {fh_status} |")
    plan_status = "\u2705 Included" if manifest['session_data']['plan_file'] else "\u2796 None"
    lines.append(f"| Plan File | {plan_status} |")
    todo_status = "\u2705 Included" if manifest['session_data']['todos'] else "\u2796 None"
    lines.append(f"| Todos | {todo_status} |")
    lines.append("")

    # Config summary
    lines.append("## Project Config")
    lines.append("")
    lines.append("| Component | Status |")
    lines.append("|-----------|--------|")
    cmd_count = len(manifest['config_snapshot']['commands'])
    cmd_status = f"\u2705 {cmd_count} files" if cmd_count else "\u2796 None"
    lines.append(f"| Commands | {cmd_status} |")
    skill_count = len(manifest['config_snapshot']['skills'])
    skill_status = f"\u2705 {skill_count} files" if skill_count else "\u2796 None"
    lines.append(f"| Skills | {skill_status} |")
    hook_count = len(manifest['config_snapshot']['hooks'])
    hook_status = f"\u2705 {hook_count} files" if hook_count else "\u2796 None"
    lines.append(f"| Hooks | {hook_status} |")
    agent_cfg_count = len(manifest['config_snapshot']['agents'])
    agent_cfg_status = f"\u2705 {agent_cfg_count} files" if agent_cfg_count else "\u2796 None"
    lines.append(f"| Agents | {agent_cfg_status} |")
    rule_count = len(manifest['config_snapshot']['rules'])
    rule_status = f"\u2705 {rule_count} files" if rule_count else "\u2796 None"
    lines.append(f"| Rules | {rule_status} |")
    settings_status = "\u2705 Included" if manifest['config_snapshot']['settings'] else "\u2796 None"
    lines.append(f"| Settings | {settings_status} |")
    claude_md_status = "\u2705 Included" if manifest['config_snapshot']['claude_md'] else "\u2796 None"
    lines.append(f"| CLAUDE.md | {claude_md_status} |")
    lines.append("")

    # Conversation
    lines.append("---")
    lines.append("")
    lines.append("## Conversation")
    lines.append("")

    for msg in messages:
        formatted = format_message_markdown(msg)
        if formatted:
            lines.append(formatted)
            lines.append("")
            lines.append("---")
            lines.append("")

    return '\n'.join(lines)


def write_empty_marker(directory: Path, message: str) -> None:
    """Write an _empty marker file in a directory."""
    marker_path = directory / '_empty'
    marker_path.write_text(message, encoding='utf-8')
