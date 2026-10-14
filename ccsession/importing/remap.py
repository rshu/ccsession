"""Rewrite identifiers and paths in Claude Code transcripts on import.

A transcript references its own records by uuid from many fields (``parentUuid``,
``leafUuid``, ``messageId``, ``foldedUuids``, compact metadata, queue origins, ...),
names its session in ``sessionId``/``session_id`` and stores absolute paths of the
machine that wrote it. When a session is imported under a new id or into a new
project every one of those has to move together, while model-visible message
content must stay byte-identical.

Record uuids are rewritten *by value*: any string outside ``message`` that equals a
known record uuid is replaced, whatever key it sits under. uuid4 values are globally
unique, so this cannot misfire, and it is the only way to keep up with the growing
set of fields Claude Code uses to point at records.

Sub-agent ids are never rewritten. Claude Code decides whether a background agent
finished by matching ``toolUseResult.agentId`` against ``<task-id>`` tags inside
message text, which import must not touch; renaming the agent would make every
finished background agent look orphaned on resume.
"""
from __future__ import annotations

import re
import uuid
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

# Keys that carry a session id. ``session_id`` may name a sub-session, so values are
# only rewritten when they equal the session being imported.
_SESSION_ID_KEYS = frozenset({'sessionId', 'session_id'})
# Keys whose string values are filesystem paths worth relocating. Free text such as
# stdout is deliberately not in this set.
_PATH_KEYS = frozenset({
    'cwd', 'filePath', 'persistedOutputPath', 'outputFile', 'transcriptDir',
    'scriptPath', 'trackingPath', 'backup', 'backgroundCwdHint', 'workingDirectory',
})
# Subtrees that are never rewritten: the API-visible message, including thinking
# signatures, tool_use ids and text.
_FROZEN_KEYS = frozenset({'message'})
# A path prefix match must end at a separator or at the end of the string
_END_OF_SEGMENT = r'(?=[\\/]|$)'


@dataclass(frozen=True)
class RemapPlan:
    """Everything needed to rewrite one session's transcripts consistently."""

    old_session_id: str
    new_session_id: str
    uuid_map: Mapping[str, str]
    path_rules: tuple


def most_common_cwd(records: Iterable[dict]) -> str | None:
    """The working directory most records were written under, or None."""
    counts = Counter(r['cwd'] for r in records
                     if isinstance(r, dict) and isinstance(r.get('cwd'), str) and r['cwd'])
    return counts.most_common(1)[0][0] if counts else None


def build_remap_plan(main_records: list[dict], agent_records_by_id: Mapping[str, list[dict]], *,
                     old_session_id: str, new_session_id: str,
                     old_project_path: str | None, new_project_path: str | Path,
                     new_session_dir: Path, new_file_history_dir: Path,
                     regenerate_ids: bool) -> RemapPlan:
    """Build the id and path mappings for one import.

    With ``regenerate_ids`` every record uuid across the main and sub-agent
    transcripts gets a fresh uuid4; without it (``--preserve-session-id``) ids are
    kept and only paths are relocated. Path rules accept ``/`` or ``\\`` as the
    separator so transcripts written on Windows relocate too.
    """
    uuid_map: dict[str, str] = {}
    if regenerate_ids:
        for record in _iter_records(main_records, agent_records_by_id):
            old = record.get('uuid')
            if isinstance(old, str) and old and old not in uuid_map:
                uuid_map[old] = str(uuid.uuid4())

    sid = re.escape(old_session_id)
    rules: list[tuple] = [
        (re.compile(r'^.*[\\/]projects[\\/][^\\/]+[\\/]' + sid + _END_OF_SEGMENT), str(new_session_dir)),
        (re.compile(r'^.*[\\/]file-history[\\/]' + sid + _END_OF_SEGMENT), str(new_file_history_dir)),
    ]
    if old_project_path:
        old_root = old_project_path.rstrip('/\\') or old_project_path
        rules.append((re.compile('^' + re.escape(old_root) + _END_OF_SEGMENT), str(new_project_path)))

    return RemapPlan(old_session_id=old_session_id, new_session_id=new_session_id,
                     uuid_map=uuid_map, path_rules=tuple(rules))


def remap_records(records: Iterable[dict], plan: RemapPlan) -> list[dict]:
    """Return rewritten copies of ``records``; the inputs are left untouched."""
    return [remap_record(record, plan) for record in records]


def remap_record(record: dict, plan: RemapPlan) -> dict:
    """Return a rewritten copy of one transcript record (or meta.json object)."""
    return _remap_value(record, plan, key=None)


def _iter_records(main_records: list[dict], agent_records_by_id: Mapping[str, list[dict]]) -> Iterable[dict]:
    yield from main_records
    for records in agent_records_by_id.values():
        yield from records


def _remap_value(value: Any, plan: RemapPlan, key: str | None) -> Any:
    if isinstance(value, dict):
        return {k: (v if k in _FROZEN_KEYS else _remap_value(v, plan, k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_remap_value(item, plan, key) for item in value]
    if isinstance(value, str) and key is not None:
        return _remap_string(value, plan, key)
    return value


def _remap_string(value: str, plan: RemapPlan, key: str) -> str:
    if key in _SESSION_ID_KEYS:
        return plan.new_session_id if value == plan.old_session_id else value
    if key in _PATH_KEYS:
        return _relocate_path(value, plan)
    return plan.uuid_map.get(value, value)


def _relocate_path(value: str, plan: RemapPlan) -> str:
    for pattern, replacement in plan.path_rules:
        relocated, count = pattern.subn(lambda _match: replacement, value, count=1)
        if count:
            return relocated
    return value
