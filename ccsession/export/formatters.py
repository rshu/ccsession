from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from xml.dom import minidom
from xml.parsers.expat import ExpatError

from ccsession.constants import TOOL_RESULT_MAX_LENGTH
from ccsession.output import error
from ccsession.utils import parse_iso_timestamp

# C0/C1 controls (except tab, LF, CR), lone surrogates and the two non-characters XML 1.0 forbids
_XML_INVALID_RE = re.compile(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F\uD800-\uDFFF\uFFFE\uFFFF]')


def clean_text_for_xml(text: str | None) -> str | None:
    """Remove or replace characters that cause XML parsing issues."""
    if not text:
        return text
    # Remove control characters except newline, tab, and carriage return
    return _XML_INVALID_RE.sub('', str(text))


def _xml_text(value) -> str:
    """Any value as XML-safe text; ``None`` becomes an empty string."""
    if value is None:
        return ''
    return _XML_INVALID_RE.sub('', str(value))


def render_tool_result_content(content) -> str:
    """Human-readable text for a ``tool_result`` block's ``content``.

    Claude Code stores either a string or a list of content blocks (text, image,
    document, ...). Text blocks are shown verbatim, images as a short placeholder
    (a screenshot can be hundreds of kilobytes of base64) and anything else as JSON.
    """
    if content is None:
        return ''
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return json.dumps(content, ensure_ascii=False)

    parts = []
    for block in content:
        if not isinstance(block, dict):
            parts.append(str(block))
            continue
        block_type = block.get('type')
        if block_type == 'text':
            parts.append(str(block.get('text', '')))
        elif block_type == 'image':
            source = block.get('source')
            if isinstance(source, dict) and source.get('type') == 'base64':
                parts.append(f"[image: {source.get('media_type', 'unknown')}, "
                             f"{len(str(source.get('data', '')))} base64 chars]")
            elif isinstance(source, dict) and source.get('url'):
                parts.append(f"[image: {source['url']}]")
            else:
                parts.append('[image]')
        else:
            parts.append(json.dumps(block, ensure_ascii=False))
    return '\n'.join(parts)


def _truncate_tool_result(text: str) -> list[str]:
    if len(text) <= TOOL_RESULT_MAX_LENGTH:
        return [text]
    return [text[:TOOL_RESULT_MAX_LENGTH],
            f"\n... (truncated, {len(text) - TOOL_RESULT_MAX_LENGTH} chars omitted)"]


def format_message_markdown(message_data: dict) -> str:
    """Format a single message as markdown."""
    output = []

    msg = message_data.get('message')
    if not isinstance(msg, dict):
        return ""

    timestamp = message_data.get('timestamp', '')

    # Add timestamp
    if timestamp:
        try:
            output.append(f"**[{parse_iso_timestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')}]**")
        except (ValueError, TypeError, AttributeError):
            output.append(f"**[{timestamp}]**")

    # Add role header
    role = msg.get('role', 'unknown')
    if role == 'user':
        output.append("\n### \U0001f464 User\n")
    elif role == 'assistant':
        model = msg.get('model', '')
        output.append(f"\n### \U0001f916 Assistant ({model})\n")

    # Process content
    if 'content' in msg:
        if isinstance(msg['content'], str):
            output.append(msg['content'])
        elif isinstance(msg['content'], list):
            for content in msg['content']:
                if isinstance(content, dict):
                    content_type = content.get('type')

                    if content_type == 'text':
                        output.append(content.get('text', ''))

                    elif content_type == 'thinking':
                        output.append("\n<details>")
                        output.append("<summary>\U0001f4ad Internal Reasoning (click to expand)</summary>\n")
                        output.append("```")
                        output.append(content.get('thinking', ''))
                        output.append("```")
                        output.append("</details>\n")

                    elif content_type == 'tool_use':
                        tool_name = content.get('name', 'unknown')
                        tool_id = content.get('id', '')
                        output.append(f"\n\U0001f527 **Tool Use: {tool_name}** (ID: {tool_id})")
                        output.append("```json")
                        output.append(json.dumps(content.get('input', {}), indent=2))
                        output.append("```\n")

                    elif content_type == 'tool_result':
                        output.append("\n\U0001f4ca **Tool Result:**")
                        output.append("```")
                        output.extend(_truncate_tool_result(render_tool_result_content(content.get('content', ''))))
                        output.append("```\n")

    return '\n'.join(output)


