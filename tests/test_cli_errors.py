"""run_command maps exceptions to exit codes and messages."""
from __future__ import annotations

import argparse

from ccsession.cli import run_command
from ccsession.errors import InvalidExportError


def _run(exc):
    def fn(_args):
        raise exc
    return run_command(fn, argparse.Namespace())


def test_invalid_export_is_reported_as_a_validation_failure(capsys):
    assert _run(InvalidExportError("manifest is bad")) == 1
    err = capsys.readouterr().err
    assert "Import validation failed" in err and "manifest is bad" in err


def test_a_broken_installation_is_not_blamed_on_the_export(capsys):
    """A missing module is a packaging problem; telling the user to re-export would mislead them."""
    assert _run(ModuleNotFoundError("No module named 'ccsession.export.exporter'")) == 1
    err = capsys.readouterr().err
    assert "Import validation failed" not in err
    assert "Unexpected error" in err and "Traceback" in err


def test_keyboard_interrupt_is_a_clean_cancel(capsys):
    assert _run(KeyboardInterrupt()) == 1
    assert "Cancelled" in capsys.readouterr().err
