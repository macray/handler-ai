"""The shopify addon against a real store (opt-in): a Claude Code agent with a shopify binding,
filtered network **enforced** with only the harness's and the addon's egress, lists the store's
themes. Proves the addon's egress list is complete (docs/dev/design/addons.md).

    HANDLER_TEST_SHOPIFY_STORE=my-dev-shop.myshopify.com
    HANDLER_TEST_SHOPIFY_THEME_TOKEN=shptka_…  (Theme Access, addons/shopify/PROVISIONING.md)

Needs the claude-code and shopify addon images (`handler image rebuild addon:shopify`); no Claude
login (the agent is only started, the CLI runs next to it). The addon is the registry's:
HANDLER_TEST_REGISTRY, a checkout of it.
"""

import os
import subprocess
import time
from collections.abc import Iterator

import pytest

from handler_control import runtime

from ..support import dev_env
from ..support.daemon import Daemon, start_daemon
from ..support.sources import REGISTRY, requires_registry

STORE = os.environ.get("HANDLER_TEST_SHOPIFY_STORE")
TOKEN = os.environ.get("HANDLER_TEST_SHOPIFY_THEME_TOKEN")

pytestmark = [
    requires_registry,
    pytest.mark.skipif(
        not (STORE and TOKEN), reason="HANDLER_TEST_SHOPIFY_STORE/_THEME_TOKEN not set"
    ),
    pytest.mark.skipif(
        not (
            runtime.exists("localhost/handler-ai-claude-code:latest")
            and runtime.exists("localhost/handler-ai-addon-shopify:latest")
        ),
        reason="claude-code or shopify addon image not built",
    ),
    pytest.mark.timeout(dev_env.IMAGE_TIMEOUT),
]


@pytest.fixture(scope="module")
def daemon() -> Iterator[Daemon]:
    env = {"HANDLER_TEST_SHOPIFY_THEME_TOKEN": TOKEN or ""}
    assert REGISTRY is not None
    yield from start_daemon(extra_env=env, source=REGISTRY, addons=("shopify",))


def test_theme_list_with_enforced_egress(daemon: Daemon) -> None:
    root = daemon.config_dir / "bindings"
    root.mkdir(exist_ok=True)
    (root / "shop.toml").write_text(
        'apiVersion = "handler.binding/v1"\naddon = "shopify"\n'
        f'settings = {{ store = "{STORE}" }}\n'
        'secrets = { theme_token = { env = "HANDLER_TEST_SHOPIFY_THEME_TOKEN" } }\n'
    )
    ad_hoc = daemon.create_ad_hoc(
        "claude-code", daemon.make_scope(), bindings=["shop"], egress="enforce"
    )
    assert ad_hoc["network"] == "filtered" and ad_hoc["egress"] == "enforce"
    client = daemon.connect(ad_hoc["acpUrl"])
    try:
        container = agent_container(ad_hoc["id"])
        r = subprocess.run(
            ["podman", "exec", "-w", "/tmp", container, "shopify", "theme", "list"],
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert "live" in r.stdout  # every store has a live theme
    finally:
        client.close()


def agent_container(agent_id: str, timeout: float = 60) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        names = subprocess.run(
            [
                "podman",
                "ps",
                "--format",
                "{{.Names}}",
                "--filter",
                f"label=handler.agent={agent_id}",
            ],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.split()
        if agents := [n for n in names if not n.endswith("-proxy")]:
            return agents[0]
        time.sleep(0.2)
    raise TimeoutError(agent_id)