def format_message_xml(message_data: dict, parent_element: ET.Element) -> None:
    """Format a single message as XML element.

    Every string that lands in the document passes through ``_xml_text`` so a stray
    control character (ANSI escapes in slash-command output, for instance) can never
    make the file ill-formed.
    """
    msg_elem = ET.SubElement(parent_element, 'message')

    # Add attributes
    msg_elem.set('uuid', _xml_text(message_data.get('uuid', '')))
    if message_data.get('parentUuid'):
        msg_elem.set('parent-uuid', _xml_text(message_data['parentUuid']))
    msg_elem.set('timestamp', _xml_text(message_data.get('timestamp', '')))

    # Add metadata
    if 'type' in message_data:
        ET.SubElement(msg_elem, 'event-type').text = _xml_text(message_data['type'])
    if 'cwd' in message_data:
        ET.SubElement(msg_elem, 'working-directory').text = _xml_text(message_data['cwd'])
    if 'requestId' in message_data:
        ET.SubElement(msg_elem, 'request-id').text = _xml_text(message_data['requestId'])

    # Process message content
    if isinstance(message_data.get('message'), dict):
        msg = message_data['message']

        # Add role
        if 'role' in msg:
            ET.SubElement(msg_elem, 'role').text = _xml_text(msg['role'])

        # Add model info
        if 'model' in msg:
            ET.SubElement(msg_elem, 'model').text = _xml_text(msg['model'])

        # Process content
        if 'content' in msg:
            content_elem = ET.SubElement(msg_elem, 'content')

            if isinstance(msg['content'], str):
                content_elem.text = _xml_text(msg['content'])
            elif isinstance(msg['content'], list):
                for content in msg['content']:
                    if isinstance(content, dict):
                        content_type = content.get('type')

                        if content_type == 'text':
                            text_elem = ET.SubElement(content_elem, 'text')
                            text_elem.text = _xml_text(content.get('text', ''))

                        elif content_type == 'thinking':
                            thinking_elem = ET.SubElement(content_elem, 'thinking')
                            if 'signature' in content:
                                thinking_elem.set('signature', _xml_text(content['signature']))
                            thinking_elem.text = _xml_text(content.get('thinking', ''))

                        elif content_type == 'tool_use':
                            tool_elem = ET.SubElement(content_elem, 'tool-use')
                            tool_elem.set('id', _xml_text(content.get('id', '')))
                            tool_elem.set('name', _xml_text(content.get('name', '')))

                            input_elem = ET.SubElement(tool_elem, 'input')
                            input_elem.text = _xml_text(json.dumps(content.get('input', {}), indent=2))

                        elif content_type == 'tool_result':
                            result_elem = ET.SubElement(content_elem, 'tool-result')
                            if 'tool_use_id' in content:
                                result_elem.set('tool-use-id', _xml_text(content['tool_use_id']))
                            result_elem.text = _xml_text(render_tool_result_content(content.get('content', '')))

        # Add usage info
        if 'usage' in msg:
            usage_elem = ET.SubElement(msg_elem, 'usage')
            usage = msg['usage']

            if 'input_tokens' in usage:
                ET.SubElement(usage_elem, 'input-tokens').text = _xml_text(usage['input_tokens'])
            if 'output_tokens' in usage:
                ET.SubElement(usage_elem, 'output-tokens').text = _xml_text(usage['output_tokens'])
            if 'cache_creation_input_tokens' in usage:
                ET.SubElement(usage_elem, 'cache-creation-tokens').text = _xml_text(usage['cache_creation_input_tokens'])
            if 'cache_read_input_tokens' in usage:
                ET.SubElement(usage_elem, 'cache-read-tokens').text = _xml_text(usage['cache_read_input_tokens'])
            if 'service_tier' in usage:
                ET.SubElement(usage_elem, 'service-tier').text = _xml_text(usage['service_tier'])

    # Add tool result metadata if present
    if 'toolUseResult' in message_data:
        tool_result = message_data['toolUseResult']
        if isinstance(tool_result, dict):
            tool_meta = ET.SubElement(msg_elem, 'tool-execution-metadata')

            if 'bytes' in tool_result:
                ET.SubElement(tool_meta, 'response-bytes').text = _xml_text(tool_result['bytes'])
            if 'code' in tool_result:
                ET.SubElement(tool_meta, 'response-code').text = _xml_text(tool_result['code'])
            if 'codeText' in tool_result:
                ET.SubElement(tool_meta, 'response-text').text = _xml_text(tool_result['codeText'])
            if 'durationMs' in tool_result:
                ET.SubElement(tool_meta, 'duration-ms').text = _xml_text(tool_result['durationMs'])
            if 'url' in tool_result:
                ET.SubElement(tool_meta, 'url').text = _xml_text(tool_result['url'])


def prettify_xml(elem: ET.Element) -> str:
    """Return a pretty-printed XML string for the Element."""
    try:
        rough_string = ET.tostring(elem, encoding='unicode', method='xml')
        reparsed = minidom.parseString(rough_string)
        return reparsed.toprettyxml(indent="  ")
    except ExpatError as e:
        # Fallback: return unprettified XML if pretty printing fails
        error(f"⚠️  XML prettification failed: {e}")
        return '<?xml version="1.0" ?>\n' + ET.tostring(elem, encoding='unicode', method='xml')
