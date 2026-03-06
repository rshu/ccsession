"""Tests for exception handling changes."""
from __future__ import annotations

import json
import os
import time
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from ccsession.export.formatters import prettify_xml
from ccsession.export.session_discovery import identify_current_session


class TestPrettifyXmlExceptionHandling:
    def test_valid_xml(self):
        import xml.etree.ElementTree as ET
        root = ET.Element("root")
        ET.SubElement(root, "child").text = "hello"
        result = prettify_xml(root)
        assert "<root>" in result
        assert "<child>hello</child>" in result

    def test_malformed_xml_returns_fallback(self):
        """prettify_xml should catch ExpatError, not generic Exception."""
        import xml.etree.ElementTree as ET
        from xml.parsers.expat import ExpatError
        root = ET.Element("root")
        ET.SubElement(root, "child").text = "hello"

        # Patch minidom.parseString to raise ExpatError
        with patch('ccsession.export.formatters.minidom') as mock_minidom:
            mock_minidom.parseString.side_effect = ExpatError("malformed")
            result = prettify_xml(root)
            # Should return the rough (unprettified) XML string
            assert "<root>" in result


class TestIdentifyCurrentSessionExceptionHandling:
    def test_oserror_handled_gracefully(self, tmp_path):
        """identify_current_session catches OSError, not generic Exception."""
        # Create a real session file so stat() works in the refresh loop,
        # then make the marker file creation fail
        session_file = tmp_path / 'test.jsonl'
        session_file.write_text('{}')
        sessions = [{'path': session_file, 'mtime': time.time(), 'session_id': 'abc123'}]

        # Use a non-writable directory to trigger OSError on marker file creation
        readonly_dir = tmp_path / 'readonly'
        readonly_dir.mkdir()
        readonly_dir.chmod(0o444)

        with patch('ccsession.export.session_discovery.get_parent_claude_pid', return_value=12345):
            result = identify_current_session(sessions, str(readonly_dir))
            assert result is None

        # Clean up
        readonly_dir.chmod(0o755)

    def test_returns_none_when_no_claude_pid(self, tmp_path):
        """Should return None if not running inside Claude Code."""
        sessions = [{'path': tmp_path / 'test.jsonl', 'mtime': time.time(), 'session_id': 'abc123'}]

        with patch('ccsession.export.session_discovery.get_parent_claude_pid', return_value=None):
            result = identify_current_session(sessions, str(tmp_path))
            assert result is None
