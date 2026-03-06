"""Tests for ccsession.output module."""
from __future__ import annotations

import sys
from io import StringIO

import pytest

from ccsession.output import info, detail, error, success, set_verbosity, get_verbosity, QUIET, NORMAL, VERBOSE


@pytest.fixture(autouse=True)
def reset_verbosity():
    """Reset verbosity to NORMAL before each test."""
    set_verbosity(NORMAL)
    yield
    set_verbosity(NORMAL)


class TestVerbosityLevel:
    def test_default_is_normal(self):
        set_verbosity(NORMAL)
        assert get_verbosity() == NORMAL

    def test_set_quiet(self):
        set_verbosity(QUIET)
        assert get_verbosity() == QUIET

    def test_set_verbose(self):
        set_verbosity(VERBOSE)
        assert get_verbosity() == VERBOSE


class TestInfoFunction:
    def test_prints_at_normal(self, capsys):
        set_verbosity(NORMAL)
        info("hello")
        assert capsys.readouterr().out == "hello\n"

    def test_prints_at_verbose(self, capsys):
        set_verbosity(VERBOSE)
        info("hello")
        assert capsys.readouterr().out == "hello\n"

    def test_suppressed_at_quiet(self, capsys):
        set_verbosity(QUIET)
        info("hello")
        assert capsys.readouterr().out == ""


class TestDetailFunction:
    def test_suppressed_at_normal(self, capsys):
        set_verbosity(NORMAL)
        detail("details")
        assert capsys.readouterr().out == ""

    def test_prints_at_verbose(self, capsys):
        set_verbosity(VERBOSE)
        detail("details")
        assert capsys.readouterr().out == "details\n"

    def test_suppressed_at_quiet(self, capsys):
        set_verbosity(QUIET)
        detail("details")
        assert capsys.readouterr().out == ""


class TestErrorFunction:
    def test_always_prints_at_normal(self, capsys):
        set_verbosity(NORMAL)
        error("bad")
        assert capsys.readouterr().err == "bad\n"

    def test_always_prints_at_quiet(self, capsys):
        set_verbosity(QUIET)
        error("bad")
        assert capsys.readouterr().err == "bad\n"

    def test_prints_to_stderr(self, capsys):
        error("bad")
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == "bad\n"


class TestSuccessFunction:
    def test_always_prints_at_normal(self, capsys):
        set_verbosity(NORMAL)
        success("done")
        assert capsys.readouterr().out == "done\n"

    def test_always_prints_at_quiet(self, capsys):
        set_verbosity(QUIET)
        success("done")
        assert capsys.readouterr().out == "done\n"
