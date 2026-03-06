"""ccsession CLI — export, import, and restore Claude Code sessions."""
from __future__ import annotations

import os
import sys
import argparse
from pathlib import Path

from ccsession.output import info, detail, error, success, set_verbosity, QUIET, NORMAL, VERBOSE


def cmd_export(args: argparse.Namespace) -> int:
    """Export the current Claude Code session."""
    from ccsession.export.session_discovery import find_project_sessions, find_session_by_id, select_session
    from ccsession.export.exporter import export_session

    cwd = os.getcwd()

    if args.session_id:
        info(f"\U0001f50d Looking for session: {args.session_id}")
        session_to_export = find_session_by_id(args.session_id)
        if not session_to_export:
            error(f"\u274c Session not found: {args.session_id}")
            error("   Searched all projects in ~/.claude/projects/")
            return 1
        info(f"\U0001f4c2 Found session in project: {session_to_export.get('project_dir', 'unknown')}")
    else:
        info(f"\U0001f50d Looking for Claude Code sessions in: {cwd}")

        sessions = find_project_sessions(cwd)
        if not sessions:
            error("\u274c No Claude Code sessions found for this project.")
            error("   Make sure you're running this from a project directory with active Claude Code sessions.")
            return 1

        info(f"\U0001f4c2 Found {len(sessions)} session(s) for this project")

        session_to_export = select_session(sessions, project_dir=cwd)

    info(f"\n\U0001f4e4 Exporting session file: {session_to_export['session_id'][:8]}...")

    output_dir = Path(args.output_dir) if args.output_dir else None
    export_path, manifest = export_session(
        session_to_export, cwd,
        export_name=args.export_name,
        output_dir=output_dir,
        mode=args.mode,
    )

    if manifest:
        # Portable mode
        success(f"\n\u2705 Export completed successfully!")
        info(f"\U0001f4c1 Export directory: {export_path}")
        info(f"\n\U0001f4cb Export Summary:")
        info(f"   Session ID: {manifest['session_id']}")
        if manifest.get('session_slug'):
            info(f"   Session Name: {manifest['session_slug']}")
        info(f"   Messages: {manifest['statistics']['message_count']}")
        info(f"   Tool Uses: {manifest['statistics']['tool_uses']}")
        info(f"   Agent Sessions: {len(manifest['session_data']['agent_sessions'])}")
        info(f"   File History: {len(manifest['session_data']['file_history'])} snapshots")

        detail(f"\nFiles created:")
        detail(f"  Legacy files:")
        for name in ['raw_messages.jsonl', 'conversation_full.md', 'conversation_full.xml',
                     'session_info.json', 'summary.txt']:
            if (export_path / name).exists():
                detail(f"    - {name}")

        detail(f"  Enhanced structure:")
        for name in ['session/main.jsonl', 'session/agents/', 'session/file-history/',
                     'session/plan.md', 'session/todos.json', 'config/',
                     'trajectory.json', 'RENDERED.md', '.ccsession-manifest.json']:
            detail(f"    - {name}")

        info(f"\n\U0001f4a1 Next steps:")
        export_name = args.export_name or export_path.name
        try:
            rel_path = export_path.relative_to(cwd)
        except ValueError:
            rel_path = export_path
        info(f"   git add {rel_path}")
        info(f"   git commit -m \"Export Claude Code session: {export_name}\"")
    else:
        # Classic mode
        success(f"\n\u2705 Session exported successfully!")
        info(f"\U0001f4c1 Output directory: {export_path}")
        detail(f"\nFiles created:")
        for file in export_path.iterdir():
            detail(f"  - {file.name}")

    return 0


def cmd_import(args: argparse.Namespace) -> int:
    """Import a ccsession session export into Claude Code."""
    from ccsession.importing.importer import import_session

    summary = import_session(
        export_path=args.export_path,
        project_path=args.project_path,
        preserve_session_id=args.preserve_session_id,
        skip_config=args.skip_config,
        skip_auxiliary=args.skip_auxiliary,
        non_interactive=args.non_interactive,
    )
    return 0 if summary else 1


def cmd_restore(args: argparse.Namespace) -> int:
    """Restore from pre-import snapshot."""
    from ccsession.restore import restore_snapshot, show_info

    if args.restore:
        result = restore_snapshot(force=args.yes)
        return 0 if result.get('restored') else 1
    else:
        return show_info()


def run_command(fn, args: argparse.Namespace) -> int:
    """Run a CLI command with shared error handling."""
    try:
        return fn(args)
    except ValueError as e:
        error(f"\u274c {e}")
        return 1
    except ImportError as e:
        error(f"\u274c Import validation failed:\n   {e}")
        return 1
    except FileExistsError as e:
        error(f"\u274c Conflict detected:\n   {e}")
        return 1
    except FileNotFoundError as e:
        error(f"\u274c File not found:\n   {e}")
        return 1
    except RuntimeError as e:
        error(f"\u274c {e}")
        return 1
    except KeyboardInterrupt:
        error("\n\n\u274c Cancelled by user.")
        return 1
    except Exception as e:
        error(f"\u274c Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        prog='ccsession',
        description='Export, import, and restore Claude Code sessions',
    )

    verbosity = parser.add_mutually_exclusive_group()
    verbosity.add_argument('--quiet', '-q', action='store_true',
                           help='Suppress informational output')
    verbosity.add_argument('--verbose', '-v', action='store_true',
                           help='Show detailed output')

    subparsers = parser.add_subparsers(dest='command', required=True)

    # --- export ---
    p_export = subparsers.add_parser('export', help='Export the current session')
    p_export.add_argument('--session-id', help='Session ID to export (searches all projects)')
    p_export.add_argument('--output-dir', help='Custom output directory')
    p_export.add_argument('--export-name', help='Name for the export folder')
    p_export.add_argument('--mode', choices=['portable', 'classic'], default='portable',
                          help='Export mode (default: portable)')

    # --- import ---
    p_import = subparsers.add_parser('import', help='Import a session export')
    p_import.add_argument('export_path', type=Path,
                          help='Path to .claude-sessions/<name>/ directory')
    p_import.add_argument('--project-path', type=Path, default=None,
                          help='Target project path (default: current directory)')
    p_import.add_argument('--preserve-session-id', action='store_true',
                          help='Keep original session ID (fails on conflict)')
    p_import.add_argument('--skip-config', action='store_true',
                          help="Don't import config files")
    p_import.add_argument('--skip-auxiliary', action='store_true',
                          help="Don't import file-history, todos, or plan")
    p_import.add_argument('--non-interactive', action='store_true',
                          help='No prompts, use defaults')

    # --- restore ---
    p_restore = subparsers.add_parser('restore', help='Restore from pre-import snapshot')
    p_restore.add_argument('--restore', action='store_true',
                           help='Perform the restore operation (requires confirmation)')
    p_restore.add_argument('--yes', action='store_true',
                           help='Skip confirmation prompt (DANGEROUS)')

    args = parser.parse_args()

    # Set verbosity before dispatching
    if args.quiet:
        set_verbosity(QUIET)
    elif args.verbose:
        set_verbosity(VERBOSE)

    dispatch = {
        'export': cmd_export,
        'import': cmd_import,
        'restore': cmd_restore,
    }
    return run_command(dispatch[args.command], args)


if __name__ == '__main__':
    sys.exit(main())
