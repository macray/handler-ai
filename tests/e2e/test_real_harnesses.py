"""End to end, no credentials needed: handlerd → policy → handler-sandbox-podman → real harness
image.

Checks that P7 sets each harness's real bypass mode through the whole stack, and that the
agent runs in a container. Prompt turns with credentials: tests/harness (opt-in).
"""

from collections.abc import Iterator

import pytest

from handler_control import runtime
from handler_harness import catalog, images

from ..support.daemon import Daemon, start_daemon

VIBE_ACCOUNT = """apiVersion = "handler.account/v1"
harness = "vibe"
"""


@pytest.fixture(scope="module")
def daemon() -> Iterator[Daemon]:
    """Its accounts logged in with dummies (D.9): a token, and the file Vibe's sign-in leaves."""
    for d in start_daemon(extra_accounts={"e2e-vibe": VIBE_ACCOUNT}):
        with d.http() as c:
            token = {"token": "sk-ant-oat01-dummy"}  # the shape `claude setup-token` prints
            c.put("/v1/accounts/claude-code/login", json=token).raise_for_status()
            login = {"file": "MISTRAL_API_KEY=dummy-key-for-session-new\n"}
            c.put("/v1/accounts/e2e-vibe/login", json=login).raise_for_status()
        yield d


@pytest.mark.parametrize(
    ("account", "harness"), [("claude-code", "claude-code"), ("e2e-vibe", "vibe")]
)
def test_bypass_mode_applied_through_the_stack(daemon: Daemon, account: str, harness: str) -> None:
    descriptor = catalog.get(harness).descriptor
    latest = images.ref(descriptor.image, images.LATEST)
    if not runtime.exists(latest):
        pytest.skip(f"{latest} not built")
    scope = daemon.make_scope()
    ad_hoc = daemon.create_ad_hoc(account, scope, network="none")
    client = daemon.connect(ad_hoc["acpUrl"])
    try:
        client.initialize({"fs": {"readTextFile": True, "writeTextFile": True}, "terminal": True})
        session = client.new_session(str(scope))
    finally:
        client.close()
    expected = descriptor.permissions["bypass"].session_mode
    assert session["modes"]["currentModeId"] == expected
