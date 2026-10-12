"""The control plane's unit tests never read the user's own configuration."""

from collections.abc import Iterator

import pytest

from handler_harness import catalog


@pytest.fixture(autouse=True)
def _default_toolbox(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The default toolbox (read only), in place of `~/.config/handler-ai/toolbox`."""
    monkeypatch.setenv("HANDLER_TOOLBOX_DIR", str(catalog.DEFAULT_TOOLBOX))
    yield
