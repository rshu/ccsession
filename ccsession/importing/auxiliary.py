from __future__ import annotations

import os
from pathlib import Path

from ccsession.importing.config import place_file
from ccsession.importing.validation import resolve_export_path
from ccsession.paths import get_file_history_dir


def resolve_file_history_sources(export_path: Path, manifest: dict) -> list:
    """The file-history snapshots named by the manifest, confined to the export.

    Entries whose file is missing are dropped.

    Raises:
        InvalidExportError: if a manifest path escapes the export directory.
    """
    relatives = manifest.get('session_data', {}).get('file_history', []) or []
    sources = [resolve_export_path(export_path, relative) for relative in relatives]
    return [source for source in sources if source.is_file()]


def import_file_history(export_path: Path, manifest: dict, new_session_id: str,
                        sources: list | None = None, created: list | None = None, *, journal=None) -> int:
    """Copy file-history snapshots to ``<claude-dir>/file-history/<sessionId>/``.

    ``sources`` may be passed from :func:`resolve_file_history_sources` when the
    caller validated the manifest earlier; otherwise they are resolved here, before
    anything is written. A snapshot that already exists is never overwritten (with
    ``--preserve-session-id`` the session's directory may already hold the local
    copies). Each file is journaled before it is written (see
    :func:`ccsession.importing.config.place_file`) and added to ``created`` once it
    is in place.

    Returns:
        int: Number of files imported
    """
    if sources is None:
        sources = resolve_file_history_sources(export_path, manifest)
    if created is None:
        created = []
    if not sources:
        return 0

    target_dir = get_file_history_dir(new_session_id)
    validate_file_history_target(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    for source_path in sources:
        target = target_dir / source_path.name
        if os.path.lexists(target):
            continue
        place_file(source_path, target, journal=journal, kind='file_history_file')
        created.append(str(target))
        copied += 1
    return copied


def validate_file_history_target(target_dir: Path) -> None:
    """Do not add snapshots through symlinks that a restore cannot safely undo."""
    for directory in (target_dir.parent, target_dir):
        if directory.is_symlink():
            raise FileExistsError(f"File-history directory is a symlink: {directory}\n"
                                  "Import aborted to prevent writing outside the file-history directory.")
