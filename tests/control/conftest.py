from collections.abc import Iterator

import pytest

from ..support.daemon import Daemon, start_daemon


@pytest.fixture(scope="module")
def daemon() -> Iterator[Daemon]:
    yield from start_daemon()
