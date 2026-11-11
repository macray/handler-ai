"""Every test run: on macOS, temporary files go to /tmp's real path (/tmp is a link), as a socket's
path there is 104 bytes at most and the default temporary folder (/var/folders/…/T/) leaves too few
of them."""

import os
import sys
import tempfile

import pytest

if sys.platform == "darwin":
    os.environ["TMPDIR"] = tempfile.tempdir = os.path.realpath("/tmp")


def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]) -> None:
    """A failing test names the rules it proves (`pytest.mark.rule`): what its failure breaks."""
    if call.when == "call" and call.excinfo is not None:
        rules = [name for mark in item.iter_markers("rule") for name in mark.args]
        if rules:
            item.add_report_section("call", "rules", "breaks: " + ", ".join(rules))


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter) -> None:
    """After sandbox tests, where they ran and what each runtime was tested for
    (tests/support/place.py): a skip of what it does not list is this place, not a fault."""
    reports = [r for found in terminalreporter.stats.values() for r in found]
    if not any(getattr(r, "nodeid", "").startswith("tests/sandbox/") for r in reports):
        return
    from tests.support import runtimes  # noqa: PLC0415 — probes the runtimes: only when needed

    terminalreporter.section("where the sandbox tests ran")
    for line in runtimes.summary():
        terminalreporter.line(line)
