from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path

# Claude Code 2.1.287 (the bundled JavaScript):
#   function k(e){return e.replace(/[^a-zA-Z0-9]/g,"-")}
#   function Jx(e){let n=k(e);if(n.length<=200)return n;
#                  return`${n.slice(0,200)}-${Math.abs(tee(e)).toString(36)}`}
#   function tee(t){let e=0;for(let n=0;n<t.length;n++)e=(e<<5)-e+t.charCodeAt(n)|0;return e}
# The regex has no ``u`` flag, so it runs over UTF-16 code units: a BMP character outside
# [A-Za-z0-9] becomes one dash, an astral character (surrogate pair) becomes two.
_PROJECT_DIR_NAME_MAX_LENGTH = 200
_PROJECT_DIR_NAME_OVERRIDE_ENV = 'CLAUDE_CODE_PROJECT_DIR_NAME'
_OVERRIDE_RE = re.compile(r'^[A-Za-z0-9_-]{1,64}$')
_WINDOWS_RESERVED_RE = re.compile(r'^(?:con|prn|aux|nul|com[0-9]|lpt[0-9])$', re.IGNORECASE)
_BASE36_DIGITS = '0123456789abcdefghijklmnopqrstuvwxyz'


def _utf16_code_units(text: str) -> list[int]:
    # surrogatepass: a lone surrogate (how os.getcwd() surfaces an undecodable byte on
    # Linux) is one code unit, as it is to JavaScript, instead of an encoding error
    encoded = text.encode('utf-16-le', 'surrogatepass')
    return [int.from_bytes(encoded[i:i + 2], 'little') for i in range(0, len(encoded), 2)]


def _js_string_hash(text: str) -> int:
    """``(h << 5) - h + charCodeAt(i) | 0`` over UTF-16 code units, as a signed 32-bit int."""
    h = 0
    for unit in _utf16_code_units(text):
        h = ((h << 5) - h + unit) & 0xFFFFFFFF
    return h - 0x100000000 if h >= 0x80000000 else h


def _base36(value: int) -> str:
    if value == 0:
        return '0'
    digits = []
    while value:
        value, rem = divmod(value, 36)
        digits.append(_BASE36_DIGITS[rem])
    return ''.join(reversed(digits))


def claude_code_path_text(path: str | Path) -> str:
    """A path as Claude Code (Node) sees it.

    On POSIX, ``os.getcwd()`` surfaces bytes that are not valid UTF-8 as lone
    surrogates (one per byte); Node decodes the same bytes with one U+FFFD per
    maximal invalid subpart. This converts the former into the latter so names,
    hashes and recorded ``cwd`` values match what Claude Code writes. Other text,
    and every path on Windows (where paths are UTF-16 already), is returned as is.
    """
    text = str(path)
    if os.name == 'nt' or not any('\udc80' <= ch <= '\udcff' for ch in text):
        return text
    try:
        return text.encode('utf-8', 'surrogateescape').decode('utf-8', 'replace')
    except UnicodeEncodeError:
        # A surrogate outside the surrogateescape range: not from a byte path
        return text


def get_normalized_project_dir(project_path: str | Path) -> str:
    """The directory name Claude Code derives from a working directory.

    Every UTF-16 code unit outside ``[A-Za-z0-9]`` becomes ``-``; a result longer than
    200 characters is cut to 200 and suffixed with ``-<base36 hash of the original>``.
    The rule is platform-independent: ``/home/u/p`` -> ``-home-u-p`` and
    ``C:\\Users\\u\\p`` -> ``C--Users-u-p``.
    """
    # Claude Code normalises the working directory to NFC before deriving the name
    text = unicodedata.normalize('NFC', claude_code_path_text(project_path))
    name = ''.join('-' if not (0x30 <= unit <= 0x39 or 0x41 <= unit <= 0x5A or 0x61 <= unit <= 0x7A)
                   else chr(unit) for unit in _utf16_code_units(text))
    if len(name) <= _PROJECT_DIR_NAME_MAX_LENGTH:
        return name
    return f'{name[:_PROJECT_DIR_NAME_MAX_LENGTH]}-{_base36(abs(_js_string_hash(text)))}'


def _project_dir_name_override() -> str | None:
    """``CLAUDE_CODE_PROJECT_DIR_NAME``, which Claude Code honours only together with
    ``CLAUDE_CONFIG_DIR`` and only when it is a plain, non-reserved directory name."""
    if not os.environ.get('CLAUDE_CONFIG_DIR'):
        return None
    value = os.environ.get(_PROJECT_DIR_NAME_OVERRIDE_ENV)
    if not value or not _OVERRIDE_RE.fullmatch(value) or _WINDOWS_RESERVED_RE.fullmatch(value):
        return None
    return value


def get_project_dir_name(project_path: str | Path) -> str:
    """The name of ``<claude-dir>/projects/<name>/`` for a project: the override when
    Claude Code would use it, otherwise the normalized path."""
    return _project_dir_name_override() or get_normalized_project_dir(project_path)


def _canonical(path: Path) -> Path:
    """Absolute, with ``.`` and ``..`` collapsed (as Node's path.resolve does), so
    every path ccsession records is canonical. Symlinks are left alone."""
    return Path(os.path.abspath(path))


def get_claude_dir() -> Path:
    """Return Claude Code's config directory.

    Honours ``CLAUDE_CONFIG_DIR`` the same way the CLI does; an unset or empty
    value means ``~/.claude``. A relative value is made absolute against the
    current directory and ``..`` is collapsed, so paths recorded in a snapshot stay
    valid wherever a later restore runs.
    """
    configured = os.environ.get('CLAUDE_CONFIG_DIR', '').strip()
    if configured:
        return _canonical(Path(configured).expanduser())
    return _canonical(Path.home() / '.claude')


def get_projects_root() -> Path:
    """Get <claude-dir>/projects/."""
    return get_claude_dir() / 'projects'


def get_projects_dir(project_path: str | Path) -> Path:
    """Get <claude-dir>/projects/<project-dir-name>/ for the given project."""
    return get_projects_root() / get_project_dir_name(project_path)


def get_session_dir(project_path: str | Path, session_id: str) -> Path:
    """Get the per-session directory <claude-dir>/projects/<normalized>/<session_id>/."""
    return get_projects_dir(project_path) / session_id


def get_file_history_dir(session_id: str) -> Path:
    """Get <claude-dir>/file-history/<session_id>/."""
    return get_claude_dir() / 'file-history' / session_id


def get_session_env_dir(session_id: str) -> Path:
    """Get <claude-dir>/session-env/<session_id>/."""
    return get_claude_dir() / 'session-env' / session_id


def get_history_file() -> Path:
    """Get <claude-dir>/history.jsonl (prompt history shown by the CLI)."""
    return get_claude_dir() / 'history.jsonl'


def get_import_storage_dir() -> Path:
    """Where ccsession keeps the pre-import snapshot and import logs.

    ``~/.claude-session-imports/`` by default. When ``CLAUDE_CONFIG_DIR`` points at an
    alternative Claude config directory the storage moves with it, to
    ``<CLAUDE_CONFIG_DIR>/ccsession-imports/``, so imports into an isolated config
    directory never replace the snapshot that protects the default one.
    """
    configured = os.environ.get('CLAUDE_CONFIG_DIR', '').strip()
    if configured:
        return _canonical(Path(configured).expanduser()) / 'ccsession-imports'
    return _canonical(Path.home() / '.claude-session-imports')


def get_snapshot_dir() -> Path:
    """Get <import-storage>/pre-import-snapshot/."""
    return get_import_storage_dir() / 'pre-import-snapshot'
