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
import sys
import tempfile
import uuid
from pathlib import Path

from ccsession.export.session_discovery import find_session_by_id, read_session_cwd
from ccsession.export.collectors import collect_session_dir_files
from ccsession.paths import get_claude_dir, get_file_history_dir, get_normalized_project_dir
from ccsession.utils import copy_file_writable, force_rmtree, json_line, write_json

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
        value = EMAIL_RE.sub(lambda m: m.group(0) if m.group(0).rsplit('@', 1)[1].lower() == 'anthropic.com'
                            else FIXTURE_EMAIL, value)
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
            fout.write(json_line(sanitize(json.loads(line), replacements)) + '\n')


def sanitize_file(source: Path, target: Path, replacements: list) -> None:
    """Sanitize UTF-8 text, retaining binary snapshots byte for byte."""
    target.parent.mkdir(parents=True, exist_ok=True)
    data = source.read_bytes()
    try:
        text = data.decode('utf-8')
    except UnicodeError:
        text = None
    if text is None or '\0' in text:
        copy_file_writable(source, target)
    else:
        target.write_text(sanitize(text, replacements), encoding='utf-8')


def write_fixture(session: dict, out: Path, project: str, replacements: list) -> None:
    """Build and validate a fixture before replacing the previous output."""
    sid = session['session_id']
    project_dir = out / 'projects' / get_normalized_project_dir(project)
    sanitize_jsonl(session['path'], project_dir / f'{sid}.jsonl', replacements)

    session_dir = session['path'].parent / sid
    for source in collect_session_dir_files(session['path'].parent, sid):
        target = project_dir / sid / source.relative_to(session_dir)
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.suffix == '.jsonl':
            sanitize_jsonl(source, target, replacements)
        elif source.suffix == '.json':
            data = json.loads(source.read_text(encoding='utf-8'))
            write_json(target, sanitize(data, replacements))
        else:
            sanitize_file(source, target, replacements)

    file_history = get_file_history_dir(sid)
    if file_history.is_dir():
        for source in sorted(p for p in file_history.rglob('*') if p.is_file()):
            sanitize_file(source, out / 'file-history' / sid / source.relative_to(file_history), replacements)

    history = get_claude_dir() / 'history.jsonl'
    lines = []
    if history.is_file():
        for line in history.read_text(encoding='utf-8').splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict) and record.get('sessionId') == sid:
                lines.append(json_line(sanitize(record, replacements)))
    if not lines:
        lines.append(json_line({'display': 'fixture prompt', 'pastedContents': {}, 'timestamp': 1791945800023,
                                'project': project, 'sessionId': sid}))
    (out / 'history.jsonl').write_text('\n'.join(lines) + '\n', encoding='utf-8')

    # Also inspect binary files: if recognizable personal text remains there,
    # refuse publication rather than silently labeling the bytes sanitized.
    tokens = [old for old, new in replacements if old and old not in new]
    leftovers = []
    for path in out.rglob('*'):
        if not path.is_file():
            continue
        text = path.read_text(encoding='utf-8', errors='replace')
        emails = [m.group(0) for m in EMAIL_RE.finditer(text)]
        if (any(token in text for token in tokens)
                or any(email != FIXTURE_EMAIL and email.rsplit('@', 1)[1].lower() != 'anthropic.com' for email in emails)):
            leftovers.append(str(path.relative_to(out)))
    if leftovers:
        raise ValueError('sanitization left personal data in: ' + ', '.join(leftovers))


def replace_fixture(staging: Path, out: Path) -> None:
    """Publish a validated fixture, restoring the previous one if the rename fails."""
    previous = out.with_name(f'.{out.name}.previous-{uuid.uuid4().hex}')
    existed = out.exists()
    if existed:
        out.rename(previous)
    try:
        staging.rename(out)
    except BaseException:
        if existed:
            previous.rename(out)
        raise
    if existed:
        force_rmtree(previous)


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

    out = args.output_dir.expanduser().absolute()
    source_roots = [get_claude_dir().resolve(), session['path'].parent.resolve(), get_file_history_dir(sid).resolve()]
    resolved_out = out.resolve()
    if any(resolved_out == source or resolved_out in source.parents or source in resolved_out.parents
           for source in source_roots):
        print('output directory overlaps the source Claude store; nothing was changed', file=sys.stderr)
        return 1
    if out.is_symlink() or (out.exists() and not out.is_dir()):
        print('output must be a directory, without a symlink', file=sys.stderr)
        return 1
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=f'.{out.name}.capture-', dir=out.parent) as temporary:
            staging = Path(temporary)
            write_fixture(session, staging, args.project, replacements)
            replace_fixture(staging, out)
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        print(f'fixture capture failed: {exc}', file=sys.stderr)
        return 1
    print(f'fixture written to {out}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
