#!/usr/bin/env python3
"""Copy one real Claude Code session into a sanitized fixture claude-dir.

Usage: python3 scripts/capture_fixture.py <session-id> <output-dir> [--project /tmp/e2e/proj]

The output directory becomes a miniature config dir (projects/, file-history/,
history.jsonl) that tests can point CLAUDE_CONFIG_DIR at. Personal data is
replaced and oversized attachment payloads (system-prompt snapshots, skill
listings) are reduced to a marker so the fixture stays small and shareable.
"""
from __future__ import annotations

import argparse
import getpass
import json
import re
import shutil
import sys
from pathlib import Path

from ccsession.export.session_discovery import find_session_by_id, read_session_cwd
from ccsession.paths import get_claude_dir, get_file_history_dir, get_normalized_project_dir

FIXTURE_PROJECT = '/tmp/e2e/proj'
FIXTURE_ORG = '00000000-0000-4000-8000-000000000000'
FIXTURE_EMAIL = 'user@example.com'
EMAIL_RE = re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+')
# Attachment payloads that are environment-specific bulk (system-prompt snapshots,
# skill/agent/MCP listings), not transcript structure. They are replaced by a
# marker that records their size so the record itself stays in place.
BULKY_ATTACHMENTS = {'prompt_snapshot', 'skill_listing', 'agent_listing_delta', 'mcp_instructions_delta',
                     'deferred_tools_record'}


def sanitize(value, replacements: list):
    """Recursively replace personal strings and collapse bulky attachment payloads."""
    if isinstance(value, dict):
        if value.get('type') in BULKY_ATTACHMENTS:
            return {'type': value['type'], 'redacted_chars': len(json.dumps(value))}
        out = {}
        for key, item in value.items():
            if key == 'organizationUuid':
                out[key] = FIXTURE_ORG
            else:
                out[key] = sanitize(item, replacements)
        return out
    if isinstance(value, list):
        return [sanitize(item, replacements) for item in value]
    if isinstance(value, str):
        value = EMAIL_RE.sub(lambda m: m.group(0) if 'anthropic.com' in m.group(0) else FIXTURE_EMAIL, value)
        for old, new in replacements:
            value = value.replace(old, new)
        return value
    return value


def sanitize_jsonl(source: Path, target: Path, replacements: list) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(source, 'r', encoding='utf-8') as fin, open(target, 'w', encoding='utf-8') as fout:
        for line in fin:
            if not line.strip():
                continue
            fout.write(json.dumps(sanitize(json.loads(line), replacements), ensure_ascii=False) + '\n')


def main(argv: list) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('session_id')
    parser.add_argument('output_dir', type=Path)
    parser.add_argument('--project', default=FIXTURE_PROJECT, help='project path to write into the fixture')
    args = parser.parse_args(argv)

    session = find_session_by_id(args.session_id)
    if not session:
        print(f'session not found: {args.session_id}', file=sys.stderr)
        return 1
    sid = session['session_id']
    old_project = session.get('project_path') or read_session_cwd(session['path'])
    if not old_project:
        print('transcript has no cwd; cannot derive project path', file=sys.stderr)
        return 1
    replacements = [(old_project, args.project), (str(Path.home()), '/home/user'), (getpass.getuser(), 'user')]

    out = args.output_dir
    if out.exists():
        shutil.rmtree(out)
    project_dir = out / 'projects' / get_normalized_project_dir(args.project)
    sanitize_jsonl(session['path'], project_dir / f'{sid}.jsonl', replacements)

    session_dir = session['path'].parent / sid
    if session_dir.is_dir():
        for source in sorted(p for p in session_dir.rglob('*') if p.is_file()):
            target = project_dir / sid / source.relative_to(session_dir)
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.suffix == '.jsonl':
                sanitize_jsonl(source, target, replacements)
            elif source.suffix == '.json':
                data = json.loads(source.read_text(encoding='utf-8'))
                target.write_text(json.dumps(sanitize(data, replacements)), encoding='utf-8')
            else:
                shutil.copy2(source, target)

    file_history = get_file_history_dir(sid)
    if file_history.is_dir():
        shutil.copytree(file_history, out / 'file-history' / sid)

    history = get_claude_dir() / 'history.jsonl'
    lines = []
    if history.is_file():
        for line in history.read_text(encoding='utf-8').splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get('sessionId') == sid:
                lines.append(json.dumps(sanitize(record, replacements), ensure_ascii=False))
    if not lines:
        lines.append(json.dumps({'display': 'fixture prompt', 'pastedContents': {}, 'timestamp': 1791945800023,
                                 'project': args.project, 'sessionId': sid}))
    (out / 'history.jsonl').write_text('\n'.join(lines) + '\n', encoding='utf-8')

    tokens = (getpass.getuser(), str(Path.home()), old_project)
    leftovers = [p for p in out.rglob('*') if p.is_file()
                 and any(token in p.read_text(encoding='utf-8', errors='replace') for token in tokens)]
    if leftovers:
        print('sanitization left personal data in: ' + ', '.join(str(p) for p in leftovers), file=sys.stderr)
        return 1
    print(f'fixture written to {out}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
