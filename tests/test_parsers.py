"""parse_jsonl_file tolerates lines that are valid JSON but not transcript records."""
from __future__ import annotations

import json

from ccsession.export.parsers import parse_jsonl_file, extract_message_metadata


def test_non_object_json_lines_are_skipped(tmp_path):
    path = tmp_path / "s.jsonl"
    record = {"type": "user", "uuid": "u1", "sessionId": "s", "timestamp": "2026-10-14T00:00:00Z",
              "message": {"role": "user", "content": "hi"}}
    path.write_text("42\n\"a string\"\n[1, 2]\nnull\n" + json.dumps(record) + "\n", encoding="utf-8")

    messages, metadata = parse_jsonl_file(path)

    assert messages == [record]
    assert metadata["total_messages"] == 1 and metadata["user_messages"] == 1


def test_message_content_that_is_not_a_list_does_not_break_tool_counting(tmp_path):
    path = tmp_path / "s.jsonl"
    record = {"type": "user", "uuid": "u1", "message": {"role": "user", "content": "plain string"}}
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")

    messages, metadata = parse_jsonl_file(path)

    assert len(messages) == 1 and metadata["tool_uses"] == 0


def test_a_message_field_that_is_not_an_object_does_not_crash_the_parse(tmp_path):
    path = tmp_path / "s.jsonl"
    rows = [{"type": "user", "uuid": "u1", "message": None},
            {"type": "user", "uuid": "u2", "message": "hello"},
            {"type": "user", "uuid": "u3", "message": {"role": "user", "content": "ok"}}]
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

    messages, metadata = parse_jsonl_file(path)

    assert len(messages) == 3 and metadata["user_messages"] == 1


def test_time_bounds_compare_instants_instead_of_raw_iso_strings(tmp_path):
    path = tmp_path / 's.jsonl'
    rows = [{'timestamp': '2026-10-14T01:00:00+01:00'},
            {'timestamp': '2026-10-14T00:30:00Z'}, {'timestamp': 'not-a-date'}]
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')
    messages, metadata = parse_jsonl_file(path)
    assert messages == rows
    assert metadata['start_time'] == rows[0]['timestamp']
    assert metadata['end_time'] == rows[1]['timestamp']


def test_time_bounds_handle_optional_fractional_seconds(tmp_path):
    path = tmp_path / 's.jsonl'
    rows = [{'timestamp': '2026-10-14T00:00:00Z'}, {'timestamp': '2026-10-14T00:00:00.100Z'}]
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')
    _, metadata = parse_jsonl_file(path)
    assert metadata['start_time'] == rows[0]['timestamp']
    assert metadata['end_time'] == rows[1]['timestamp']


def test_null_metadata_does_not_hide_later_populated_fields():
    messages = [{'version': None, 'gitBranch': None, 'slug': None},
                {'version': '2.1.287', 'gitBranch': 'main', 'slug': 'demo'}]
    assert extract_message_metadata(messages) == {'version': '2.1.287', 'git_branch': 'main', 'slug': 'demo'}
