"""The shopify addon against a real store (opt-in): a Claude Code agent with a shopify binding,
filtered network **enforced** with only the harness's and the addon's egress, lists the store's
themes. Proves the addon's egress list is complete (addons design).

    HANDLER_TEST_SHOPIFY_STORE=my-dev-shop.myshopify.com
    HANDLER_TEST_SHOPIFY_THEME_TOKEN=shptka_…  (Theme Access, addons/shopify/PROVISIONING.md)

Needs the claude-code and toolbox images (the test's daemon builds the addon, G.4); no Claude
login (the agent is only started, the CLI runs next to it). The tool is the private registry's:
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
    requires_registry("tools/shopify"),
    pytest.mark.skipif(
        not (STORE and TOKEN), reason="HANDLER_TEST_SHOPIFY_STORE/_THEME_TOKEN not set"
    ),
    pytest.mark.skipif(
        not (
            runtime.exists("localhost/handler-ai-claude-code:latest")
            and runtime.exists("localhost/handler-ai-toolbox:latest")
        ),
        reason="claude-code or toolbox image not built",
    ),
    pytest.mark.timeout(dev_env.IMAGE_TIMEOUT),
]


@pytest.fixture(scope="module")
def daemon() -> Iterator[Daemon]:
    env = {"HANDLER_TEST_SHOPIFY_THEME_TOKEN": TOKEN or ""}
    assert REGISTRY is not None
    for daemon in start_daemon(extra_env=env, source=REGISTRY, addons=("shopify",)):
        with daemon.http() as c:  # its folder is the test daemon's own: built here
            build_id = c.post("/v1/addons/shopify/rebuild").json()["id"]
            while (build := c.get(f"/v1/builds/{build_id}").json())["state"] == "running":
                time.sleep(1)
        assert build["state"] == "succeeded", build.get("error")
        yield daemon


def test_theme_list_with_enforced_egress(daemon: Daemon) -> None:
    root = daemon.config_dir / "connections"
    root.mkdir(exist_ok=True)
    (root / "shop.toml").write_text(
        'apiVersion = "handler.connection/v1"\ntool = "shopify"\n'
        f'settings = {{ store = "{STORE}" }}\n'
        'secrets = { theme_token = { env = "HANDLER_TEST_SHOPIFY_THEME_TOKEN" } }\n'
    )
    ad_hoc = daemon.create_ad_hoc(
        "claude-code",
        daemon.make_scope(),
        addons=[{"addon": "shopify", "binding": "shop"}],
        egress="enforce",
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
