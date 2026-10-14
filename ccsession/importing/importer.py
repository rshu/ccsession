from __future__ import annotations

import sys
import uuid
from pathlib import Path

from ccsession.errors import InvalidExportError
from ccsession.paths import claude_code_path_text, get_projects_dir, get_import_storage_dir, get_file_history_dir
from ccsession.importing.validation import validate_manifest, check_version_compatibility, resolve_export_path
from ccsession.importing.uuids import generate_new_session_id
from ccsession.importing.remap import build_remap_plan, most_common_cwd, remap_records
from ccsession.importing.snapshot import ImportJournal, create_snapshot, record_import_artifacts
from ccsession.importing.session_io import read_session_jsonl, write_session_file
from ccsession.importing.auxiliary import import_file_history, resolve_file_history_sources
from ccsession.importing.session_dir import (
    append_history, prepare_session_dir, read_export_history, rewrite_history_records, write_session_dir,
)
from ccsession.importing.config import (
    add_claude_md_note, apply_config_import, claude_md_note, new_config_summary, plan_config_import,
)
from ccsession.importing.import_log import log_import
from ccsession.output import error, info, success, warn

_CONFIG_TYPE_NAMES = ('commands', 'skills', 'hooks', 'agents', 'rules')


def import_session(export_path: Path, project_path: Path | None = None,
                   preserve_session_id: bool = False,
                   skip_config: bool = False,
                   skip_auxiliary: bool = False,
                   non_interactive: bool = False) -> dict:
    """Main import orchestrator.

    Everything that depends on the export -- manifest validation, conflict checks,
    reading and rewriting every transcript, sidecar and history record, confining
    every manifest path -- happens before the pre-import snapshot is taken, so a bad
    export never replaces the snapshot of the previous import. Writes start only
    after the snapshot exists, and each one is first recorded in the snapshot's
    journal, so whatever ends the import part-way, a restore can undo it.

    Args:
        export_path: Path to the export directory
        project_path: Target project path (default: current directory)
        preserve_session_id: Keep original session ID
        skip_config: Don't import config files or touch CLAUDE.md
        skip_auxiliary: Don't import file history or prompt history
        non_interactive: No prompts

    Returns:
        dict: Import summary, or None when the user declined to continue
    """
    if project_path is None:
        project_path = Path.cwd()

    project_path = Path(project_path).resolve()
    if not project_path.is_dir():
        raise FileNotFoundError(f"Project directory does not exist: {project_path}")
    export_path = Path(export_path).resolve()

    info(f"\U0001f50d Validating export at: {export_path}")

    # 1. Validate manifest
    manifest = validate_manifest(export_path)
    info(f"✓ Valid ccsession export (v{manifest.get('ccsession_version', 'unknown')})")

    original_context = manifest.get('original_context', {})
    info(f"✓ Exported by: {original_context.get('user', 'Unknown')}")
    info(f"✓ Original platform: {original_context.get('platform', 'Unknown')}")

    # 2. Check version compatibility
    is_compatible, warning = check_version_compatibility(manifest)
    if warning:
        warn(f"⚠️  {warning}")
        if not non_interactive and not _confirm("Continue? (y/n): "):
            info("Import aborted.")
            return None

    # 3. Check for conflicts
    target_dir = get_projects_dir(project_path)
    old_session_id = manifest.get('session_id')

    if preserve_session_id:
        _require_canonical_uuid(old_session_id)
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

    info(f"\n\U0001f4e5 Importing as session: {new_session_id}")
    if old_session_id != new_session_id:
        info(f"   (Original: {old_session_id})")

    # 4. Read and remap the transcripts; check every other manifest path and sidecar
    info("\n\U0001f4dd Processing session...")

    session_data = manifest.get('session_data', {})
    main_session_path = session_data.get('main_session')

    if not main_session_path:
        raise InvalidExportError("Manifest does not name a main_session transcript.")
    source_session_path = resolve_export_path(export_path, main_session_path)
    if not source_session_path.is_file():
        raise FileNotFoundError(f"Session file not found in export: {source_session_path}")

    try:
        messages = read_session_jsonl(source_session_path)
    except UnicodeDecodeError as e:
        raise InvalidExportError(f"The session transcript {main_session_path} is not valid UTF-8: {e}")
    except RecursionError:
        raise InvalidExportError("The session transcript holds a record nested too deeply to process.")
    info(f"   Read {len(messages)} messages")

    # The project path as Claude Code records it (undecodable bytes become U+FFFD)
    project_text = claude_code_path_text(project_path)

    # Rewrite ids (unless preserving) and relocate paths consistently across the
    # main transcript and every sub-agent transcript
    try:
        agent_records = _read_agent_transcripts(export_path, manifest)
    except UnicodeDecodeError as e:
        raise InvalidExportError(f"A sub-agent transcript is not valid UTF-8: {e}")
    except RecursionError:
        raise InvalidExportError("A sub-agent transcript holds a record nested too deeply to process.")
    plan = build_remap_plan(
        messages, agent_records,
        old_session_id=old_session_id, new_session_id=new_session_id,
        old_project_path=most_common_cwd(messages) or manifest.get('original_context', {}).get('repo_path'),
        new_project_path=project_text,
        new_session_dir=target_dir / new_session_id,
        new_file_history_dir=get_file_history_dir(new_session_id),
        regenerate_ids=not preserve_session_id,
    )
    try:
        messages = remap_records(messages, plan)
    except RecursionError:
        raise InvalidExportError("The session transcript holds a record nested too deeply to process.")
    info("   Regenerated ids and relocated paths" if not preserve_session_id
         else "   Relocated paths (ids preserved)")

    prepared_session_dir = prepare_session_dir(export_path, manifest, plan)
    history_records = [] if skip_auxiliary else read_export_history(export_path, manifest)
    rewrite_history_records(history_records, plan, project_text)  # refuse what cannot be processed, now
    file_history_sources = [] if skip_auxiliary else resolve_file_history_sources(export_path, manifest)
    config_plan = None if skip_config else plan_config_import(export_path, manifest, project_path)

    # 5. Create pre-import snapshot (nothing above has written anything)
    import_storage_dir = get_import_storage_dir()
    import_storage_dir.mkdir(parents=True, exist_ok=True)

    info("\n\U0001f4f8 Creating pre-import snapshot...")
    snapshot_path = create_snapshot(target_dir, import_storage_dir,
                                    project_path=project_path, new_session_id=new_session_id,
                                    export_name=manifest.get('export_name'), export_path=export_path)
    info(f"   Snapshot saved to: {snapshot_path}")

    try:
        summary = _write_everything(
            export_path, manifest, plan, messages,
            project_path=project_path, project_text=project_text, new_session_id=new_session_id,
            target_session_path=target_session_path, target_session_dir=target_session_dir,
            prepared_session_dir=prepared_session_dir,
            history_records=history_records, file_history_sources=file_history_sources,
            config_plan=config_plan, skip_auxiliary=skip_auxiliary, snapshot_path=snapshot_path,
        )
    except BaseException:
        error("\n❌ The import failed after the snapshot was taken.")
        error("   Run `ccsession restore --restore` to roll back whatever was written.")
        raise

    # 10. Log import
    log_path = log_import(import_storage_dir, manifest, new_session_id,
                          target_session_path, summary)

    label = manifest.get('session_slug') or new_session_id
    success(f"\n✅ Import complete!")
    info(f"   Session: {label}")
    success(f"   Session ID: {new_session_id}")
    info(f"   Log: {log_path}")
    info(f"\n\U0001f4a1 To continue this session:")
    info(f"   cd {project_path}")
    success(f"   claude --resume {new_session_id}")
    info(f"\n⚠️  If problems occur: ccsession restore --restore")

    return summary


