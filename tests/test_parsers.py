"""parse_jsonl_file tolerates lines that are valid JSON but not transcript records."""
from __future__ import annotations

import json

from ccsession.export.parsers import parse_jsonl_file


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
