"""Verbosity-aware output functions for the ccsession CLI.

Levels: ``QUIET`` shows errors, warnings and the final result only; ``NORMAL`` adds
progress; ``VERBOSE`` adds per-file detail.
"""
from __future__ import annotations

import sys

QUIET = 0
NORMAL = 1
VERBOSE = 2

_verbosity: int = NORMAL


def set_verbosity(level: int) -> None:
    global _verbosity
    _verbosity = level


def get_verbosity() -> int:
    return _verbosity


def configure_streams() -> None:
    """Make stdout and stderr tolerate characters their encoding cannot represent.

    Every command prints emoji. On Windows a redirected stream uses the ANSI code
    page with ``errors='strict'``, so without this the first line raises
    UnicodeEncodeError before any work is done. Unencodable characters are
    replaced with ``?``; nothing else about the streams changes.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, 'reconfigure', None)
        if reconfigure is None:
            continue
        try:
            reconfigure(errors='replace')
        except (ValueError, OSError):
            pass


def info(msg: str) -> None:
    """Print at normal and verbose levels."""
    if _verbosity >= NORMAL:
        print(msg)


def detail(msg: str) -> None:
    """Print only at verbose level."""
    if _verbosity >= VERBOSE:
        print(msg)


def _to_stderr(msg: str) -> None:
    # Keep the two streams in order when stdout is a pipe (block-buffered).
    # Either stream may be None (pythonw.exe, `>&-`); print() is then a no-op.
    stdout = sys.stdout
    if stdout is not None:
        try:
            stdout.flush()
        except (OSError, ValueError):
            pass
    print(msg, file=sys.stderr)


def error(msg: str) -> None:
    """Always print to stderr."""
    _to_stderr(msg)


def warn(msg: str) -> None:
    """Always print to stderr: something the user should know even under --quiet."""
    _to_stderr(msg)


def success(msg: str) -> None:
    """Always print to stdout."""
    print(msg)


def prompt(msg: str) -> None:
    """Always print to stdout: text the user must read before answering a question."""
    print(msg)