def _write_everything(export_path: Path, manifest: dict, plan, messages: list, *,
                      project_path: Path, project_text: str, new_session_id: str,
                      target_session_path: Path, target_session_dir: Path,
                      prepared_session_dir: list,
                      history_records: list, file_history_sources: list, config_plan: dict | None,
                      skip_auxiliary: bool, snapshot_path: Path) -> dict:
    """Steps 6-9: every write of the import, in an order that fails as early as possible.

    Every history line, config file and directory, file-history snapshot and the
    CLAUDE.md note is recorded in the snapshot's journal (flushed to disk) before it
    is written; the session transcript and its directory live under the project
    directory the snapshot copied. A summary is also written to snapshot_info.json
    on the way out, however the steps end.
    """
    artifacts: dict = {}
    journal = ImportJournal(snapshot_path)
    try:
        # 6. Write the session directory first: a populated target (possible with
        # --preserve-session-id) must abort before the transcript is written.
        info(f"\n\U0001f4be Writing session files...")
        dir_result = write_session_dir(prepared_session_dir, target_session_dir)
        if dir_result.files:
            info(f"   ✓ Session directory: {dir_result.files} files "
                 f"({dir_result.agents} sub-agent transcripts)")
        write_session_file(messages, target_session_path)
        info(f"   ✓ Wrote session to: {target_session_path}")

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
            info(f"\n\U0001f4e6 Importing auxiliary files...")

            # File history
            created_snapshots: list = []
            artifacts['created_file_history_files'] = created_snapshots
            fh_count = import_file_history(export_path, manifest, new_session_id,
                                           sources=file_history_sources, created=created_snapshots,
                                           journal=journal)
            summary['file_history_count'] = fh_count
            info(f"   ✓ File history: {fh_count} snapshots")

            # Prompt history
            appended: list = []
            artifacts['appended_history_lines'] = appended
            append_history(history_records, plan, project_text, appended=appended, journal=journal)
            summary['history_lines'] = len(appended)
            info(f"   ✓ Prompt history: {len(appended)} lines")

        # 8. Import config files
        if config_plan is not None:
            info(f"\n⚙️  Importing config files...")
            config_summary = new_config_summary()
            artifacts['created_config_files'] = config_summary['created']
            artifacts['created_config_dirs'] = config_summary['created_dirs']
            apply_config_import(config_plan, config_summary, journal=journal)
            summary['config'] = config_summary

            total_config = sum(config_summary[name] for name in _CONFIG_TYPE_NAMES)

            if total_config > 0:
                info(f"   ✓ Imported {total_config} config files:")
                for name in _CONFIG_TYPE_NAMES:
                    if config_summary[name]:
                        info(f"      - {config_summary[name]} {name}")

            if config_summary['conflicts']:
                warn(f"   \u26a0\ufe0f  Skipped {len(config_summary['conflicts'])} config files that already exist")

            reference_only = [name for name, key in (('settings.json', 'settings'), ('CLAUDE.md', 'claude_md'))
                              if (manifest.get('config_snapshot') or {}).get(key)]
            if reference_only:
                info(f"   \u2139\ufe0f  {' and '.join(reference_only)} from the export are not restored; "
                     f"they are in {export_path / 'config'} for reference")

            # 9. Add CLAUDE.md note (part of the config import, so --skip-config skips it too)
            info(f"\n\U0001f4dd Adding import context to CLAUDE.md...")
            if add_claude_md_note(project_path, manifest, journal=journal):
                artifacts['claude_md_note'] = claude_md_note(manifest)
                info(f"   ✓ Updated CLAUDE.md")
            else:
                info(f"   ✓ CLAUDE.md already carries this import's note")
    finally:
        record_import_artifacts(snapshot_path, **artifacts)
    return summary


