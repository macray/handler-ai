from collections.abc import Iterator

import pytest

from ..support.daemon import Daemon, start_daemon


@pytest.fixture(scope="module")
def daemon() -> Iterator[Daemon]:
    yield from start_daemon(
        extra_env={"HANDLER_SESSION_IDLE_TIMEOUT": "2", "HANDLER_SESSION_MAX_ATTACH": "2"}
    )
