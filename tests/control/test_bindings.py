"""G.2, D.15 through a real handlerd: bindings created, edited, renamed and deleted through the API,
their secret values going to the secret store (never read back), a hand-written reference kept,
and a connection in use neither renamed nor deleted. The addon has no image: no podman needed."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from ..support.daemon import Daemon, start_daemon

MANIFEST = """
apiVersion = "handler.tool/v1"
name = "shop"
description = "a shop"
egress = ["shop.example.com:443"]
[settings.store]
env = "SHOP_STORE"
required = true
description = "the store's domain"
[secretSlots.token]
env = "SHOP_TOKEN"
required = true
[secretSlots.extra]
env = "SHOP_EXTRA"
"""
# a tool with a connection check, never built here: its check cannot run yet
CHECKED = """
apiVersion = "handler.tool/v1"
name = "checked"
image = "localhost/handler-ai-test-checked"
commands = ["checked"]
connectionCheck = ["checked", "--ping"]
[settings.site]
env = "CHECKED_SITE"
"""
CONNECT = "# Shop — the token an agent needs\n\nMake one in the shop's admin.\n"
TOKEN = "shop-token-not-a-real-one"


@pytest.fixture(scope="module")
def daemon(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Daemon]:
    addons = tmp_path_factory.mktemp("addons")
    (addons / "shop").mkdir()
    (addons / "shop" / "tool.toml").write_text(MANIFEST)
    (addons / "shop" / "CONNECT.md").write_text(CONNECT)
    (addons / "checked").mkdir()
    (addons / "checked" / "tool.toml").write_text(CHECKED)
    (addons / "checked" / "Containerfile").write_text("FROM scratch\n")
    yield from start_daemon(extra_env={"HANDLER_TOOLS_DIR": str(addons)})


@pytest.mark.rule("tool.its-connect-file-is-shown-at-connect")
def test_a_tool_s_connect_file_is_given_with_it(daemon: Daemon) -> None:
    with daemon.http() as c:
        tools = {a["name"]: a for a in c.get("/v1/addons").json()}
    assert tools["shop"]["connect"] == CONNECT  # as written, for the Connect form
    assert tools["app-builder"].get("connect") is None  # a tool without one


def bindings_dir(daemon: Daemon) -> Path:
    return daemon.config_dir / "connections"


@pytest.mark.rule("connection.fills-its-tool-s-slots")
def test_addon_slots_are_described(daemon: Daemon) -> None:
    with daemon.http() as c:
        [shop] = [a for a in c.get("/v1/addons").json() if a["name"] == "shop"]
    assert shop["settings"] == [
        {"name": "store", "required": True, "description": "the store's domain"}
    ]
    assert [s["name"] for s in shop["secretSlots"]] == ["extra", "token"]
    assert shop["egress"] == ["shop.example.com:443"]


@pytest.mark.rule(
    "access.a-secret-given-goes-to-the-store",
    "access.its-secrets-follow-it",
    "access.in-use-is-never-renamed",
    "secrets.never-read-back",
    "secrets.every-one-is-listed",
    "secrets.kept-for-you-only",
    "connection.fills-its-tool-s-slots",
)
def test_bindings_are_written_through_the_api(daemon: Daemon) -> None:
    body = {
        "name": "dev-shop",
        "addon": "shop",
        "description": "the dev store",
        "settings": {"store": "dev.example.com"},
        "secrets": {"token": TOKEN},
    }
    with daemon.http() as c:
        missing = body | {"secrets": {}}
        assert c.post("/v1/bindings", json=missing).status_code == 422  # required token
        assert c.post("/v1/bindings", json=body | {"settings": {"nope": "x"}}).status_code == 422
        r = c.post("/v1/bindings", json=body)
        assert r.status_code == 201, r.text
        info = r.json()
        assert TOKEN not in r.text
        assert (info["secrets"], info["handWritten"], info.get("error")) == (["token"], [], None)
        assert c.post("/v1/bindings", json=body).status_code == 409
        path = bindings_dir(daemon) / "dev-shop.toml"
        assert TOKEN not in path.read_text() and path.stat().st_mode & 0o777 == 0o600
        [secret] = [s for s in c.get("/v1/secrets").json() if s["path"].startswith("connections/")]
        assert secret["path"] == "connections/dev-shop/token"
        assert (secret["usedBy"], secret["hosts"]) == (
            ["connections/dev-shop"],
            ["shop.example.com:443"],
        )

        # a hand-written reference is kept; renaming moves the store's secrets
        text = path.read_text().replace(
            "[secrets]", '[secrets]\nextra = { env = "SHOP_EXTRA_SOURCE" }'
        )
        path.write_text(text)
        edit = body | {"name": "shop-dev", "secrets": {}, "settings": {"store": "x.example.com"}}
        r = c.put("/v1/bindings/dev-shop", json=edit)
        assert r.status_code == 200, r.text
        assert r.json()["handWritten"] == ["extra"] and r.json()["secrets"] == ["extra", "token"]
        assert not path.exists()
        renamed = (bindings_dir(daemon) / "shop-dev.toml").read_text()
        assert "SHOP_EXTRA_SOURCE" in renamed and "connections/shop-dev/token" in renamed
        paths = [s["path"] for s in c.get("/v1/secrets").json()]
        assert "connections/shop-dev/token" in paths and "connections/dev-shop/token" not in paths
        assert c.put("/v1/bindings/shop-dev", json=edit | {"addon": "other"}).status_code == 422

        # in use by an ad-hoc agent: neither renamed nor deleted
        uses = [{"addon": "shop", "binding": "shop-dev"}]
        ad_hoc = daemon.create_ad_hoc("fake", daemon.make_scope(), addons=uses)
        [listed] = [b for b in c.get("/v1/bindings").json() if b["name"] == "shop-dev"]
        assert listed["usedBy"] == [f"ad-hoc/{ad_hoc['id']}"]
        assert c.put("/v1/bindings/shop-dev", json=edit | {"name": "again"}).status_code == 409
        assert c.delete("/v1/bindings/shop-dev").status_code == 409
        assert c.delete(f"/v1/agents/{ad_hoc['id']}").status_code == 204

        assert c.delete("/v1/bindings/shop-dev").status_code == 204
        assert c.delete("/v1/bindings/shop-dev").status_code == 404
        assert not [s for s in c.get("/v1/secrets").json() if s["path"].startswith("connections/")]


def test_a_check_that_cannot_run_says_why(daemon: Daemon) -> None:
    """G.2, D.15: 409 when it cannot run (the connection invalid, its tool without a check or
    not ready), 404 for no such connection; nothing is kept."""
    folder = bindings_dir(daemon)
    folder.mkdir(exist_ok=True)
    (folder / "no-check.toml").write_text(
        'apiVersion = "handler.connection/v1"\ntool = "shop"\n'
        'settings = { store = "a.example.com" }\nsecrets = { token = { env = "NOPE" } }\n'
    )
    (folder / "unbuilt.toml").write_text(
        'apiVersion = "handler.connection/v1"\ntool = "checked"\nsettings = { site = "x" }\n'
    )
    (folder / "broken.toml").write_text('apiVersion = "handler.connection/v1"\ntool = "shop"\n')
    with daemon.http() as c:
        [checked] = [a for a in c.get("/v1/addons").json() if a["name"] == "checked"]
        assert checked["connectionCheck"] == ["checked", "--ping"]
        refused = {
            name: c.post(f"/v1/bindings/{name}/check")
            for name in ("no-check", "unbuilt", "broken", "nope")
        }
        assert {n: r.status_code for n, r in refused.items()} == {
            "no-check": 409,
            "unbuilt": 409,
            "broken": 409,
            "nope": 404,
        }
        assert refused["no-check"].json()["title"] == "no connection check"
        assert refused["unbuilt"].json()["title"] == "tool not ready"
        assert refused["broken"].json()["title"] == "invalid connection"
        assert all(not b.get("checked") for b in c.get("/v1/bindings").json())
    for name in ("no-check", "unbuilt", "broken"):
        (folder / f"{name}.toml").unlink()
