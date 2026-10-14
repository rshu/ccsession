"""Shared pytest configuration."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_claude_config_dir(monkeypatch):
    """Tests reason about ~/.claude unless they set CLAUDE_CONFIG_DIR themselves.

    CLAUDE_CODE_PROJECT_DIR_NAME is cleared too: Claude Code (and ccsession) honour
    it whenever CLAUDE_CONFIG_DIR is set, so a developer's own value would leak in."""
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_PROJECT_DIR_NAME", raising=False)
