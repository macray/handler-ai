"""Contract D conformance: the Control API of a real handlerd (docs/dev/contracts.md §D)."""

import time
from pathlib import Path

import httpx

from ..support.daemon import UI_ORIGIN, Daemon, require_echo_box


def test_auth(daemon: Daemon) -> None:
    with daemon.http(token=None) as c:
        r = c.get("/v1/accounts")
        assert r.status_code == 401
        assert r.headers["content-type"] == "application/problem+json"
    with daemon.http(token="wrong") as c:
        assert c.get("/v1/accounts").status_code == 401
    with daemon.http(Origin="http://evil.test") as c:
        assert c.get("/v1/accounts").status_code == 403
    with daemon.http(Origin=UI_ORIGIN) as c:
        assert c.get("/v1/accounts").status_code == 200


def test_listen_on_loopback_only(daemon: Daemon) -> None:
    assert daemon.base_url.startswith("http://127.0.0.1:")


def test_what_an_agent_runs_as(daemon: Daemon) -> None:
    """An account brings its harness; a provider needs one that speaks it; exactly one of them;
    a model of the provider's (E1)."""
    (daemon.providers_dir / "local.toml").write_text(
        'apiVersion = "handler.provider/v1"\n[endpoints]\nopenai-chat = "http://127.0.0.1:3000/v1"\n'
        '[[models]]\nid = "m1"\n'
    )
    scope = daemon.make_scope()
    on_account = daemon.create_ad_hoc("fake", scope, model="big-model")
    assert (on_account["model"]["harness"], on_account["model"]["model"]) == (
        "fake",
        "big-model",
    )
    on_provider = daemon.create_ad_hoc(None, scope, provider="local", harness="pi", name="pi")
    model = on_provider["model"]
    assert (model["harness"], model.get("account"), model["provider"]) == ("pi", None, "local")
    with daemon.http() as c:
        for wrong, detail in (
            ({"account": "nope"}, "no account 'nope'"),
            ({"account": "fake", "harness": "pi"}, "is for harness 'fake', not 'pi'"),
            ({"provider": "local", "harness": "claude-code"}, "accepts: anthropic"),
            ({"provider": "local", "harness": "pi", "model": "m9"}, "has no model 'm9'"),
        ):
            r = c.post("/v1/agents", json={"scope": str(scope), "model": wrong})
            assert r.status_code == 400 and detail in r.json()["detail"], (wrong, r.text)
        for invalid in (
            {},
            {"account": "fake", "provider": "local", "harness": "pi"},
            {"provider": "local"},
        ):
            r = c.post("/v1/agents", json={"scope": str(scope), "model": invalid})
            assert r.status_code == 422, invalid
        # one model, not a list of them (D.1)
        r = c.post("/v1/agents", json={"scope": str(scope), "models": [{"account": "fake"}]})
        assert r.status_code == 422


def test_harnesses(daemon: Daemon) -> None:
    with daemon.http() as c:
        names = {h["name"] for h in c.get("/v1/harnesses").json()}
    assert {"fake", "echo-box", "claude-code", "codex", "pi", "vibe"} <= names


def test_one_ad_hoc_agent_per_folder_and_name_starting_nothing(daemon: Daemon) -> None:
    """An ad-hoc agent is its folder and its name (D.1): whatever the settings, a second one
    with both is refused; another name is another agent."""
    scope = daemon.make_scope()
    first = daemon.create_ad_hoc("fake", scope)
    with daemon.http() as c:
        body = {"model": {"account": "fake"}, "scope": str(scope), "network": "none"}
        r = c.post("/v1/agents", json=body)
        assert r.status_code == 409 and r.json()["title"] == "agent exists"
        assert f"agent {first['id']} (unnamed) works in {scope}" in r.json()["detail"]
    other = daemon.create_ad_hoc("fake", scope, network="none", name="offline")
    assert first["id"] != other["id"] and other["network"] == "none"
    assert first["connections"] == []
    assert first["acpUrl"] == f"{daemon.ws_base}/v1/agents/{first['id']}/acp"


