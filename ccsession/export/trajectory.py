from __future__ import annotations

import json
import sys
from pathlib import Path

from ccsession import CCSESSION_VERSION
from ccsession.constants import TRAJECTORY_FORMAT_VERSION
from ccsession.export.parsers import parse_jsonl_file
from ccsession.utils import parse_iso_timestamp


def _transform_content_block(block: dict) -> dict | None:
    """Transform a single content block from raw JSONL to trajectory format."""
    if not isinstance(block, dict):
        return None

    block_type = block.get('type')

    if block_type == 'text':
        return {'type': 'text', 'text': block.get('text', '')}

    if block_type == 'thinking':
        result = {'type': 'thinking', 'text': block.get('thinking', '')}
        if 'signature' in block:
            result['signature'] = block['signature']
        return result

    if block_type == 'tool_use':
        result = {
            'type': 'tool_call',
            'id': block.get('id', ''),
            'name': block.get('name', ''),
            'input': block.get('input', {}),
        }
        if 'caller' in block:
            result['caller'] = block['caller']
        return result

    if block_type == 'tool_result':
        output = block.get('content', '')
        if not isinstance(output, str):
            output = json.dumps(output) if output else ''
        return {
            'type': 'tool_result',
            'tool_call_id': block.get('tool_use_id', ''),
            'output': output,
            'is_error': block.get('is_error', False),
        }

    return None


def _transform_event(msg: dict, index: int) -> dict:
    """Transform a non-message JSONL event (progress, system, file-history-snapshot, etc.)."""
    event: dict = {
        'index': index,
        'role': 'event',
        'event_type': msg.get('type', 'unknown'),
        'timestamp': msg.get('timestamp'),
    }

    # Common top-level fields
    if 'uuid' in msg:
        event['uuid'] = msg['uuid']
    if 'parentUuid' in msg:
        event['parent_uuid'] = msg['parentUuid']
    if 'cwd' in msg:
        event['cwd'] = msg['cwd']

    # Include event-specific data
    if 'data' in msg:
        event['data'] = msg['data']
    if 'toolUseID' in msg:
        event['tool_use_id'] = msg['toolUseID']
    if 'parentToolUseID' in msg:
        event['parent_tool_use_id'] = msg['parentToolUseID']
    if 'messageId' in msg:
        event['message_id'] = msg['messageId']
    if 'snapshot' in msg:
        event['snapshot'] = msg['snapshot']

    return event


def _transform_turn(msg: dict, index: int) -> dict:
    """Transform one JSONL line into a trajectory entry.

    Handles both role-bearing messages and non-message events.
    """
    if 'message' not in msg:
        return _transform_event(msg, index)

    message = msg['message']
    role = message.get('role')
    if not role:
        return _transform_event(msg, index)

    turn: dict = {
        'index': index,
        'role': role,
        'timestamp': msg.get('timestamp'),
    }

    # Top-level JSONL fields (per-turn context)
    if 'uuid' in msg:
        turn['uuid'] = msg['uuid']
    if 'parentUuid' in msg:
        turn['parent_uuid'] = msg['parentUuid']
    if 'cwd' in msg:
        turn['cwd'] = msg['cwd']
    if 'isSidechain' in msg:
        turn['is_sidechain'] = msg['isSidechain']
    if 'userType' in msg:
        turn['user_type'] = msg['userType']
    if 'requestId' in msg:
        turn['request_id'] = msg['requestId']
    if 'durationMs' in msg:
        turn['duration_ms'] = msg['durationMs']
    if 'permissionMode' in msg:
        turn['permission_mode'] = msg['permissionMode']

    # Message-level fields
    if 'id' in message:
        turn['message_id'] = message['id']
    if role == 'assistant':
        if 'model' in message:
            turn['model'] = message['model']
        if 'stop_reason' in message:
            turn['stop_reason'] = message['stop_reason']
        if 'stop_sequence' in message:
            turn['stop_sequence'] = message['stop_sequence']
        if 'usage' in message:
            turn['usage'] = message['usage']

    # Transform content blocks
    raw_content = message.get('content', [])
    if isinstance(raw_content, str):
        turn['content'] = [{'type': 'text', 'text': raw_content}]
    elif isinstance(raw_content, list):
        content = []
        for block in raw_content:
            transformed = _transform_content_block(block)
            if transformed is not None:
                content.append(transformed)
        turn['content'] = content
    else:
        turn['content'] = []

    # Tool execution metadata (on user turns containing tool results)
    if 'toolUseResult' in msg and isinstance(msg['toolUseResult'], dict):
        turn['tool_execution'] = msg['toolUseResult']

    return turn


