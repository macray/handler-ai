"""Contract D conformance: the Control API of a real handlerd (contract D)."""

import json
import socket
import subprocess
import time
from pathlib import Path

import httpx
import pytest

from ..support.daemon import UI_ORIGIN, Daemon, require_echo_box


@pytest.mark.rule("connect.only-with-the-token", "connect.browsers-only-from-handler-s-pages")
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


def _outbound_address() -> str | None:
    """This computer's address on its network (the one it would reach the outside from)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("192.0.2.1", 9))  # a documentation address: nothing is sent
        except OSError:
            return None
        address = s.getsockname()[0]
    return None if address.startswith("127.") else address


def _answers(family: socket.AddressFamily, address: str, port: int) -> bool:
    with socket.socket(family, socket.SOCK_STREAM) as s:
        s.settimeout(2)
        return s.connect_ex((address, port)) == 0


@pytest.mark.rule("connect.this-computer-only")
def test_handlerd_answers_on_127_0_0_1_only(daemon: Daemon) -> None:
    """handlerd as started (its own choice of address): reached on 127.0.0.1, refused on another
    loopback address (where a listener on every address answers), on IPv6's loopback and on
    this computer's network address.

    If this fails: another computer on your network reaches the Control API and ACP."""
    port = int(daemon.base_url.rsplit(":", 1)[1])
    assert _answers(socket.AF_INET, "127.0.0.1", port)
    assert not _answers(socket.AF_INET, "127.0.0.2", port)
    if socket.has_ipv6:
        assert not _answers(socket.AF_INET6, "::1", port)
    if network := _outbound_address():
        assert not _answers(socket.AF_INET, network, port)


@pytest.mark.rule("agent.its-model-can-run")
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


@pytest.mark.rule("agent.outside-projects-it-is-its-folder-and-name", "save.saving-starts-nothing")
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


@pytest.mark.rule("folders.agents-work-only-inside-them")
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


@pytest.mark.rule("agent.deleting-it-stops-what-runs-on-it")
def test_deleting_an_agent_stops_its_sessions(daemon: Daemon) -> None:
    """A running session of a deleted agent is stopped (`deleted`), its folder kept.

    If this fails: a deleted agent keeps working, with nothing left to stop it from."""
    ad_hoc = daemon.create_ad_hoc("fake", daemon.make_scope())
    with daemon.http() as c:
        r = c.post("/v1/sessions", json={"agentId": ad_hoc["id"]})
        assert r.status_code == 202, r.text
        url = f"/v1/sessions/{r.json()['id']}"
        _wait(lambda: c.get(url).json()["state"] == "running")
        assert c.delete(f"/v1/agents/{ad_hoc['id']}").status_code == 204
        _wait(lambda: c.get(url).json()["state"] != "running", timeout=30)
        assert c.get(url).json()["state"] == "stopped"
    folder = daemon.config_dir.parent / "state" / "sessions" / r.json()["id"]
    log = [json.loads(line) for line in (folder / "events.ndjson").read_text().splitlines()]
    assert [e["how"] for e in log if e.get("event") == "stopped"] == ["deleted"]


@pytest.mark.rule("agent.deleting-it-stops-what-runs-on-it")
def test_deleting_an_agent_removes_its_running_sandbox(daemon: Daemon) -> None:
    """If this fails: a deleted agent's container keeps running, out of every list."""
    require_echo_box()
    ad_hoc = daemon.create_ad_hoc("echo-box", daemon.make_scope(), network="none")
    client = daemon.connect(ad_hoc["acpUrl"])  # `tail` agent: nothing to initialize
    try:
        with daemon.http() as c:
            url = f"/v1/agents/{ad_hoc['id']}"
            _wait(lambda: c.get(url).json()["connections"])
            (running,) = c.get(url).json()["connections"]
            assert _route(running["sandbox"]) == "none"  # its container runs
            assert c.delete(url).status_code == 204
        exists = ["podman", "container", "exists", running["sandbox"]]
        _wait(lambda: subprocess.run(exists, check=False).returncode == 1, timeout=30)
        assert subprocess.run(exists, check=False).returncode == 1
    finally:
        client.close()


@pytest.mark.rule("chat.is-no-app")
def test_chat_is_no_app(daemon: Daemon) -> None:
    """Chat's agents have no folder and no form; Chat itself, though listed with the apps, is
    none of them: not read, exported, shared, opened nor removed as one.

    If this fails: Chat could be uninstalled or exported, or one of its agents works in a folder
    of yours."""
    chat = {"model": {"account": "fake"}, "name": "Ask me", "chat": True}
    form = {"fields": {"type": "object", "properties": {"q": {"type": "string"}}}}
    with daemon.http() as c:
        for extra in ({"scope": str(daemon.make_scope())}, {"interface": form}):
            r = c.post("/v1/agents", json=chat | extra)
            assert r.status_code == 400 and r.json()["title"] == "a chat", r.text
        assert c.post("/v1/agents", json=chat).status_code == 201
        for method, path in [
            ("GET", ""), ("GET", "/export"), ("DELETE", ""), ("PUT", "/persons"),
            ("POST", "/open"), ("POST", "/deploy"),
        ]:  # fmt: skip
            body = {"persons": []} if method == "PUT" else None
            r = c.request(method, f"/v1/apps/chat{path}", json=body)
            assert r.status_code == 404, (method, path, r.text)


