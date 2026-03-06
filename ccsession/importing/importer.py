from __future__ import annotations

from pathlib import Path

from ccsession.paths import get_projects_dir, get_import_storage_dir
from ccsession.importing.validation import validate_manifest, check_version_compatibility
from ccsession.importing.uuids import generate_new_session_id, regenerate_message_uuids
from ccsession.importing.snapshot import create_snapshot
from ccsession.importing.session_io import read_session_jsonl, write_session_file
from ccsession.importing.auxiliary import import_file_history, import_todos, import_plan
from ccsession.importing.config import import_config, add_claude_md_note
from ccsession.importing.import_log import log_import


def import_session(export_path: Path, project_path: Path | None = None,
                   preserve_session_id: bool = False,
                   skip_config: bool = False,
                   skip_auxiliary: bool = False,
                   non_interactive: bool = False) -> dict:
    """Main import orchestrator.

    Args:
        export_path: Path to the export directory
        project_path: Target project path (default: current directory)
        preserve_session_id: Keep original session ID
        skip_config: Don't import config files
        skip_auxiliary: Don't import file-history/todos/plan
        non_interactive: No prompts

    Returns:
        dict: Import summary
    """
    if project_path is None:
        project_path = Path.cwd()

    project_path = Path(project_path).resolve()
    export_path = Path(export_path).resolve()

    print(f"\U0001f50d Validating export at: {export_path}")

    # 1. Validate manifest
    manifest = validate_manifest(export_path)
    print(f"\u2713 Valid ccsession export (v{manifest.get('ccsession_version', 'unknown')})")

    original_context = manifest.get('original_context', {})
    print(f"\u2713 Exported by: {original_context.get('user', 'Unknown')}")
    print(f"\u2713 Original platform: {original_context.get('platform', 'Unknown')}")

    # 2. Check version compatibility
    is_compatible, warning = check_version_compatibility(manifest)
    if warning:
        print(f"\u26a0\ufe0f  {warning}")
        if not non_interactive:
            response = input("Continue? (y/n): ")
            if response.lower() != 'y':
                print("Import aborted.")
                return None

    # 3. Check for conflicts
    target_dir = get_projects_dir(project_path)
    old_session_id = manifest.get('session_id')

    if preserve_session_id:
        new_session_id = old_session_id
        target_session_path = target_dir / f'{new_session_id}.jsonl'

        if target_session_path.exists():
            raise FileExistsError(
                f"Session ID {new_session_id} already exists locally.\n"
                "Import aborted. Options:\n"
                "  - Use default import (generates new session ID)\n"
                "  - Manually delete existing session at {target_session_path}"
            )
    else:
        new_session_id = generate_new_session_id()
        target_session_path = target_dir / f'{new_session_id}.jsonl'

    print(f"\n\U0001f4e5 Importing as session: {new_session_id}")
    if old_session_id != new_session_id:
        print(f"   (Original: {old_session_id})")

    # 4. Create pre-import snapshot
    import_storage_dir = get_import_storage_dir()
    import_storage_dir.mkdir(parents=True, exist_ok=True)

    print("\n\U0001f4f8 Creating pre-import snapshot...")
    snapshot_path = create_snapshot(target_dir, import_storage_dir)
    print(f"   Snapshot saved to: {snapshot_path}")

    # 5. Process session
    print("\n\U0001f4dd Processing session...")

    # Find session file - prefer session/main.jsonl, fallback to raw_messages.jsonl
    session_data = manifest.get('session_data', {})
    main_session_path = session_data.get('main_session')

    source_session_path = None
    if main_session_path:
        source_session_path = export_path / main_session_path
    if not source_session_path or not source_session_path.exists():
        source_session_path = export_path / 'raw_messages.jsonl'

    if not source_session_path.exists():
        raise FileNotFoundError(f"Session file not found in export: {export_path}")

    messages = read_session_jsonl(source_session_path)
    print(f"   Read {len(messages)} messages")

    # Regenerate UUIDs unless preserving
    if not preserve_session_id:
        messages = regenerate_message_uuids(messages, new_session_id, str(project_path))
        print(f"   Regenerated UUIDs and updated cwd")
    else:
        # Still need to update cwd
        for msg in messages:
            if 'cwd' in msg:
                msg['cwd'] = str(project_path)

    # 6. Write session file
    print(f"\n\U0001f4be Writing session file...")
    write_session_file(messages, target_session_path)
    print(f"   \u2713 Wrote session to: {target_session_path}")

    # 7. Import auxiliary files
    summary = {
        'session_file': str(target_session_path),
        'file_history_count': 0,
        'todos_imported': False,
        'plan_imported': False,
        'config': {}
    }

    if not skip_auxiliary:
        print(f"\n\U0001f4e6 Importing auxiliary files...")

        # File history
        fh_count = import_file_history(export_path, manifest, new_session_id)
        summary['file_history_count'] = fh_count
        print(f"   \u2713 File history: {fh_count} snapshots")

        # Todos
        todos_imported = import_todos(export_path, manifest, new_session_id)
        summary['todos_imported'] = todos_imported > 0
        print(f"   \u2713 Todos: {'imported' if todos_imported else 'none'}")

        # Plan
        plan_imported = import_plan(export_path, manifest)
        summary['plan_imported'] = plan_imported
        print(f"   \u2713 Plan: {'imported' if plan_imported else 'skipped/none'}")

    # 8. Import config files
    if not skip_config:
        print(f"\n\u2699\ufe0f  Importing config files...")
        config_summary = import_config(export_path, manifest, project_path)
        summary['config'] = config_summary

        total_config = sum([
            config_summary['commands'],
            config_summary['skills'],
            config_summary['hooks'],
            config_summary['agents'],
            config_summary['rules']
        ])

        if total_config > 0:
            print(f"   \u2713 Imported {total_config} config files:")
            if config_summary['commands']:
                print(f"      - {config_summary['commands']} commands")
            if config_summary['skills']:
                print(f"      - {config_summary['skills']} skills")
            if config_summary['hooks']:
                print(f"      - {config_summary['hooks']} hooks")
            if config_summary['agents']:
                print(f"      - {config_summary['agents']} agents")
            if config_summary['rules']:
                print(f"      - {config_summary['rules']} rules")

        if config_summary['conflicts']:
            print(f"   \u26a0\ufe0f  Skipped {len(config_summary['conflicts'])} files (already exist)")

    # 9. Add CLAUDE.md note
    print(f"\n\U0001f4dd Adding import context to CLAUDE.md...")
    add_claude_md_note(project_path, manifest)
    print(f"   \u2713 Updated CLAUDE.md")

    # 10. Log import
    log_path = log_import(import_storage_dir, manifest, new_session_id,
                          target_session_path, summary)

    print(f"\n\u2705 Import complete!")
    print(f"   Session: {manifest.get('session_slug', new_session_id[:8])}")
    print(f"   Session ID: {new_session_id}")
    print(f"   Log: {log_path}")
    print(f"\n\U0001f4a1 To continue this session:")
    print(f"   cd {project_path}")
    print(f"   claude -c")
    print(f"\n\u26a0\ufe0f  If problems occur: python ccsession.py restore --restore")

    return summary
