"""D.14 through a real handlerd: secrets set, described and deleted through the API, never read
back, and resolved from a `{ secret = … }` reference."""

import pytest

from ..support.daemon import Daemon
from .test_model_access import PROVIDER

KEY = "providers/remote2/apiKey"
VALUE = "sk-test-not-a-real-key"


@pytest.mark.rule(
    "access.its-status-says-what-is-missing",
    "secrets.never-read-back",
    "secrets.set-by-their-owner",
    "secrets.kept-for-you-only",
)
def test_secrets(daemon: Daemon) -> None:
    provider = daemon.providers_dir / "remote2.toml"
    provider.write_text(f'apiKey = {{ secret = "{KEY}" }}\n' + PROVIDER)
    with daemon.http() as c:
        status = {p["name"]: p for p in c.get("/v1/providers").json()}["remote2"]
        assert (
            status["status"] == "incomplete"
            and f"handler secret set {KEY}" in status["problems"][0]
        )

        body = {"value": VALUE, "description": "a key"}
        r = c.put(f"/v1/secrets/{KEY}", json=body)
        assert r.status_code == 200, r.text
        assert r.json()["usedBy"] == ["providers/remote2"] and VALUE not in r.text
        listed = c.get("/v1/secrets")
        assert VALUE not in listed.text
        [info] = [s for s in listed.json() if s["path"] == KEY]
        assert info["description"] == "a key"
        status = {p["name"]: p for p in c.get("/v1/providers").json()}["remote2"]
        assert status["status"] == "ready"

        assert c.delete(f"/v1/secrets/{KEY}").status_code == 409  # still referenced
        assert c.delete("/v1/secrets/providers").status_code == 409  # nor anything under it
        provider.unlink()
        assert c.delete(f"/v1/secrets/{KEY}").status_code == 204
        assert c.delete(f"/v1/secrets/{KEY}").status_code == 404

        assert c.put("/v1/secrets/a/.hidden", json={"value": "x"}).status_code == 400
        assert c.put("/v1/secrets/apps/x/TOKEN", json={"value": "x"}).status_code == 409
        assert c.put("/v1/secrets/a/b", json={"value": "two\nlines"}).status_code == 422
    assert (daemon.data_dir / "secrets.json").stat().st_mode & 0o777 == 0o600


@pytest.mark.rule("secrets.never-read-back", "secrets.every-one-is-listed")
def test_every_secret_and_how_agents_get_it(daemon: Daemon) -> None:
    """D.14, E3: the store's secrets and those kept elsewhere, each with what it belongs to, the
    agents that get it, and how: handler adds it to their requests to its hosts, or they read it."""
    (daemon.providers_dir / "keyed.toml").write_text(
        'apiKey = { secret = "providers/keyed/apiKey" }\n' + PROVIDER
    )
    (daemon.providers_dir / "byenv.toml").write_text(
        'apiKey = { env = "HANDLER_TEST_UNSET_KEY" }\n' + PROVIDER
    )
    scope = daemon.make_scope()
    daemon.create_ad_hoc(None, scope, provider="keyed", harness="pi", name="keyed-agent")
    with daemon.http() as c:
        assert c.put("/v1/secrets/providers/keyed/apiKey", json={"value": VALUE}).status_code == 200
        assert c.put("/v1/secrets/spare/one", json={"value": "x"}).status_code == 200
        listed = c.get("/v1/secrets")
        assert VALUE not in listed.text
        rows = {s["path"]: s for s in listed.json()}
    keyed = rows["providers/keyed/apiKey"]
    assert (keyed["source"], keyed["hasValue"], keyed["usedBy"]) == (
        "secret",
        True,
        ["providers/keyed"],
    )
    assert (keyed["agents"], keyed["hosts"], keyed.get("visible")) == (
        ["keyed-agent"],
        ["api.example.com:443"],
        None,
    )
    byenv = rows["providers/byenv/apiKey"]  # kept elsewhere: listed under its owner's path
    assert (byenv["source"], byenv["hasValue"], byenv.get("createdAt")) == ("env", False, None)
    spare = rows["spare/one"]  # nothing uses it
    assert (spare["usedBy"], spare["agents"]) == ([], [])
