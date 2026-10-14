"""Shared pytest configuration."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_claude_config_dir(monkeypatch):
    """Tests reason about ~/.claude unless they set CLAUDE_CONFIG_DIR themselves."""
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