def _compute_statistics(turns: list[dict]) -> dict:
    """Compute aggregate statistics from trajectory turns."""
    user_turns = 0
    assistant_turns = 0
    events = 0
    tool_calls = 0
    tool_calls_by_name: dict[str, int] = {}
    tokens_input = 0
    tokens_output = 0
    tokens_cache_read = 0
    tokens_cache_creation = 0

    for turn in turns:
        role = turn['role']
        if role == 'user':
            user_turns += 1
        elif role == 'assistant':
            assistant_turns += 1
            usage = turn.get('usage', {})
            tokens_input += usage.get('input_tokens', 0)
            tokens_output += usage.get('output_tokens', 0)
            tokens_cache_read += usage.get('cache_read_input_tokens', 0)
            tokens_cache_creation += usage.get('cache_creation_input_tokens', 0)
        elif role == 'event':
            events += 1

        for block in turn.get('content', []):
            if block.get('type') == 'tool_call':
                tool_calls += 1
                name = block.get('name', 'unknown')
                tool_calls_by_name[name] = tool_calls_by_name.get(name, 0) + 1

    return {
        'turns': len(turns),
        'user_turns': user_turns,
        'assistant_turns': assistant_turns,
        'events': events,
        'tool_calls': tool_calls,
        'tool_calls_by_name': dict(sorted(tool_calls_by_name.items(), key=lambda x: -x[1])),
        'tokens': {
            'input': tokens_input,
            'output': tokens_output,
            'cache_read': tokens_cache_read,
            'cache_creation': tokens_cache_creation,
        },
    }


def _find_spawning_tool_call_id(main_messages: list[dict], agent_id: str) -> str | None:
    """Find the tool_call ID of the Agent tool_use that spawned a sub-agent."""
    for msg in main_messages:
        if 'message' not in msg:
            continue
        message = msg['message']
        if message.get('role') != 'assistant':
            continue
        for block in message.get('content', []):
            if (isinstance(block, dict) and block.get('type') == 'tool_use'
                    and block.get('name') == 'Agent'):
                return block.get('id')
    return None


def _parse_agent_trajectory(agent_path: Path) -> dict:
    """Parse an agent session file into a sub-agent trajectory entry."""
    messages, metadata = parse_jsonl_file(agent_path)

    turns = [_transform_turn(msg, i) for i, msg in enumerate(messages)]

    stats = _compute_statistics(turns)

    result: dict = {
        'started_at': metadata.get('start_time'),
        'ended_at': metadata.get('end_time'),
        'statistics': stats,
        'trajectory': turns,
    }

    # Compute duration
    if metadata.get('start_time') and metadata.get('end_time'):
        try:
            start = parse_iso_timestamp(metadata['start_time'])
            end = parse_iso_timestamp(metadata['end_time'])
            result['duration_seconds'] = int((end - start).total_seconds())
        except (ValueError, TypeError):
            pass

    return result


def format_trajectory(messages: list[dict], metadata: dict, msg_meta: dict,
                      agent_sessions: dict[str, Path] | None = None) -> dict:
    """Transform parsed JSONL messages into the trajectory JSON structure.

    Args:
        messages: Parsed JSONL messages from parse_jsonl_file()
        metadata: Session metadata from parse_jsonl_file()
        msg_meta: Message metadata from extract_message_metadata()
        agent_sessions: Agent ID -> file path mapping from collect_agent_sessions()

    Returns:
        Complete trajectory dict ready for JSON serialization.
    """
    # Build main trajectory entries (messages + events)
    turns = [_transform_turn(msg, i) for i, msg in enumerate(messages)]

    # Compute statistics
    stats = _compute_statistics(turns)

    # Session metadata
    session: dict = {
        'id': metadata.get('session_id', ''),
        'slug': msg_meta.get('slug'),
        'started_at': metadata.get('start_time'),
        'ended_at': metadata.get('end_time'),
        'duration_seconds': None,
        'working_directory': metadata.get('project_dir', ''),
        'git_branch': msg_meta.get('git_branch'),
        'claude_code_version': msg_meta.get('version'),
        'models_used': metadata.get('models_used', []),
    }

    session['platform'] = sys.platform

    # Compute duration
    if metadata.get('start_time') and metadata.get('end_time'):
        try:
            start = parse_iso_timestamp(metadata['start_time'])
            end = parse_iso_timestamp(metadata['end_time'])
            session['duration_seconds'] = int((end - start).total_seconds())
        except (ValueError, TypeError):
            pass

    # Process sub-agent sessions
    sub_agents = []
    if agent_sessions:
        for agent_id, agent_path in agent_sessions.items():
            agent_data = _parse_agent_trajectory(agent_path)
            agent_data['agent_id'] = agent_id
            agent_data['spawned_by_tool_call_id'] = _find_spawning_tool_call_id(
                messages, agent_id,
            )
            sub_agents.append(agent_data)

    stats['sub_agent_count'] = len(sub_agents)

    return {
        'format': 'ccsession-trajectory',
        'format_version': TRAJECTORY_FORMAT_VERSION,
        'generator': {
            'name': 'ccsession',
            'version': CCSESSION_VERSION,
        },
        'session': session,
        'statistics': stats,
        'trajectory': turns,
        'sub_agents': sub_agents,
    }
