"""Tests for exception handling changes."""
from __future__ import annotations

import os
import time
from unittest.mock import patch

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


class TestIdentifyCurrentSession:
    def _sessions(self, tmp_path, *names):
        out = []
        for name in names:
            path = tmp_path / f"{name}.jsonl"
            path.write_text('{}\n', encoding='utf-8')
            out.append({'path': path, 'mtime': path.stat().st_mtime, 'session_id': name})
        return out

    def test_oserror_from_a_vanishing_session_file_is_handled(self, tmp_path):
        """A transcript deleted between discovery and identification must not crash the export."""
        sessions = self._sessions(tmp_path, 'present')
        sessions.append({'path': tmp_path / 'gone.jsonl', 'mtime': time.time(), 'session_id': 'gone'})

        with patch('ccsession.export.session_discovery.get_parent_claude_pid', return_value=12345):
            with patch('ccsession.export.session_discovery.time.sleep'):
                assert identify_current_session(sessions, str(tmp_path)) is None

    def test_writes_nothing_into_the_project_directory(self, tmp_path):
        """Identification used to drop a marker file into the user's project tree."""
        project = tmp_path / 'project'
        project.mkdir()
        sessions = self._sessions(tmp_path, 'a', 'b')
        seen_during_wait = []

        def observe(_seconds):
            seen_during_wait.extend(p.name for p in project.iterdir())

        with patch('ccsession.export.session_discovery.get_parent_claude_pid', return_value=12345):
            with patch('ccsession.export.session_discovery.time.sleep', side_effect=observe):
                identify_current_session(sessions, str(project))

        assert seen_during_wait == []
        assert list(project.iterdir()) == []

    def test_returns_the_session_whose_transcript_grew_during_the_wait(self, tmp_path):
        sessions = self._sessions(tmp_path, 'a', 'b')

        def append_to_b(_seconds):
            with open(sessions[1]['path'], 'a', encoding='utf-8') as f:
                f.write('{"type": "user"}\n')
            future = time.time() + 5
            os.utime(sessions[1]['path'], (future, future))

        with patch('ccsession.export.session_discovery.get_parent_claude_pid', return_value=12345):
            with patch('ccsession.export.session_discovery.time.sleep', side_effect=append_to_b):
                result = identify_current_session(sessions, str(tmp_path))

        assert result is not None and result['session_id'] == 'b'

    def test_returns_none_when_no_transcript_changes(self, tmp_path):
        sessions = self._sessions(tmp_path, 'a', 'b')
        with patch('ccsession.export.session_discovery.get_parent_claude_pid', return_value=12345):
            with patch('ccsession.export.session_discovery.time.sleep'):
                assert identify_current_session(sessions, str(tmp_path)) is None

    def test_returns_none_when_no_claude_pid(self, tmp_path):
        """Should return None if not running inside Claude Code."""
        sessions = [{'path': tmp_path / 'test.jsonl', 'mtime': time.time(), 'session_id': 'abc123'}]

        with patch('ccsession.export.session_discovery.get_parent_claude_pid', return_value=None):
            result = identify_current_session(sessions, str(tmp_path))
            assert result is None
