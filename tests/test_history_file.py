"""<claude-dir>/history.jsonl is shared with running Claude Code processes."""
from __future__ import annotations

import os
import stat
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from ccsession.history_file import HistoryBusyError, append_lines, history_lock, rewrite_lines


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


def test_long_operation_refreshes_the_history_lock(tmp_path, monkeypatch):
    import ccsession.history_file as history_module
    history = tmp_path / "history.jsonl"
    lock = Path(os.path.realpath(history) + ".lock")
    refreshed = threading.Event()
    refresh_guard = threading.Lock()
    real_utime = os.utime
    frozen_now = time.time()

    def observe_refresh(path, *args, **kwargs):
        with refresh_guard:
            real_utime(path, *args, **kwargs)
            if path == str(lock):
                refreshed.set()

    monkeypatch.setattr(history_module.os, "utime", observe_refresh)
    # Keep the real heartbeat interval and timeout clock. Freeze only the stale
    # check's wall clock so a loaded runner cannot age a refreshed lock before
    # the contender gets scheduled.
    monkeypatch.setattr(history_module, "time", SimpleNamespace(
        time=lambda: frozen_now, monotonic=time.monotonic, sleep=time.sleep,
    ))
    with history_lock(history):
        with refresh_guard:
            old = frozen_now - 2 * history_module.LOCK_STALE_SECONDS
            real_utime(lock, (old, old))
            refreshed.clear()
        assert refreshed.wait(timeout=20), "the history lock heartbeat did not refresh the lock"
        assert frozen_now - lock.stat().st_mtime < history_module.LOCK_STALE_SECONDS
        # A real filesystem refresh must keep another Claude Code writer out.
        with pytest.raises(HistoryBusyError, match="locked"):
            with history_lock(history, timeout=0.2):
                pytest.fail("an active history lock was treated as stale")


def test_malformed_stale_lock_times_out(tmp_path):
    history = tmp_path / "history.jsonl"
    lock = Path(str(history) + ".lock")
    lock.write_text("not a lock directory", encoding="utf-8")
    old = time.time() - 30
    os.utime(lock, (old, old))
    start = time.monotonic()
    with pytest.raises(HistoryBusyError, match="locked"):
        with history_lock(history, timeout=0.08):
            pass
    assert time.monotonic() - start < 1
    assert lock.read_text(encoding="utf-8") == "not a lock directory"


def test_lost_lock_does_not_remove_another_writers_lock(tmp_path):
    history = tmp_path / "history.jsonl"
    lock = Path(str(history) + ".lock")
    previous = tmp_path / "old-lock"
    with pytest.raises(HistoryBusyError, match="lost"):
        with history_lock(history):
            lock.rename(previous)
            lock.mkdir()
    assert lock.is_dir(), "only the lock acquired by this operation may be removed"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlinks")
def test_rewrite_does_not_follow_a_preexisting_temporary_symlink(tmp_path):
    history = tmp_path / "history.jsonl"
    history.write_bytes(b'{"keep":1}\n{"drop":1}\n')
    victim = tmp_path / "unrelated"
    victim.write_bytes(b"precious")
    predictable = Path(f"{history}.ccsession-tmp-{os.getpid()}")
    predictable.symlink_to(victim)

    assert rewrite_lines(history, lambda lines: lines[:1]) == 1

    assert history.read_bytes() == b'{"keep":1}\n'
    assert victim.read_bytes() == b"precious"
    assert predictable.is_symlink()
