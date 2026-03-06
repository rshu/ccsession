from __future__ import annotations

import uuid

from ccsession.constants import AGENT_ID_LENGTH


def generate_new_session_id() -> str:
    """Generate a new UUID for the imported session."""
    return str(uuid.uuid4())


def generate_new_agent_id() -> str:
    """Generate a new short agent ID (7 hex characters)."""
    return uuid.uuid4().hex[:AGENT_ID_LENGTH]


def regenerate_message_uuids(messages: list, new_session_id: str, new_cwd: str) -> list:
    """Regenerate all UUIDs while maintaining parent references.

    Args:
        messages: List of message dictionaries from JSONL
        new_session_id: New session UUID
        new_cwd: New working directory path

    Returns:
        list: Messages with updated UUIDs
    """
    # Create mapping from old UUIDs to new UUIDs
    uuid_mapping = {}
    new_agent_id = generate_new_agent_id()

    # First pass: generate new UUIDs for all messages
    for msg in messages:
        if 'uuid' in msg:
            old_uuid = msg['uuid']
            if old_uuid not in uuid_mapping:
                uuid_mapping[old_uuid] = str(uuid.uuid4())

    # Second pass: update all references
    updated_messages = []
    for msg in messages:
        updated_msg = msg.copy()

        # Update sessionId
        if 'sessionId' in updated_msg:
            updated_msg['sessionId'] = new_session_id

        # Update uuid
        if 'uuid' in updated_msg:
            updated_msg['uuid'] = uuid_mapping.get(updated_msg['uuid'], updated_msg['uuid'])

        # Update parentUuid reference
        if 'parentUuid' in updated_msg and updated_msg['parentUuid']:
            updated_msg['parentUuid'] = uuid_mapping.get(
                updated_msg['parentUuid'],
                updated_msg['parentUuid']
            )

        # Update agentId
        if 'agentId' in updated_msg:
            updated_msg['agentId'] = new_agent_id

        # Update cwd
        if 'cwd' in updated_msg:
            updated_msg['cwd'] = new_cwd

        # Keep slug unchanged (per user preference)

        # DO NOT modify:
        # - message.id (Anthropic message ID)
        # - requestId (Anthropic request ID)
        # - signature in thinking blocks
        # - tool_use.id (tool invocation ID)
        # - timestamp (historical record)
        # - thinking block text content

        updated_messages.append(updated_msg)

    return updated_messages
