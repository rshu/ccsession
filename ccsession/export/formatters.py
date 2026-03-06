from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from xml.dom import minidom
from xml.parsers.expat import ExpatError

from ccsession.constants import TOOL_RESULT_MAX_LENGTH
from ccsession.utils import parse_iso_timestamp


def clean_text_for_xml(text: str | None) -> str | None:
    """Remove or replace characters that cause XML parsing issues."""
    if not text:
        return text
    # Remove control characters except newline, tab, and carriage return
    text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]', '', str(text))
    return text


def format_message_markdown(message_data: dict) -> str:
    """Format a single message as markdown."""
    output = []

    if 'message' not in message_data:
        return ""

    msg = message_data['message']
    timestamp = message_data.get('timestamp', '')

    # Add timestamp
    if timestamp:
        dt = parse_iso_timestamp(timestamp)
        output.append(f"**[{dt.strftime('%Y-%m-%d %H:%M:%S')}]**")

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
                        result = content.get('content', '')
                        if isinstance(result, str):
                            output.append(result[:TOOL_RESULT_MAX_LENGTH])
                            if len(result) > TOOL_RESULT_MAX_LENGTH:
                                output.append(f"\n... (truncated, {len(result) - TOOL_RESULT_MAX_LENGTH} chars omitted)")
                        else:
                            output.append(str(result))
                        output.append("```\n")

    return '\n'.join(output)


def format_message_xml(message_data: dict, parent_element: ET.Element) -> None:
    """Format a single message as XML element."""
    msg_elem = ET.SubElement(parent_element, 'message')

    # Add attributes
    msg_elem.set('uuid', message_data.get('uuid', ''))
    if message_data.get('parentUuid'):
        msg_elem.set('parent-uuid', message_data['parentUuid'])
    msg_elem.set('timestamp', message_data.get('timestamp', ''))

    # Add metadata
    if 'type' in message_data:
        ET.SubElement(msg_elem, 'event-type').text = message_data['type']
    if 'cwd' in message_data:
        ET.SubElement(msg_elem, 'working-directory').text = message_data['cwd']
    if 'requestId' in message_data:
        ET.SubElement(msg_elem, 'request-id').text = message_data['requestId']

    # Process message content
    if 'message' in message_data:
        msg = message_data['message']

        # Add role
        if 'role' in msg:
            ET.SubElement(msg_elem, 'role').text = msg['role']

        # Add model info
        if 'model' in msg:
            ET.SubElement(msg_elem, 'model').text = msg['model']

        # Process content
        if 'content' in msg:
            content_elem = ET.SubElement(msg_elem, 'content')

            if isinstance(msg['content'], str):
                content_elem.text = msg['content']
            elif isinstance(msg['content'], list):
                for content in msg['content']:
                    if isinstance(content, dict):
                        content_type = content.get('type')

                        if content_type == 'text':
                            text_elem = ET.SubElement(content_elem, 'text')
                            text_elem.text = clean_text_for_xml(content.get('text', ''))

                        elif content_type == 'thinking':
                            thinking_elem = ET.SubElement(content_elem, 'thinking')
                            if 'signature' in content:
                                thinking_elem.set('signature', content['signature'])
                            thinking_elem.text = clean_text_for_xml(content.get('thinking', ''))

                        elif content_type == 'tool_use':
                            tool_elem = ET.SubElement(content_elem, 'tool-use')
                            tool_elem.set('id', content.get('id', ''))
                            tool_elem.set('name', content.get('name', ''))

                            input_elem = ET.SubElement(tool_elem, 'input')
                            input_elem.text = clean_text_for_xml(json.dumps(content.get('input', {}), indent=2))

                        elif content_type == 'tool_result':
                            result_elem = ET.SubElement(content_elem, 'tool-result')
                            if 'tool_use_id' in content:
                                result_elem.set('tool-use-id', content['tool_use_id'])

                            result_content = content.get('content', '')
                            if isinstance(result_content, str):
                                result_elem.text = clean_text_for_xml(result_content)
                            else:
                                result_elem.text = clean_text_for_xml(str(result_content))

        # Add usage info
        if 'usage' in msg:
            usage_elem = ET.SubElement(msg_elem, 'usage')
            usage = msg['usage']

            if 'input_tokens' in usage:
                ET.SubElement(usage_elem, 'input-tokens').text = str(usage['input_tokens'])
            if 'output_tokens' in usage:
                ET.SubElement(usage_elem, 'output-tokens').text = str(usage['output_tokens'])
            if 'cache_creation_input_tokens' in usage:
                ET.SubElement(usage_elem, 'cache-creation-tokens').text = str(usage['cache_creation_input_tokens'])
            if 'cache_read_input_tokens' in usage:
                ET.SubElement(usage_elem, 'cache-read-tokens').text = str(usage['cache_read_input_tokens'])
            if 'service_tier' in usage:
                ET.SubElement(usage_elem, 'service-tier').text = usage['service_tier']

    # Add tool result metadata if present
    if 'toolUseResult' in message_data:
        tool_result = message_data['toolUseResult']
        if isinstance(tool_result, dict):
            tool_meta = ET.SubElement(msg_elem, 'tool-execution-metadata')

            if 'bytes' in tool_result:
                ET.SubElement(tool_meta, 'response-bytes').text = str(tool_result['bytes'])
            if 'code' in tool_result:
                ET.SubElement(tool_meta, 'response-code').text = str(tool_result['code'])
            if 'codeText' in tool_result:
                ET.SubElement(tool_meta, 'response-text').text = tool_result['codeText']
            if 'durationMs' in tool_result:
                ET.SubElement(tool_meta, 'duration-ms').text = str(tool_result['durationMs'])
            if 'url' in tool_result:
                ET.SubElement(tool_meta, 'url').text = tool_result['url']


def prettify_xml(elem: ET.Element) -> str:
    """Return a pretty-printed XML string for the Element."""
    try:
        rough_string = ET.tostring(elem, encoding='unicode', method='xml')
        reparsed = minidom.parseString(rough_string)
        return reparsed.toprettyxml(indent="  ")
    except ExpatError as e:
        # Fallback: return unprettified XML if pretty printing fails
        print(f"\u26a0\ufe0f  XML prettification failed: {e}")
        return ET.tostring(elem, encoding='unicode', method='xml')
