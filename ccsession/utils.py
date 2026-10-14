from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path

# Any surrogate code point left in a str after json.loads is a lone one (json joins
# escaped pairs); JSON.stringify writes those as \uXXXX escapes, and so must we,
# since UTF-8 cannot encode them.
_SURROGATE_RE = re.compile('[\ud800-\udfff]')


def utc_now_iso() -> str:
    """Return current UTC time as ISO string with 'Z' suffix."""
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def parse_iso_timestamp(ts: str) -> datetime:
    """Parse an ISO timestamp string (with 'Z' or '+00:00') into a timezone-aware datetime.

    A timestamp without an offset is taken to be UTC.
    """
    parsed = datetime.fromisoformat(ts.replace('Z', '+00:00'))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def json_line(record) -> str:
    """Serialise one JSONL record the way Claude Code would.

    Non-ASCII text stays as is; lone surrogates (a string cut in the middle of an
    emoji, or an undecodable path byte) become ``\\uXXXX`` escapes, so the line is
    always valid UTF-8 and parses back to the same value.
    """
    text = json.dumps(record, ensure_ascii=False)
    if _SURROGATE_RE.search(text):
        text = _SURROGATE_RE.sub(lambda m: '\\u%04x' % ord(m.group()), text)
    return text


def file_digest(path) -> dict:
    """``{'size': ..., 'sha256': ...}`` of a file, to recognise it later."""
    h = hashlib.sha256()
    size = 0
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
            size += len(chunk)
    return {'size': size, 'sha256': h.hexdigest()}


def copy_file_writable(src, dst) -> None:
    """Copy a file's content, permissions and times, always leaving the copy writable.

    ``shutil.copy2`` also carries the read-only attribute (Windows) and file flags
    such as ``uchg`` (macOS) onto the copy, which would make it impossible for a
    restore to delete what the import wrote.
    """
    shutil.copyfile(src, dst)
    st = os.stat(src)
    os.chmod(dst, stat.S_IMODE(st.st_mode) | stat.S_IWUSR | stat.S_IRUSR)
    try:
        os.utime(dst, ns=(st.st_atime_ns, st.st_mtime_ns))
    except OSError:
        pass


def _make_writable_and_retry(func, path, _exc) -> None:
    """rmtree error handler: clear read-only state on the entry and its directory, retry."""
    for target in (os.path.dirname(path), path):
        try:
            os.chmod(target, stat.S_IMODE(os.lstat(target).st_mode) | stat.S_IWRITE | stat.S_IREAD
                     | (stat.S_IEXEC if os.path.isdir(target) else 0))
        except OSError:
            pass
    func(path)


def force_rmtree(path, ignore_errors: bool = False) -> None:
    """``shutil.rmtree`` that also removes read-only files and directories."""
    if not os.path.lexists(path):
        return
    try:
        if os.path.islink(path) or not os.path.isdir(path):
            force_unlink(path)
        elif sys.version_info >= (3, 12):
            shutil.rmtree(path, onexc=_make_writable_and_retry)
        else:
            shutil.rmtree(path, onerror=lambda f, p, e: _make_writable_and_retry(f, p, e))
    except OSError:
        if not ignore_errors:
            raise


def force_unlink(path) -> None:
    """Remove a file (or symlink), clearing a read-only attribute if that is what blocks it."""
    try:
        os.unlink(path)
    except PermissionError:
        _make_writable_and_retry(os.unlink, str(path), None)


def read_json(path: Path) -> dict:
    """Read a JSON file with UTF-8 encoding."""
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def ensure_private_dir(path) -> Path:
    """Create ``path`` (and parents) and make it owner-only (0700 on POSIX)."""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    if os.name != 'nt':
        try:
            os.chmod(path, 0o700)
        except OSError:
            pass
    return path


def open_private(path, flags: int):
    """``os.open`` a file with owner-only permissions (0600), whatever the umask."""
    fd = os.open(path, flags | getattr(os, 'O_BINARY', 0), 0o600)
    if os.name != 'nt':
        try:
            os.fchmod(fd, 0o600)
        except OSError:
            pass
    return fd


def write_json(path: Path, data, indent: int = 2, *, private: bool = False) -> None:
    """Write data as JSON with UTF-8 encoding, creating parent directories.

    The file is written to a sibling temporary file and moved into place, so a
    failure part-way (disk full, unserialisable value, interrupt) leaves the
    previous content intact instead of a truncated document. ``private`` makes
    the file owner-only (0600).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f'.{path.name}.tmp-{os.getpid()}')
    try:
        if private:
            f = os.fdopen(open_private(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC), 'w', encoding='utf-8')
        else:
            f = open(tmp, 'w', encoding='utf-8')
        with f:
            json.dump(data, f, indent=indent)
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
