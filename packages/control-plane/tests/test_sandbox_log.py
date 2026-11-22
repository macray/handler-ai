"""A sandbox's stderr in handlerd's log (sandbox_process.log_line)."""

import logging

import pytest

from handler_control.sandbox_process import LOGGED_CHARS, log_line


@pytest.mark.rule("runtime.its-stderr-is-logged-cut")
def test_a_long_stderr_line_is_cut_in_the_log(caplog: pytest.LogCaptureFixture) -> None:
    """A harness logging whole ACP messages (every skill's description, kilobytes a line) gets
    its line cut, its length said; an error line is logged whole; an egress event is not logged.

    If this fails: `handler daemon log`, where the docs send you, buries the error under payloads."""
    events: list[dict[str, str]] = []
    with caplog.at_level(logging.INFO, logger="handler.sandbox"):
        log_line("x" * 5000, "s_1", events.append)
        log_line("Error: 401 OAuth access token is invalid", "s_1", events.append)
        log_line('handler-egress {"host": "pypi.org:443"}', "s_1", events.append)
    cut, error = (r.getMessage() for r in caplog.records)
    assert cut == f"[s_1] {'x' * LOGGED_CHARS}… (5000 characters)"
    assert error == "[s_1] Error: 401 OAuth access token is invalid"
    assert events == [{"host": "pypi.org:443"}]
