"""<claude-dir>/history.jsonl is shared with running Claude Code processes."""
from __future__ import annotations

import os
import stat
import sys
import threading
import time
from pathlib import Path

import pytest

from ccsession.history_file import append_lines, history_lock, rewrite_lines


def _hold_lock(path: Path, seconds: float):
    lock = Path(os.path.realpath(path)) .with_name(path.name + ".lock")
    lock.mkdir()

    def release():
        time.sleep(seconds)
        lock.rmdir()

    t = threading.Thread(target=release)
    t.start()
    return t


def test_rewrite_waits_for_claude_codes_lock(tmp_path):
    """Claude Code appends only while holding <history>.lock (proper-lockfile)."""
    history = tmp_path / "history.jsonl"
    history.write_bytes(b'{"a":1}\n{"b":2}\n')
    t = _hold_lock(history, 0.4)
    start = time.monotonic()

    rewrite_lines(history, lambda lines: [l for l in lines if b'"b"' not in l])

    t.join()
    assert time.monotonic() - start >= 0.35
    assert history.read_bytes() == b'{"a":1}\n'
    assert not Path(str(history) + ".lock").exists()


def test_a_stale_lock_is_broken(tmp_path):
    history = tmp_path / "history.jsonl"
    history.write_bytes(b'{"a":1}\n')
    lock = Path(str(history) + ".lock")
    lock.mkdir()
    old = time.time() - 30
    os.utime(lock, (old, old))

    with history_lock(history, timeout=2):
        pass

    assert not lock.exists()


def test_append_writes_lf_only_and_creates_a_private_file(tmp_path):
    history = tmp_path / "history.jsonl"
    append_lines(history, ['{"a":1}', '{"b":2}'])
    assert history.read_bytes() == b'{"a":1}\n{"b":2}\n'
    if sys.platform != "win32":
        assert stat.S_IMODE(history.stat().st_mode) == 0o600


def test_append_adds_a_missing_final_newline_first(tmp_path):
    history = tmp_path / "history.jsonl"
    history.write_bytes(b'{"mine":1}')
    append_lines(history, ['{"b":2}'])
    assert history.read_bytes() == b'{"mine":1}\n{"b":2}\n'


def test_rewrite_keeps_other_lines_byte_for_byte(tmp_path):
    """Windows-written CRLF lines and undecodable bytes survive untouched."""
    history = tmp_path / "history.jsonl"
    history.write_bytes(b'{"a":1}\r\n{"drop":1}\n{"c":"\xff"}\n')
    rewrite_lines(history, lambda lines: [l for l in lines if b'drop' not in l])
    assert history.read_bytes() == b'{"a":1}\r\n{"c":"\xff"}\n'


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions and symlinks")
def test_rewrite_keeps_mode_and_symlink(tmp_path):
    real = tmp_path / "dot" / "history.jsonl"
    real.parent.mkdir()
    real.write_bytes(b'{"a":1}\n{"drop":1}\n')
    os.chmod(real, 0o600)
    link = tmp_path / "history.jsonl"
    os.symlink(real, link)
    rewrite_lines(link, lambda lines: [l for l in lines if b'drop' not in l])
    assert link.is_symlink() and real.read_bytes() == b'{"a":1}\n'
    assert stat.S_IMODE(real.stat().st_mode) == 0o600
