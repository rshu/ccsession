from __future__ import annotations

import uuid

from ccsession.constants import AGENT_ID_LENGTH


def generate_new_session_id() -> str:
    """Generate a new UUID for the imported session."""
    return str(uuid.uuid4())


def generate_new_agent_id() -> str:
    """Generate a new 17-hex-character agent ID, the length Claude Code uses."""
    return uuid.uuid4().hex[:AGENT_ID_LENGTH]