def _require_canonical_uuid(session_id) -> None:
    """With --preserve-session-id the id becomes a path component of every file the
    import writes, so it must be exactly what Claude Code uses: a lowercase UUID."""
    try:
        canonical = str(uuid.UUID(session_id)) == session_id
    except (TypeError, ValueError, AttributeError):
        canonical = False
    if not canonical:
        raise InvalidExportError(
            f"Cannot preserve session id {session_id!r}: Claude Code session ids are lowercase UUIDs.\n"
            "Import without --preserve-session-id to get a new id."
        )


def _confirm(question: str) -> bool:
    """Ask a yes/no question; a closed or missing stdin counts as "no"."""
    if sys.stdin is None:
        return False
    try:
        return input(question).strip().lower() == 'y'
    except (EOFError, RuntimeError):
        return False


def _read_agent_transcripts(export_path: Path, manifest: dict) -> dict[str, list[dict]]:
    """Sub-agent transcripts in the export, keyed by agent id, for id-map building."""
    agents: dict[str, list[dict]] = {}
    for relative in manifest.get('session_data', {}).get('agent_sessions', []):
        path = resolve_export_path(export_path, relative)
        name = path.name
        if path.is_file() and name.startswith('agent-') and name.endswith('.jsonl'):
            agents[name[len('agent-'):-len('.jsonl')]] = read_session_jsonl(path)
    return agents