def test_run_errors(daemon: Daemon, tmp_path: Path) -> None:
    scope = daemon.make_scope()
    with daemon.http() as c:
        fake = {"account": "fake"}
        outside = c.post("/v1/agents", json={"model": fake, "scope": str(tmp_path)})
        assert outside.status_code == 403 and outside.json()["title"] == "scope not allowed"
        assert (
            c.post(
                "/v1/agents", json={"model": {"account": "nope"}, "scope": str(scope)}
            ).status_code
            == 400
        )
        assert c.post("/v1/agents", json={"scope": str(scope)}).status_code == 422
        assert c.get("/v1/agents/nope").status_code == 404


def test_list_inspect_delete(daemon: Daemon) -> None:
    ad_hoc = daemon.create_ad_hoc("fake", daemon.make_scope())
    with daemon.http() as c:
        assert ad_hoc["id"] in {r["id"] for r in c.get("/v1/agents").json()}
        assert c.get(f"/v1/agents/{ad_hoc['id']}").json()["scope"] == ad_hoc["scope"]
        assert c.delete(f"/v1/agents/{ad_hoc['id']}").status_code == 204
        assert c.get(f"/v1/agents/{ad_hoc['id']}").status_code == 404


def test_rename_agent(daemon: Daemon) -> None:
    ad_hoc = daemon.create_ad_hoc("fake", daemon.make_scope())
    assert ad_hoc.get("name") is None
    url = f"/v1/agents/{ad_hoc['id']}"
    body = {"model": {"account": "fake"}, "scope": ad_hoc["scope"], "confirmRisks": True}
    with daemon.http() as c:
        renamed = c.put(url, json=body | {"name": " my project "})
        assert renamed.json()["name"] == "my project"
        assert c.get(url).json()["name"] == "my project"
        # its folder and name are taken: by another one, refused (names without case)
        other = daemon.create_ad_hoc("fake", ad_hoc["scope"])
        r = c.put(f"/v1/agents/{other['id']}", json=body | {"name": "My Project"})
        assert r.status_code == 409 and r.json()["title"] == "agent exists"
        assert c.put(url, json=body | {"name": ""}).status_code == 409
        assert c.put(url, json=body | {"name": "mine"}).json()["name"] == "mine"


def test_named_agents_of_one_folder(daemon: Daemon) -> None:
    """Several ad-hoc agents in one folder, one per use case: a name makes another one."""
    scope = daemon.make_scope()
    plain = daemon.create_ad_hoc("fake", scope)
    review = daemon.create_ad_hoc("fake", scope, name="review")
    assert review["id"] != plain["id"] and review["name"] == "review"
    with daemon.http() as c:
        again = {"model": {"account": "fake"}, "scope": str(scope), "name": " Review "}
        assert c.post("/v1/agents", json=again).status_code == 409


def test_update_ad_hoc_agent(daemon: Daemon, tmp_path: Path) -> None:
    """PUT replaces an ad-hoc agent's settings and keeps its id (and so its sessions); the hosts
    its addons require are listed with what requires them."""
    scope = daemon.make_scope()
    ad_hoc = daemon.create_ad_hoc("fake", scope)
    (daemon.config_dir / "bindings" / "apps.toml").write_text(
        'apiVersion = "handler.binding/v1"\naddon = "app-builder"\n'
    )
    url = f"/v1/agents/{ad_hoc['id']}"
    with daemon.http() as c:
        body = {
            "model": {"account": "echo-box"},
            "scope": str(scope),
            "name": "tests",
            "allow": ["a.test:443"],
            "bindings": ["apps"],
        }
        r = c.put(url, json=body)
        assert r.status_code == 200, r.text
        updated = r.json()
        assert (updated["id"], updated["name"], updated["model"]["account"]) == (
            ad_hoc["id"],
            "tests",
            "echo-box",
        )
        assert (updated["network"], updated["egress"]) == ("filtered", "enforce")  # preset
        assert updated["allow"] == ["a.test:443"]
        required = updated["model"]["requiredHosts"]
        assert {"host": "registry.npmjs.org:443", "by": "addon app-builder: apps"} in required
        assert c.get(url).json()["allow"] == ["a.test:443"]
        # checked like a new one
        echo = {"account": "echo-box"}
        outside = c.put(url, json={"model": echo, "scope": str(tmp_path)})
        assert outside.status_code == 403
        assert (
            c.put(url, json={"model": echo, "scope": str(scope), "allow": ["nope"]}).status_code
            == 422
        )
        assert c.put("/v1/agents/nope", json=body).status_code == 404


