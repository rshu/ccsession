"""Exceptions ccsession raises for problems in user-supplied data."""
from __future__ import annotations


class CCSessionError(Exception):
    """Base class for errors the CLI reports without a traceback."""


class InvalidExportError(CCSessionError):
    """An export directory or its manifest is missing, malformed, or unsafe to import."""
