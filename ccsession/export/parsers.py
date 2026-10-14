from __future__ import annotations

import json
from pathlib import Path

from ccsession.utils import parse_iso_timestamp


def parse_jsonl_file(file_path: str | Path) -> tuple[list[dict], dict]:
    """Parse a JSONL file and extract all messages and metadata."""
    messages = []
    metadata = {
        'session_id': None,
        'start_time': None,
        'end_time': None,
        'project_dir': None,
        'total_messages': 0,
        'user_messages': 0,
        'assistant_messages': 0,
        'tool_uses': 0,
        'models_used': set()
    }
    start = end = None

    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            try:
                data = json.loads(line.strip())
                if not isinstance(data, dict):
                    # Valid JSON but not a transcript record (e.g. a bare number)
                    continue
                messages.append(data)

                # Extract metadata
                if metadata['session_id'] is None and 'sessionId' in data:
                    metadata['session_id'] = data['sessionId']

                if 'cwd' in data and metadata['project_dir'] is None:
                    metadata['project_dir'] = data['cwd']

                timestamp = data.get('timestamp')
                if isinstance(timestamp, str) and timestamp:
                    try:
                        parsed = parse_iso_timestamp(timestamp)
                    except ValueError:
                        parsed = None
                    if parsed is not None:
                        if start is None or parsed < start:
                            start = parsed
                            metadata['start_time'] = timestamp
                        if end is None or parsed > end:
                            end = parsed
                            metadata['end_time'] = timestamp

                # Count message types (a record's ``message`` may be absent or malformed)
                message = data.get('message')
                if isinstance(message, dict) and 'role' in message:
                    role = message['role']
                    if role == 'user':
                        metadata['user_messages'] += 1
                    elif role == 'assistant':
                        metadata['assistant_messages'] += 1
                        model = message.get('model')
                        if isinstance(model, str) and model:
                            metadata['models_used'].add(model)

                # Count tool uses
                if isinstance(message, dict) and isinstance(message.get('content'), list):
                    for content in message['content']:
                        if isinstance(content, dict) and content.get('type') == 'tool_use':
                            metadata['tool_uses'] += 1

            except json.JSONDecodeError:
                continue

    metadata['total_messages'] = len(messages)
    metadata['models_used'] = sorted(metadata['models_used'])

    return messages, metadata


def extract_message_metadata(messages: list[dict]) -> dict:
    """Extract key metadata fields from messages in a single pass.

    Returns dict with 'version', 'git_branch', and 'slug' (each may be None).
    """
    result: dict = {'version': None, 'git_branch': None, 'slug': None}
    for msg in messages:
        if result['version'] is None and isinstance(msg.get('version'), str) and msg['version']:
            result['version'] = msg['version']
        if result['git_branch'] is None and isinstance(msg.get('gitBranch'), str) and msg['gitBranch']:
            result['git_branch'] = msg['gitBranch']
        if result['slug'] is None and isinstance(msg.get('slug'), str) and msg['slug']:
            result['slug'] = msg['slug']
        if all(value is not None for value in result.values()):
            break
    return result
