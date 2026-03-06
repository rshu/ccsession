from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def utc_now_iso() -> str:
    """Return current UTC time as ISO string with 'Z' suffix."""
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def parse_iso_timestamp(ts: str) -> datetime:
    """Parse an ISO timestamp string (with 'Z' or '+00:00') into a timezone-aware datetime."""
    return datetime.fromisoformat(ts.replace('Z', '+00:00'))


def read_json(path: Path) -> dict:
    """Read a JSON file with UTF-8 encoding."""
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def write_json(path: Path, data, indent: int = 2) -> None:
    """Write data as JSON with UTF-8 encoding, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=indent)
