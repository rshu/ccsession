"""Markdown and XML rendering of transcript messages."""
from __future__ import annotations

import xml.etree.ElementTree as ET

from ccsession.constants import TOOL_RESULT_MAX_LENGTH
from ccsession.export.formatters import format_message_markdown, format_message_xml, prettify_xml


def _message(content, role="user", **top):
    base = {"uuid": "u1", "parentUuid": None, "timestamp": "2026-10-14T00:00:00Z", "type": role,
            "message": {"role": role, "content": content}}
    base.update(top)
    return base


def _xml_for(*messages):
    root = ET.Element("claude-session")
    for msg in messages:
        format_message_xml(msg, root)
    return prettify_xml(root)


def _tool_result(content):
    return _message([{"type": "tool_result", "tool_use_id": "toolu_1", "content": content}])


# ---------------------------------------------------------------------------
# XML must always be well-formed
# ---------------------------------------------------------------------------

def test_string_content_with_control_characters_yields_parseable_xml():
    """Slash-command output is stored as string content and often carries ANSI escapes."""
    xml = _xml_for(_message("\x1b[31mred\x1b[0m text"))
    parsed = ET.fromstring(xml)
    assert parsed.find(".//content").text == "[31mred[0m text"
    assert xml.startswith("<?xml")


def test_attributes_and_metadata_with_control_characters_are_cleaned():
    msg = _message([{"type": "text", "text": "ok"}], role="assistant", requestId="req\x01",
                   toolUseResult={"codeText": "OK\x1b", "url": "https://x\x02"})
    msg["message"]["model"] = "claude\x1b"
    msg["message"]["usage"] = {"service_tier": "std\x03"}
    msg["uuid"] = "u\x041"

    parsed = ET.fromstring(_xml_for(msg))

    message = parsed.find("message")
    assert message.get("uuid") == "u1"
    assert message.find("request-id").text == "req"
    assert message.find("model").text == "claude"
    assert message.find("tool-execution-metadata/response-text").text == "OK"
    assert message.find("tool-execution-metadata/url").text == "https://x"
    assert message.find("usage/service-tier").text == "std"


def test_tool_use_and_thinking_attributes_are_cleaned():
    msg = _message([
        {"type": "thinking", "thinking": "hmm", "signature": "sig\x1b"},
        {"type": "tool_use", "id": "toolu\x1b_1", "name": "Bash\x00", "input": {"command": "ls"}},
        {"type": "tool_result", "tool_use_id": "toolu\x1b_1", "content": "done"},
    ], role="assistant")

    parsed = ET.fromstring(_xml_for(msg))

    assert parsed.find(".//thinking").get("signature") == "sig"
    assert parsed.find(".//tool-use").get("id") == "toolu_1"
    assert parsed.find(".//tool-use").get("name") == "Bash"
    assert parsed.find(".//tool-result").get("tool-use-id") == "toolu_1"


# ---------------------------------------------------------------------------
# List-form tool results are rendered, not repr()'d
# ---------------------------------------------------------------------------

def test_list_form_tool_result_is_rendered_block_by_block():
    md = format_message_markdown(_tool_result([
        {"type": "text", "text": "first line"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "A" * 40}},
    ]))

    assert "first line" in md
    assert "[image: image/png, 40 base64 chars]" in md
    assert "{'type'" not in md and "\\n" not in md


def test_list_form_tool_result_is_truncated_like_a_string_one():
    md = format_message_markdown(_tool_result([{"type": "text", "text": "x" * (TOOL_RESULT_MAX_LENGTH + 1000)}]))

    assert f"(truncated, 1000 chars omitted)" in md
    assert md.count("x") <= TOOL_RESULT_MAX_LENGTH + 50


def test_unknown_block_in_a_tool_result_is_rendered_as_json():
    md = format_message_markdown(_tool_result([{"type": "document", "title": "spec"}]))

    assert '{"type": "document", "title": "spec"}' in md


def test_xml_tool_result_uses_the_same_rendering():
    xml = _xml_for(_tool_result([
        {"type": "text", "text": "first"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "B" * 8}},
    ]))

    text = ET.fromstring(xml).find(".//tool-result").text
    assert "first" in text and "[image: image/jpeg, 8 base64 chars]" in text and "{'type'" not in text


def test_xml_illegal_unicode_is_removed():
    """XML 1.0 also forbids U+FFFE/U+FFFF, and a lone surrogate cannot even be encoded."""
    xml = _xml_for(_message("a￾b￿c\ud800d", requestId="r\udfffx"))
    parsed = ET.fromstring(xml)
    assert parsed.find(".//content").text == "abcd"
    assert parsed.find(".//request-id").text == "rx"
