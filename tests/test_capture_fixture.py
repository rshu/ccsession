"""Fixture capture uses a throwaway Claude store and never touches account data."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ccsession.paths import get_normalized_project_dir
from scripts import capture_fixture


SID = '11111111-2222-4333-8444-555555555555'


@pytest.fixture
def capture_source(tmp_path, monkeypatch):
    claude = tmp_path / 'source-claude'
    project = tmp_path / 'source-project'
    root = claude / 'projects' / get_normalized_project_dir(project)
    root.mkdir(parents=True)
    record = {'type': 'user', 'sessionId': SID, 'cwd': str(project), 'uuid': 'u1',
              'message': {'role': 'user', 'content': 'hello'}}
    transcript = root / f'{SID}.jsonl'
    transcript.write_text(json.dumps(record) + '\n', encoding='utf-8')
    monkeypatch.setenv('CLAUDE_CONFIG_DIR', str(claude))
    monkeypatch.delenv('CLAUDE_CODE_PROJECT_DIR_NAME', raising=False)
    monkeypatch.setattr(Path, 'home', lambda: tmp_path / 'home-alice')
    monkeypatch.setattr(capture_fixture.getpass, 'getuser', lambda: 'alice')
    return claude, transcript


@pytest.mark.parametrize('destination', ['store', 'ancestor', 'inside'])
def test_capture_refuses_output_overlapping_its_source_store(tmp_path, capture_source, destination):
    claude, transcript = capture_source
    out = {'store': claude, 'ancestor': tmp_path, 'inside': transcript.parent}[destination]
    before = transcript.read_bytes()
    assert capture_fixture.main([SID, str(out)]) == 1
    assert transcript.read_bytes() == before


def test_capture_handles_lone_surrogates_and_non_object_history(tmp_path, capture_source):
    claude, transcript = capture_source
    record = json.loads(transcript.read_text(encoding='utf-8'))
    record['message']['content'] = 'cut \ud800'
    transcript.write_text(json.dumps(record) + '\n', encoding='utf-8')
    (claude / 'history.jsonl').write_text('42\nnull\n{"sessionId":"' + SID + '","display":"cut \\ud800"}\n',
                                         encoding='utf-8')
    out = tmp_path / 'fixture'
    assert capture_fixture.main([SID, str(out)]) == 0
    main = out / 'projects' / get_normalized_project_dir(capture_fixture.FIXTURE_PROJECT) / f'{SID}.jsonl'
    assert json.loads(main.read_text(encoding='utf-8'))['message']['content'] == 'cut \ud800'
    assert json.loads((out / 'history.jsonl').read_text(encoding='utf-8'))['display'] == 'cut \ud800'


def test_capture_sanitizes_text_sidecars_and_text_file_history(tmp_path, capture_source):
    claude, transcript = capture_source
    session_dir = transcript.parent / SID
    session_dir.mkdir()
    text = 'Contact alice@private.example at ' + str(tmp_path / 'home-alice') + '\n'
    (session_dir / 'diagnostic.txt').write_text(text, encoding='utf-8')
    history = claude / 'file-history' / SID
    history.mkdir(parents=True)
    (history / 'snapshot').write_text(text, encoding='utf-8')
    (history / 'binary').write_bytes(b'\xff\x00\x01')
    out = tmp_path / 'fixture'
    assert capture_fixture.main([SID, str(out)]) == 0
    root = out / 'projects' / get_normalized_project_dir(capture_fixture.FIXTURE_PROJECT) / SID
    for path in (root / 'diagnostic.txt', out / 'file-history' / SID / 'snapshot'):
        sanitized = path.read_text(encoding='utf-8')
        assert 'alice' not in sanitized and 'user@example.com' in sanitized
        assert str(tmp_path / 'home-alice') not in sanitized
    assert (out / 'file-history' / SID / 'binary').read_bytes() == b'\xff\x00\x01'


def test_failed_capture_keeps_an_existing_fixture(tmp_path, capture_source):
    _, transcript = capture_source
    with transcript.open('a', encoding='utf-8') as f:
        f.write('not json\n')
    out = tmp_path / 'fixture'
    out.mkdir()
    (out / 'keep.txt').write_text('precious', encoding='utf-8')
    assert capture_fixture.main([SID, str(out)]) == 1
    assert (out / 'keep.txt').read_text(encoding='utf-8') == 'precious'


def test_binary_personal_text_is_rejected_before_replacing_output(tmp_path, capture_source):
    claude, _ = capture_source
    history = claude / 'file-history' / SID
    history.mkdir(parents=True)
    (history / 'binary').write_bytes(b'\xff\0private@personal.example')
    out = tmp_path / 'fixture'
    out.mkdir()
    (out / 'keep.txt').write_text('precious', encoding='utf-8')

    assert capture_fixture.main([SID, str(out)]) == 1
    assert (out / 'keep.txt').read_text(encoding='utf-8') == 'precious'


def test_successful_capture_replaces_an_existing_fixture(tmp_path, capture_source):
    out = tmp_path / 'fixture'
    out.mkdir()
    (out / 'obsolete.txt').write_text('previous fixture', encoding='utf-8')
    assert capture_fixture.main([SID, str(out)]) == 0
    assert (out / 'history.jsonl').is_file()
    assert not (out / 'obsolete.txt').exists()
