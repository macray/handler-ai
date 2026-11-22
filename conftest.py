"""Every test run: on macOS, temporary files go to /tmp's real path (/tmp is a link), as a socket's
path there is 104 bytes at most and the default temporary folder (/var/folders/…/T/) leaves too few
of them. The property tests (Hypothesis) run with the profile HYPOTHESIS_PROFILE names: "ci" by
default, "explore" for the daily search (scripts/ci.sh)."""

import fcntl
import os
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import IO

import pytest
from hypothesis import HealthCheck, is_hypothesis_test, settings
from hypothesis.database import DirectoryBasedExampleDatabase

if sys.platform == "darwin":
    os.environ["TMPDIR"] = tempfile.tempdir = os.path.realpath("/tmp")

# "ci": the same examples on every run (a seed from each test's own code), so that a red run is
# red again until fixed and a green one says the change kept them; no deadline: under the parallel
# suite an example may take seconds, and a hang is pytest-timeout's. 300 examples a test.
settings.register_profile("ci", derandomize=True, deadline=None, max_examples=300)
# "explore": new random examples, many more, to find what the fixed ones miss. A failing example
# is kept (its database: scripts/ci.sh's, shared by the repository's checkouts) and tried first by
# the next search, until fixed; once fixed, it goes on the test as an `@example`, which "ci" runs.
_STATE = os.environ.get("HANDLER_CI_STATE")
settings.register_profile(
    "explore",
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],  # it runs beside the whole suite
    max_examples=20_000,
    **({"database": DirectoryBasedExampleDatabase(Path(_STATE) / "hypothesis")} if _STATE else {}),
)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "ci"))


SHARED_SCOPES = ("class", "module", "package")
# one machine's podman (its images by name) is shared by every test run on it: two at once (ci.sh's
# two Pythons, two checkouts) would rebuild or remove the same image under each other
SHARED_IMAGES_LOCK = os.path.join(tempfile.gettempdir(), "handler-tests-shared-images.lock")


_held: dict[str, IO[str]] = {}  # the lock, by the file whose tests hold it


@pytest.hookimpl(wrapper=True)
def pytest_runtest_protocol(item: pytest.Item, nextitem: pytest.Item | None) -> Iterator[None]:
    """A file marked `shared_images` (its tests build, replace or remove an image by a name other
    runs use too) runs while no other run on this machine runs one: from its first test (its
    module fixtures' setup) to its last (their teardown)."""
    if item.get_closest_marker("shared_images") is None:
        return (yield)
    path = item.nodeid.split("::")[0]
    if path not in _held:
        _held[path] = open(SHARED_IMAGES_LOCK, "w")  # noqa: SIM115 — held across tests
        fcntl.flock(_held[path], fcntl.LOCK_EX)
    try:
        return (yield)
    finally:
        if nextitem is None or nextitem.nodeid.split("::")[0] != path:
            _held.pop(path).close()  # closing releases it


@pytest.hookimpl(tryfirst=True)  # before xdist's, which reads the groups
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """How the parallel run (`-n auto --dist loadgroup`) places the tests: a file whose tests share
    a fixture (a module's handlerd, its browser) stays on one worker, in its order; any other
    file's tests spread over every worker, each on its own. The property tests carry the marker
    `property`: the daily search runs them alone."""
    shared: set[str] = set()
    for item in items:
        info = getattr(item, "_fixtureinfo", None)
        defs = info.name2fixturedefs.values() if info else ()
        if any(d[-1].scope in SHARED_SCOPES for d in defs):
            shared.add(item.nodeid.split("::")[0])
        if is_hypothesis_test(getattr(item, "obj", None)):
            item.add_marker(pytest.mark.property)
    for item in items:
        path = item.nodeid.split("::")[0]
        if path in shared:
            item.add_marker(pytest.mark.xdist_group(path))


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
