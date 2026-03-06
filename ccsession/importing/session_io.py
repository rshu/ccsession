from __future__ import annotations

import json
from pathlib import Path


def read_session_jsonl(session_path: Path) -> list:
    """Read messages from a session JSONL file.

    Args:
        session_path: Path to the JSONL file

    Returns:
        list: List of message dictionaries
    """
    messages = []
    with open(session_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                try:
                    messages.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
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
    with open(target_path, 'w', encoding='utf-8') as f:
        for msg in messages:
            f.write(json.dumps(msg, ensure_ascii=False) + '\n')
