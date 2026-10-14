import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ccsession.export.session_discovery import get_parent_claude_pid


@pytest.mark.skipif(os.name == "nt", reason="ps(1) is not available on Windows")
def test_detects_parent_whose_command_line_mentions_claude():
    """The parent's command line is read with ps(1); the keyword used must be
    valid on both GNU and BSD ps, or detection silently fails on macOS."""
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)", "claude-marker"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(0.3)  # let the child exec so ps sees its argv
        with patch("ccsession.export.session_discovery.os.getppid", return_value=child.pid):
            assert get_parent_claude_pid() == child.pid
    finally:
        child.kill()
        child.wait()