def test_agent_confinement(daemon: Daemon) -> None:
    """An agent may run containers itself (nested), or run it privileged (shown with a
    warning); strict by default."""
    scope = daemon.make_scope()
    assert daemon.create_ad_hoc("echo-box", scope)["confinement"] == "strict"
    nested = daemon.create_ad_hoc("echo-box", scope, confinement="nested", name="podman")
    assert nested["confinement"] == "nested"
    root = daemon.create_ad_hoc("echo-box", scope, confinement="privileged", name="root")
    assert root["confinement"] == "privileged"
    with daemon.http() as c:
        bad = {"model": {"account": "echo-box"}, "scope": str(scope), "confinement": "none"}
        assert c.post("/v1/agents", json=bad).status_code == 422


def test_saves_that_widen_an_ad_hoc_agent_need_confirming(daemon: Daemon) -> None:
    """D.8 outside projects too: beyond the preset (a new agent) or beyond what it had (an
    update), a save is refused until confirmed; one that widens nothing needs no confirmation."""
    scope = str(daemon.make_scope())
    body = {"model": {"account": "fake"}, "scope": scope, "name": "wide"}
    wide = body | {"network": "open", "confinement": "privileged"}
    with daemon.http() as c:
        r = c.post("/v1/agents", json=wide)
        assert r.status_code == 409 and r.json()["title"] == "risks not confirmed"
        assert "open network" in r.json()["detail"] and "privileged" in r.json()["detail"]
        agent = c.post("/v1/agents", json=body).json()
        url = f"/v1/agents/{agent['id']}"
        r = c.put(url, json=body | {"egress": "log-only"})
        assert r.status_code == 409 and "log only" in r.json()["detail"]
        assert c.put(url, json=wide | {"confirmRisks": True}).json()["network"] == "open"
        assert c.put(url, json=wide).status_code == 200  # nothing wider than before
        assert c.put(url, json=body).status_code == 200  # narrower


def test_egress_patch_needs_a_filtered_run(daemon: Daemon) -> None:
    ad_hoc = daemon.create_ad_hoc("fake", daemon.make_scope(), network="open")
    with daemon.http() as c:
        assert c.patch(f"/v1/agents/{ad_hoc['id']}", json={"egress": "log-only"}).status_code == 409


def _wait(predicate: object, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:  # ty: ignore[call-non-callable]
        time.sleep(0.2)


def test_live_egress_switch_and_events(daemon: Daemon) -> None:
    """A.4 through the API: a live container connection switches enforcement; denials are listed."""
    require_echo_box()
    ad_hoc = daemon.create_ad_hoc(
        "echo-box", daemon.make_scope(), egress="enforce", allow=["example.org:443"]
    )
    assert ad_hoc["egress"] == "enforce"
    client = daemon.connect(ad_hoc["acpUrl"])  # `cat` agent: nothing to initialize
    try:
        with daemon.http() as c:
            url = f"/v1/agents/{ad_hoc['id']}"
            _wait(lambda: c.get(f"{url}/egress-events").json())
            events = c.get(f"{url}/egress-events").json()
            assert {"decision": "denied", "host": "example.com:443"}.items() <= events[0].items()
            assert len(c.get(url).json()["connections"]) == 1
            r = c.patch(url, json={"egress": "log-only"})
            assert r.status_code == 200, r.text
            assert r.json()["egress"] == "log-only"
            assert c.get(url).json()["egress"] == "log-only"
            assert c.patch(url, json={"egress": "enforce"}).json()["egress"] == "enforce"
            # a full update applies the allow-list and enforcement to the running sandbox
            body = {
                "model": {"account": "echo-box"},
                "scope": ad_hoc["scope"],
                "allow": ["a.test:443"],
            }
            r = c.put(url, json=body | {"egress": "log-only", "confirmRisks": True})  # D.8
            assert r.status_code == 200, r.text
            assert r.json()["egress"] == "log-only"
            assert c.get(url).json()["lastUsedAt"]
    finally:
        client.close()


def test_openapi_is_served(daemon: Daemon) -> None:
    assert httpx.get(f"{daemon.base_url}/openapi.json").status_code == 200
