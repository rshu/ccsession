"""Verbosity-aware output functions for the ccsession CLI."""
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


def info(msg: str) -> None:
    """Print at normal and verbose levels."""
    if _verbosity >= NORMAL:
        print(msg)


def detail(msg: str) -> None:
    """Print only at verbose level."""
    if _verbosity >= VERBOSE:
        print(msg)


def error(msg: str) -> None:
    """Always print to stderr."""
    print(msg, file=sys.stderr)


def success(msg: str) -> None:
    """Always print to stdout."""
    print(msg)
