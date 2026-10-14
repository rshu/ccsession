"""Safe access to ``<claude-dir>/history.jsonl``, which running Claude Code processes share.

Claude Code 2.1.287 appends prompts while holding a proper-lockfile lock: a directory
named ``<realpath>.lock``, considered stale once its mtime is more than 10 seconds
old (the holder refreshes it every 5 seconds). ccsession takes the same lock around
every append and rewrite, writes bytes (so Windows never turns ``\\n`` into ``\\r\\n``),
creates the file 0600 like Claude Code, keeps an existing file's permissions and
symlink on rewrite, and replaces it atomically.
"""
from __future__ import annotations

import os
import stat
import time
from contextlib import contextmanager
from typing import Callable, Iterable

LOCK_STALE_SECONDS = 10
_BINARY = getattr(os, 'O_BINARY', 0)
_REWRITE_ATTEMPTS = 5


class HistoryBusyError(RuntimeError):
    """The history file stayed locked or kept changing."""


@contextmanager
def history_lock(path, timeout: float = 30.0):
    """Hold Claude Code's lock on the history file; yields the file's real path."""
    real = os.path.realpath(path)
    lock = real + '.lock'
    os.makedirs(os.path.dirname(real), exist_ok=True)
    deadline = time.monotonic() + timeout
    while True:
        try:
            os.mkdir(lock)
            break
        except FileExistsError:
            try:
                age = time.time() - os.stat(lock).st_mtime
            except FileNotFoundError:
                continue
            if age > LOCK_STALE_SECONDS:
                try:
                    os.rmdir(lock)
                except OSError:
                    time.sleep(0.05)
                continue
            if time.monotonic() > deadline:
                raise HistoryBusyError(f"{real} is locked by another process ({lock})")
            time.sleep(0.05)
    try:
        yield real
    finally:
        try:
            os.rmdir(lock)
        except OSError:
            pass


def _ends_without_newline(real: str) -> bool:
    try:
        size = os.path.getsize(real)
    except OSError:
        return False
    if size == 0:
        return False
    with open(real, 'rb') as f:
        f.seek(-1, os.SEEK_END)
        return f.read(1) != b'\n'


def append_lines(path, lines: Iterable[str], *, before_each: Callable[[str], None] | None = None) -> int:
    """Append lines (without their newline) under the lock.

    A file whose last line lacks its newline gets one first. ``before_each`` is
    called with each line just before it is written, so a caller can record it
    durably first. ``lines`` may be a generator; it is consumed under the lock.
    Returns the number of lines written.
    """
    written = 0
    with history_lock(path) as real:
        needs_separator = _ends_without_newline(real)
        fd = os.open(real, os.O_WRONLY | os.O_CREAT | os.O_APPEND | _BINARY, 0o600)
        with os.fdopen(fd, 'wb') as f:
            if needs_separator:
                f.write(b'\n')
                f.flush()
            for line in lines:
                if before_each is not None:
                    before_each(line)
                f.write(line.encode('utf-8') + b'\n')
                f.flush()
                written += 1
    return written


def _read_bytes(real: str) -> bytes:
    with open(real, 'rb') as f:
        return f.read()


def _unchanged(real: str, before: os.stat_result) -> bool:
    now = os.stat(real)
    return (now.st_size, now.st_mtime_ns, now.st_ino) == (before.st_size, before.st_mtime_ns, before.st_ino)


def rewrite_lines(path, decide: Callable[[list], list], *, remove_if_empty: bool = False) -> int:
    """Rewrite the file keeping only the lines ``decide`` returns.

    ``decide`` gets the lines as bytes with their line endings and returns the ones
    to keep, untouched. The rewrite happens under the lock, through a temporary
    file with the original permissions, replacing the real file behind a symlink;
    it is retried if another writer changed the file in between. Returns the
    number of lines removed.

    Raises:
        HistoryBusyError: if the file stayed locked or kept changing.
    """
    with history_lock(path) as real:
        for _ in range(_REWRITE_ATTEMPTS):
            if not os.path.isfile(real):
                return 0
            before = os.stat(real)
            lines = _read_bytes(real).splitlines(keepends=True)
            kept = decide(lines)
            removed = len(lines) - len(kept)
            if not removed:
                return 0
            if not kept and remove_if_empty:
                if _unchanged(real, before):
                    os.unlink(real)
                    return removed
                continue
            mode = stat.S_IMODE(before.st_mode)
            tmp = f'{real}.ccsession-tmp-{os.getpid()}'
            try:
                fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | _BINARY, mode)
                with os.fdopen(fd, 'wb') as f:
                    f.write(b''.join(kept))
                os.chmod(tmp, mode)
                if not _unchanged(real, before):
                    os.unlink(tmp)
                    continue
                os.replace(tmp, real)
                return removed
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
    raise HistoryBusyError(f"{path} kept changing while it was being rewritten")
