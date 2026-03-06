"""Tests for CLI verbosity flags and export mode flag."""
from __future__ import annotations

import subprocess
import sys
from unittest.mock import patch

import pytest

from ccsession.output import get_verbosity, set_verbosity, QUIET, NORMAL, VERBOSE


class TestVerbosityFlags:
    def test_quiet_and_verbose_mutually_exclusive(self):
        """argparse should reject --quiet and --verbose together."""
        result = subprocess.run(
            [sys.executable, '-m', 'ccsession', '--quiet', '--verbose', 'export'],
            capture_output=True, text=True
        )
        assert result.returncode != 0
        assert 'not allowed with' in result.stderr

    def test_quiet_flag_accepted(self):
        """--quiet should be accepted (will fail at session discovery, not parsing)."""
        result = subprocess.run(
            [sys.executable, '-m', 'ccsession', '--quiet', 'export'],
            capture_output=True, text=True
        )
        assert 'unrecognized arguments' not in result.stderr

    def test_verbose_flag_accepted(self):
        """--verbose should be accepted (will fail at session discovery, not parsing)."""
        result = subprocess.run(
            [sys.executable, '-m', 'ccsession', '--verbose', 'export'],
            capture_output=True, text=True
        )
        assert 'unrecognized arguments' not in result.stderr

    def test_verbosity_propagated_to_output_module(self):
        """Verbosity should be set before command dispatch."""
        from ccsession.cli import main
        set_verbosity(NORMAL)

        with patch('sys.argv', ['ccsession', '--quiet', 'export']):
            with patch('ccsession.cli.cmd_export', side_effect=lambda args: 0) as mock:
                main()
                assert get_verbosity() == QUIET

        set_verbosity(NORMAL)

        with patch('sys.argv', ['ccsession', '--verbose', 'export']):
            with patch('ccsession.cli.cmd_export', side_effect=lambda args: 0) as mock:
                main()
                assert get_verbosity() == VERBOSE


class TestExportModeFlag:
    def test_mode_portable_accepted(self):
        """--mode portable should be accepted."""
        result = subprocess.run(
            [sys.executable, '-m', 'ccsession', 'export', '--mode', 'portable'],
            capture_output=True, text=True
        )
        assert 'unrecognized arguments' not in result.stderr
        assert 'invalid choice' not in result.stderr

    def test_mode_classic_accepted(self):
        """--mode classic should be accepted."""
        result = subprocess.run(
            [sys.executable, '-m', 'ccsession', 'export', '--mode', 'classic'],
            capture_output=True, text=True
        )
        assert 'unrecognized arguments' not in result.stderr
        assert 'invalid choice' not in result.stderr

    def test_mode_invalid_rejected(self):
        """--mode invalid should be rejected."""
        result = subprocess.run(
            [sys.executable, '-m', 'ccsession', 'export', '--mode', 'invalid'],
            capture_output=True, text=True
        )
        assert result.returncode != 0
        assert 'invalid choice' in result.stderr

    def test_default_mode_is_portable(self):
        """Default mode should be portable."""
        from ccsession.cli import main

        with patch('sys.argv', ['ccsession', 'export']):
            with patch('ccsession.cli.cmd_export') as mock:
                mock.return_value = 0
                main()
                args = mock.call_args[0][0]
                assert args.mode == 'portable'

    def test_old_flags_rejected(self):
        """Old flags --in-repo, --legacy, --format, --no-copy-to-cwd should be rejected."""
        for flag in ['--in-repo', '--legacy', '--no-copy-to-cwd']:
            result = subprocess.run(
                [sys.executable, '-m', 'ccsession', 'export', flag],
                capture_output=True, text=True
            )
            assert 'unrecognized arguments' in result.stderr, f"{flag} should be rejected"

        result = subprocess.run(
            [sys.executable, '-m', 'ccsession', 'export', '--format', 'md'],
            capture_output=True, text=True
        )
        assert 'unrecognized arguments' in result.stderr, "--format should be rejected"
