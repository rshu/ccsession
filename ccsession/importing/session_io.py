from __future__ import annotations

import json
from pathlib import Path

from ccsession.utils import json_line  # noqa: F401  (re-exported)


def read_session_jsonl(session_path: Path) -> list:
    """Read the records of a JSONL file.

    Blank and unparseable lines, and lines whose JSON value is not an object, are
    skipped: they are not transcript records, and Claude Code skips them too.

    Args:
        session_path: Path to the JSONL file

    Returns:
        list: The record dictionaries, in file order
    """
    messages = []
    with open(session_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict):
                    messages.append(record)
    return messages


def write_session_file(messages: list, target_path: Path) -> None:
    """Write processed JSONL to target location.

    Args:
        messages: List of message dictionaries
        target_path: Path to write the session file

    Raises:
        FileExistsError: If target file already exists
    """
    if target_path.exists():
        raise FileExistsError(
            f"Session file already exists: {target_path}\n"
            "Import aborted to prevent data loss."
        )

    # Create parent directory if needed
    target_path.parent.mkdir(parents=True, exist_ok=True)

    # Write JSONL
    with open(target_path, 'w', encoding='utf-8', newline='') as f:
        for msg in messages:
            f.write(json_line(msg) + '\n')
