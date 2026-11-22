"""The web UI in a real browser, against a real handlerd and the fake agent: one handlerd per test
file, so that the files run in parallel.

The browser runs in Playwright's container image (`--network host`) as a remote browser server,
so no browser or system libraries are needed on the host."""

from collections.abc import Iterator

import pytest
from playwright.sync_api import Browser, Page

from ...support.daemon import Daemon, fake_terminal, start_daemon


@pytest.fixture(scope="module")
def daemon(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Daemon]:
    """With a stand-in for the desktop's terminal (an account's login window, D.9)."""
    terminal = fake_terminal(tmp_path_factory.mktemp("terminal"), typed="typed-in-the-window")
    yield from start_daemon(extra_env={"HANDLER_TERMINAL": str(terminal)})


@pytest.fixture
def page(browser: Browser, daemon: Daemon) -> Iterator[Page]:
    context = browser.new_context()
    page = context.new_page()
    page.goto(daemon.ui_url())
    yield page
    context.close()