@pytest.mark.rule("agent.outside-projects-it-is-its-folder-and-name")
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


@pytest.mark.rule("agent.outside-projects-it-is-its-folder-and-name")
def test_named_agents_of_one_folder(daemon: Daemon) -> None:
    """Several ad-hoc agents in one folder, one per use case: a name makes another one."""
    scope = daemon.make_scope()
    plain = daemon.create_ad_hoc("fake", scope)
    review = daemon.create_ad_hoc("fake", scope, name="review")
    assert review["id"] != plain["id"] and review["name"] == "review"
    with daemon.http() as c:
        again = {"model": {"account": "fake"}, "scope": str(scope), "name": " Review "}
        assert c.post("/v1/agents", json=again).status_code == 409


@pytest.mark.rule(
    "agent.it-reaches-only-the-hosts-of-what-it-uses",
    "save.new-agents-start-with-only-the-sites-they-need",
)
@pytest.mark.rule("save.a-host-is-allowed-or-kept-blocked")
def test_update_ad_hoc_agent(daemon: Daemon, tmp_path: Path) -> None:
    """PUT replaces an ad-hoc agent's settings and keeps its id (and so its sessions); the hosts
    its addons require are listed with what requires them."""
    scope = daemon.make_scope()
    ad_hoc = daemon.create_ad_hoc("fake", scope)
    url = f"/v1/agents/{ad_hoc['id']}"
    with daemon.http() as c:
        body = {
            "model": {"account": "echo-box"},
            "scope": str(scope),
            "name": "tests",
            "allow": ["a.test:443"],
            "addons": [{"addon": "app-builder"}],
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
        assert {"host": "registry.npmjs.org:443", "by": "the app-builder tool"} in required
        assert c.get(url).json()["allow"] == ["a.test:443"]
        # checked like a new one
        echo = {"account": "echo-box"}
        outside = c.put(url, json={"model": echo, "scope": str(tmp_path)})
        assert outside.status_code == 403
        assert (
            c.put(url, json={"model": echo, "scope": str(scope), "allow": ["nope"]}).status_code
            == 422
        )
        # a host is allowed or kept blocked, never both (A.3)
        both = {"model": echo, "scope": str(scope), "allow": ["a.test:443"]}
        r = c.put(url, json=both | {"blocked": ["a.test:443", "b.test:443"]})
        assert r.status_code == 422 and "allowed and kept blocked at once: a.test:443" in r.text
        r = c.put(url, json=both | {"blocked": ["b.test:443"]})
        assert r.status_code == 200 and r.json()["blocked"] == ["b.test:443"]
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


@pytest.mark.rule("save.widening-is-confirmed")
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


def _route(sandbox: str) -> str:
    """How a running sandbox reaches out (once its launcher made its container): "filter" (its
    own internal network alone, its proxy the only way out), "direct", or "none"."""
    fmt = "{{.HostConfig.NetworkMode}} {{range $name, $_ := .NetworkSettings.Networks}}{{$name}} {{end}}"
    inspect = ["podman", "container", "inspect", sandbox, "--format", fmt]
    _wait(lambda: subprocess.run(inspect, capture_output=True, check=False).returncode == 0)
    mode, *networks = subprocess.run(
        inspect, capture_output=True, text=True, check=True
    ).stdout.split()
    if mode == "none":
        return "none"
    return "filter" if networks == [f"{sandbox}-net"] else "direct"


@pytest.mark.rule("network.mode-changes-with-the-next-sandbox")
def test_a_new_network_mode_reaches_the_next_sandbox_only(daemon: Daemon) -> None:
    """An agent saved open while its filtered sandbox runs: that sandbox stays on its own
    internal network, reaching out through its filter only; the next one has the direct route.

    If this fails: a running agent moves to an open network with nobody seeing a new sandbox
    start, or a saved mode never applies."""
    require_echo_box()
    ad_hoc = daemon.create_ad_hoc("echo-box", daemon.make_scope(), allow=["example.org:443"])
    url = f"/v1/agents/{ad_hoc['id']}"
    first = daemon.connect(ad_hoc["acpUrl"])  # `tail` agent: nothing to initialize
    second = None
    try:
        with daemon.http() as c:
            _wait(lambda: c.get(url).json()["connections"])
            (running,) = c.get(url).json()["connections"]
            assert _route(running["sandbox"]) == "filter"
            body = {"model": {"account": "echo-box"}, "scope": ad_hoc["scope"]}
            r = c.put(url, json=body | {"network": "open", "confirmRisks": True})
            assert r.status_code == 200 and r.json()["network"] == "open", r.text
            assert _route(running["sandbox"]) == "filter"
            second = daemon.connect(ad_hoc["acpUrl"])
            _wait(lambda: len(c.get(url).json()["connections"]) == 2)
            (new,) = [n for n in c.get(url).json()["connections"] if n["id"] != running["id"]]
            assert _route(new["sandbox"]) == "direct"
    finally:
        first.close()
        if second:
            second.close()


def test_openapi_is_served(daemon: Daemon) -> None:
    assert httpx.get(f"{daemon.base_url}/openapi.json").status_code == 200
