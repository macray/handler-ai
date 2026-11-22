from collections.abc import Iterator

import pytest
from playwright.sync_api import Browser, expect

from .browser import browser_server

# How long a page may take to show what a test expects. The full suite runs in parallel: a sandbox
# start or an image query then takes seconds more than alone, and Playwright's 5 s failed tests
# that nothing was wrong with. A wait ends as soon as what it expects holds: a passing test is no
# slower; only a real failure takes this long to be said.
EXPECT_TIMEOUT_MS = 20_000
expect.set_options(timeout=EXPECT_TIMEOUT_MS)


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    yield from browser_server()
