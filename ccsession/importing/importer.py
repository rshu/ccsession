from __future__ import annotations

from pathlib import Path

from ccsession.paths import get_projects_dir, get_import_storage_dir, get_file_history_dir
from ccsession.importing.validation import validate_manifest, check_version_compatibility, resolve_export_path
from ccsession.importing.uuids import generate_new_session_id
from ccsession.importing.remap import build_remap_plan, most_common_cwd, remap_records
from ccsession.importing.snapshot import create_snapshot
from ccsession.importing.session_io import read_session_jsonl, write_session_file
from ccsession.importing.auxiliary import import_file_history
from ccsession.importing.session_dir import import_session_dir, import_history
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
        skip_auxiliary: Don't import file history or prompt history
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
                f"  - Manually delete existing session at {target_session_path}"
            )
    else:
        new_session_id = generate_new_session_id()
        target_session_path = target_dir / f'{new_session_id}.jsonl'

    target_session_dir = target_dir / new_session_id
    if target_session_dir.exists() and any(target_session_dir.iterdir()):
        raise FileExistsError(
            f"Session directory already exists and is not empty: {target_session_dir}\n"
            "Import aborted to prevent mixing two sessions' files."
        )

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

    # Main transcript
    session_data = manifest.get('session_data', {})
    main_session_path = session_data.get('main_session')

    if not main_session_path:
        raise ImportError("Manifest does not name a main_session transcript.")
    source_session_path = resolve_export_path(export_path, main_session_path)
    if not source_session_path.is_file():
        raise FileNotFoundError(f"Session file not found in export: {source_session_path}")

    messages = read_session_jsonl(source_session_path)
    print(f"   Read {len(messages)} messages")

    # Rewrite ids (unless preserving) and relocate paths consistently across the
    # main transcript and every sub-agent transcript
    agent_records = _read_agent_transcripts(export_path, manifest)
    plan = build_remap_plan(
        messages, agent_records,
        old_session_id=old_session_id, new_session_id=new_session_id,
        old_project_path=most_common_cwd(messages) or manifest.get('original_context', {}).get('repo_path'),
        new_project_path=project_path,
        new_session_dir=target_dir / new_session_id,
        new_file_history_dir=get_file_history_dir(new_session_id),
        regenerate_ids=not preserve_session_id,
    )
    messages = remap_records(messages, plan)
    print("   Regenerated ids and relocated paths" if not preserve_session_id
          else "   Relocated paths (ids preserved)")

    # 6. Write the session directory first: a populated target (possible with
    # --preserve-session-id) must abort before the transcript is written.
    print(f"\n\U0001f4be Writing session files...")
    dir_result = import_session_dir(export_path, manifest, target_session_dir, plan)
    if dir_result.files:
        print(f"   \u2713 Session directory: {dir_result.files} files "
              f"({dir_result.agents} sub-agent transcripts)")
    write_session_file(messages, target_session_path)
    print(f"   \u2713 Wrote session to: {target_session_path}")

    # 7. Import auxiliary files
    summary = {
        'session_id': new_session_id,
        'session_file': str(target_session_path),
        'session_dir_files': dir_result.files,
        'agent_sessions': dir_result.agents,
        'history_lines': 0,
        'file_history_count': 0,
        'config': {}
    }

    if not skip_auxiliary:
        print(f"\n\U0001f4e6 Importing auxiliary files...")

        # File history
        fh_count = import_file_history(export_path, manifest, new_session_id)
        summary['file_history_count'] = fh_count
        print(f"   \u2713 File history: {fh_count} snapshots")

        # Prompt history
        history_lines = import_history(export_path, manifest, plan, project_path)
        summary['history_lines'] = history_lines
        print(f"   \u2713 Prompt history: {history_lines} lines")

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

    label = manifest.get('session_slug') or new_session_id
    print(f"\n\u2705 Import complete!")
    print(f"   Session: {label}")
    print(f"   Session ID: {new_session_id}")
    print(f"   Log: {log_path}")
    print(f"\n\U0001f4a1 To continue this session:")
    print(f"   cd {project_path}")
    print(f"   claude --resume {new_session_id}")
    print(f"\n\u26a0\ufe0f  If problems occur: ccsession restore --restore")

    return summary


def _read_agent_transcripts(export_path: Path, manifest: dict) -> dict[str, list[dict]]:
    """Sub-agent transcripts in the export, keyed by agent id, for id-map building."""
    agents: dict[str, list[dict]] = {}
    for relative in manifest.get('session_data', {}).get('agent_sessions', []):
        path = resolve_export_path(export_path, relative)
        name = path.name
        if path.is_file() and name.startswith('agent-') and name.endswith('.jsonl'):
            agents[name[len('agent-'):-len('.jsonl')]] = read_session_jsonl(path)
    return agents
