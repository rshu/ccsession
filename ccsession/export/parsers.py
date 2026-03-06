from __future__ import annotations

import json
from pathlib import Path


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

    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            try:
                data = json.loads(line.strip())
                messages.append(data)

                # Extract metadata
                if metadata['session_id'] is None and 'sessionId' in data:
                    metadata['session_id'] = data['sessionId']

                if 'cwd' in data and metadata['project_dir'] is None:
                    metadata['project_dir'] = data['cwd']

                if 'timestamp' in data:
                    timestamp = data['timestamp']
                    if metadata['start_time'] is None or timestamp < metadata['start_time']:
                        metadata['start_time'] = timestamp
                    if metadata['end_time'] is None or timestamp > metadata['end_time']:
                        metadata['end_time'] = timestamp

                # Count message types
                if 'message' in data and 'role' in data['message']:
                    role = data['message']['role']
                    if role == 'user':
                        metadata['user_messages'] += 1
                    elif role == 'assistant':
                        metadata['assistant_messages'] += 1
                        if 'model' in data['message']:
                            metadata['models_used'].add(data['message']['model'])

                # Count tool uses
                if 'message' in data and 'content' in data['message']:
                    for content in data['message']['content']:
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
    found = 0
    for msg in messages:
        if result['version'] is None and 'version' in msg:
            result['version'] = msg['version']
            found += 1
        if result['git_branch'] is None and 'gitBranch' in msg:
            result['git_branch'] = msg['gitBranch']
            found += 1
        if result['slug'] is None and 'slug' in msg:
            result['slug'] = msg['slug']
            found += 1
        if found == 3:
            break
    return result
