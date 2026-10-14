"""Tests for CLI verbosity flags and export mode flag.

Subprocess runs are isolated with a throwaway ``CLAUDE_CONFIG_DIR`` and working
directory: the suite must never export the developer's own live sessions.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from ccsession.output import get_verbosity, set_verbosity, QUIET, NORMAL, VERBOSE

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "tests" / "fixtures" / "claude-2.1.287"
FIXTURE_SID = "7f6738b0-d2cb-44ae-a806-09860af58e1f"


@pytest.fixture(autouse=True)
def _reset_verbosity():
    set_verbosity(NORMAL)
    yield
    set_verbosity(NORMAL)


@pytest.fixture
def isolated(tmp_path):
    """(env, cwd) for a subprocess that cannot see ~/.claude or the repository."""
    cfg = tmp_path / "cfg"
    (cfg / "projects").mkdir(parents=True)
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CODE_PROJECT_DIR_NAME"}
    env.update(CLAUDE_CONFIG_DIR=str(cfg), PYTHONPATH=str(REPO))
    return env, cwd


def _run(args, isolated):
    env, cwd = isolated
    return subprocess.run([sys.executable, "-m", "ccsession", *args], capture_output=True, text=True,
                          env=env, cwd=cwd)


class TestVerbosityFlags:
    def test_quiet_and_verbose_mutually_exclusive(self, isolated):
        """argparse should reject --quiet and --verbose together."""
        result = _run(["--quiet", "--verbose", "export"], isolated)
        assert result.returncode != 0
        assert "not allowed with" in result.stderr

    def test_quiet_flag_accepted(self, isolated):
        """--quiet should be accepted (will fail at session discovery, not parsing)."""
        result = _run(["--quiet", "export"], isolated)
        assert "unrecognized arguments" not in result.stderr
        assert result.returncode == 1 and "No Claude Code sessions found" in result.stderr

    def test_verbose_flag_accepted(self, isolated):
        """--verbose should be accepted (will fail at session discovery, not parsing)."""
        result = _run(["--verbose", "export"], isolated)
        assert "unrecognized arguments" not in result.stderr

    def test_subprocess_runs_never_export_anything(self, isolated):
        env, cwd = isolated
        before = sorted(p.name for p in (REPO / ".claude-sessions").iterdir()) if (REPO / ".claude-sessions").is_dir() else []

        for mode in ([], ["--mode", "classic"]):
            result = _run(["export", *mode], isolated)
            assert result.returncode == 1, result.stderr
            assert "No Claude Code sessions found" in result.stderr

        assert not (cwd / ".claude-sessions").exists()
        after = sorted(p.name for p in (REPO / ".claude-sessions").iterdir()) if (REPO / ".claude-sessions").is_dir() else []
        assert after == before, "a subprocess test wrote an export into the repository"

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
    def test_mode_portable_accepted(self, isolated):
        """--mode portable should be accepted."""
        result = _run(["export", "--mode", "portable"], isolated)
        assert "unrecognized arguments" not in result.stderr
        assert "invalid choice" not in result.stderr

    def test_mode_classic_accepted(self, isolated):
        """--mode classic should be accepted."""
        result = _run(["export", "--mode", "classic"], isolated)
        assert "unrecognized arguments" not in result.stderr
        assert "invalid choice" not in result.stderr

    def test_mode_invalid_rejected(self, isolated):
        """--mode invalid should be rejected."""
        result = _run(["export", "--mode", "invalid"], isolated)
        assert result.returncode != 0
        assert "invalid choice" in result.stderr

    def test_default_mode_is_portable(self):
        """Default mode should be portable."""
        from ccsession.cli import main

        with patch('sys.argv', ['ccsession', 'export']):
            with patch('ccsession.cli.cmd_export') as mock:
                mock.return_value = 0
                main()
                args = mock.call_args[0][0]
                assert args.mode == 'portable'

    def test_old_flags_rejected(self, isolated):
        """Old flags --in-repo, --legacy, --format, --no-copy-to-cwd should be rejected."""
        for flag in ['--in-repo', '--legacy', '--no-copy-to-cwd']:
            result = _run(["export", flag], isolated)
            assert 'unrecognized arguments' in result.stderr, f"{flag} should be rejected"

        result = _run(["export", "--format", "md"], isolated)
        assert 'unrecognized arguments' in result.stderr, "--format should be rejected"


class TestExportNotFoundMessage:
    def test_not_found_message_names_the_configured_projects_root(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
        (tmp_path / "cfg" / "projects").mkdir(parents=True)
        from ccsession.cli import main
        assert main(["export", "--session-id", "00000000-0000-0000-0000-000000000000"]) == 1
        assert str(tmp_path / "cfg" / "projects") in capsys.readouterr().err


# ---------------------------------------------------------------------------
# --quiet means errors and the final result only, for every command
# ---------------------------------------------------------------------------

@pytest.fixture
def fixture_claude_dir(tmp_path, monkeypatch):
    claude = tmp_path / "source-claude"
    shutil.copytree(FIXTURE, claude)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    return claude


class TestQuietMode:
    def test_quiet_export_prints_only_the_success_line(self, tmp_path, fixture_claude_dir, capsys):
        from ccsession.cli import main

        rc = main(["--quiet", "export", "--session-id", FIXTURE_SID,
                   "--output-dir", str(tmp_path / "out"), "--export-name", "q"])

        assert rc == 0
        out = capsys.readouterr().out
        assert out.strip() == "✅ Export completed successfully!"
        assert (tmp_path / "out" / "q" / ".ccsession-manifest.json").is_file()

    def test_quiet_import_prints_only_the_completion_lines(self, tmp_path, fixture_claude_dir, capsys, monkeypatch):
        from ccsession.cli import main

        assert main(["--quiet", "export", "--session-id", FIXTURE_SID,
                     "--output-dir", str(tmp_path / "out"), "--export-name", "q"]) == 0
        capsys.readouterr()
        target = tmp_path / "target-claude"
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(target))
        project = tmp_path / "proj"
        project.mkdir()

        with patch("ccsession.importing.importer.check_version_compatibility", return_value=(True, None)):
            rc = main(["--quiet", "import", str(tmp_path / "out" / "q"), "--project-path", str(project),
                       "--non-interactive", "--skip-config"])

        assert rc == 0
        out = capsys.readouterr().out
        lines = [l for l in out.splitlines() if l.strip()]
        assert lines[0].strip() == "✅ Import complete!"
        assert any("claude --resume" in l for l in lines)
        assert len(lines) <= 4, out
        assert "Validating export" not in out and "Writing session files" not in out

    def test_quiet_restore_prints_only_the_result(self, tmp_path, monkeypatch, capsys):
        from ccsession.cli import main

        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        snapshot_dir = tmp_path / ".claude-session-imports" / "pre-import-snapshot"
        snapshot_dir.mkdir(parents=True)
        (snapshot_dir / "snapshot_info.json").write_text(json.dumps({
            "timestamp": "2026-01-06T12:00:00Z",
            "target_directory": str(tmp_path / ".claude" / "projects" / "-p"), "backup_exists": False}),
            encoding="utf-8")

        rc = main(["--quiet", "restore", "--restore", "--yes"])

        assert rc == 0
        assert capsys.readouterr().out.strip() == "✅ Restore complete!"

    def test_normal_export_still_reports_progress(self, tmp_path, fixture_claude_dir, capsys):
        from ccsession.cli import main

        main(["export", "--session-id", FIXTURE_SID, "--output-dir", str(tmp_path / "out"), "--export-name", "n"])

        out = capsys.readouterr().out
        assert "Export completed successfully" in out and "Writing trajectory.json" in out


class TestQuietWarnings:
    def test_quiet_export_still_warns_when_the_project_directory_is_gone(self, tmp_path, fixture_claude_dir, capsys, monkeypatch):
        """The fixture session's recorded project (/tmp/e2e/proj) does not exist here, so the
        export lands under the cwd; a --quiet user must still be told."""
        from ccsession.cli import main
        cwd = tmp_path / "cwd"
        cwd.mkdir()
        monkeypatch.chdir(cwd)

        rc = main(["--quiet", "export", "--session-id", FIXTURE_SID, "--export-name", "q"])

        assert rc == 0
        captured = capsys.readouterr()
        assert captured.out.strip() == "✅ Export completed successfully!"
        assert "does not exist" in captured.err and str(cwd) in captured.err


class TestStreamsAreConfiguredByMain:
    def test_a_strict_legacy_encoding_does_not_crash_the_cli(self, isolated):
        env, cwd = isolated
        env = {**env, "PYTHONIOENCODING": "cp1252"}
        result = subprocess.run([sys.executable, "-m", "ccsession", "export"], capture_output=True, env=env, cwd=cwd)

        assert result.returncode == 1
        assert b"Traceback" not in result.stderr and b"No Claude Code sessions found" in result.stderr
