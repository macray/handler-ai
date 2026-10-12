from collections.abc import Iterator

import pytest
from playwright.sync_api import Browser

from .browser import browser_server


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    yield from browser_server()
