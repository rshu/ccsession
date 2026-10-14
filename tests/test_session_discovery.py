import json
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ccsession.export.session_discovery import find_session_by_id, get_parent_claude_pid, read_session_cwd


@pytest.mark.skipif(os.name == "nt", reason="ps(1) is not available on Windows")
def test_detects_parent_whose_command_line_mentions_claude():
    """The parent's command line is read with ps(1); the keyword used must be
    valid on both GNU and BSD ps, or detection silently fails on macOS."""
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)", "claude-marker"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(0.3)  # let the child exec so ps sees its argv
        with patch("ccsession.export.session_discovery.os.getppid", return_value=child.pid):
            assert get_parent_claude_pid() == child.pid
    finally:
        child.kill()
        child.wait()


def test_find_session_by_id_reports_the_sessions_own_project_path(tmp_path, monkeypatch):
    """The first record of a 2.1 transcript is often a last-prompt with no cwd;
    the project path must come from the first record that has one."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    project_dir = tmp_path / ".claude" / "projects" / "-home-user-proj"
    project_dir.mkdir(parents=True)
    sid = "0b6f2a1e-1111-2222-3333-444444444444"
    lines = [
        {"type": "last-prompt", "sessionId": sid, "lastPrompt": "fix it", "leafUuid": "u1"},
        {"type": "user", "uuid": "u1", "parentUuid": None, "sessionId": sid,
         "cwd": "/home/user/proj", "message": {"role": "user", "content": "fix it"}},
    ]
    (project_dir / f"{sid}.jsonl").write_text("".join(json.dumps(l) + "\n" for l in lines), encoding="utf-8")

    found = find_session_by_id(sid)

    assert found["project_path"] == "/home/user/proj"
    assert read_session_cwd(project_dir / f"{sid}.jsonl") == "/home/user/proj"


def test_read_session_cwd_is_none_when_no_record_has_a_cwd(tmp_path):
    path = tmp_path / "s.jsonl"
    path.write_text('{"type":"mode","mode":"default"}\nnot json\n', encoding="utf-8")
    assert read_session_cwd(path) is None
