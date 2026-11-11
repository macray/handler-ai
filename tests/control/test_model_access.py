"""Accounts and providers through a real handlerd (D.9, D.12): what agents run as; and an agent's
allow-list, live on running sandboxes."""

import json
import time
from collections.abc import Iterator
from typing import Any

import pytest

from handler_sandbox_kit import egress
from handler_sandbox_kit.launch import running_filter

from ..support.daemon import Daemon, require_echo_box, start_daemon


@pytest.fixture(scope="module")
def daemon() -> Iterator[Daemon]:
    yield from start_daemon()


KEY = "sk-or-not-a-real-key"

PROVIDER = """apiVersion = "handler.provider/v1"
[endpoints]
openai-chat = "https://api.example.com/v1"
[[models]]
id = "m1"
"""


@pytest.mark.rule(
    "access.the-api-stores-what-it-is-given",
    "access.its-secrets-follow-it",
    "access.its-status-says-what-is-missing",
    "provider.its-endpoints-and-models-are-checked",
    "secrets.never-read-back",
    "secrets.every-one-is-listed",
    "secrets.kept-for-you-only",
)
def test_providers(daemon: Daemon) -> None:
    """D.12: listed with their status and use; created from a template's values, edited, renamed
    while unused and deleted; a key sent with it goes to the secret store."""
    (daemon.providers_dir / "remote.toml").write_text(
        'apiKey = { env = "HANDLER_TEST_NO_SUCH_KEY" }\n' + PROVIDER
    )
    (daemon.providers_dir / "typo.toml").write_text(PROVIDER.replace("[[models]]", "[[modles]]"))
    with daemon.http() as c:
        listed = {p["name"]: p for p in c.get("/v1/providers").json()}
        remote = listed["remote"]
        assert remote["status"] == "incomplete" and remote["key"] == "env"
        assert remote["endpoints"] == {"openai-chat": "https://api.example.com/v1"}
        assert remote["models"][0]["id"] == "m1"
        assert {"vibe", "pi"} <= set(remote["harnesses"])
        assert listed["typo"]["status"] == "invalid" and listed["typo"]["error"]

        templates = {t["name"]: t for t in c.get("/v1/provider-templates").json()}
        assert {"llamacpp", "anthropic-api", "openrouter"} <= templates.keys()
        assert templates["openrouter"]["needsKey"] and not templates["llamacpp"]["needsKey"]
        router = templates["openrouter"]
        body = {"name": "router", "endpoints": router["endpoints"], "models": router["models"]}
        r = c.post("/v1/providers", json=body | {"key": KEY})
        assert r.status_code == 201, r.text
        made = r.json()
        assert (made["status"], made["key"]) == ("ready", "secret") and KEY not in r.text
        assert c.post("/v1/providers", json=body).status_code == 409
        text = (daemon.providers_dir / "router.toml").read_text()
        assert 'apiKey = {secret = "providers/router/apiKey"}' in text and KEY not in text
        assert (daemon.providers_dir / "router.toml").stat().st_mode & 0o777 == 0o600

        # edited: without a key, the one it has is kept, a hand-written reference too
        r = c.put("/v1/providers/remote", json=body | {"name": "remote", "description": "d"})
        assert r.json()["key"] == "env" and r.json()["description"] == "d"
        # renamed while unused: its key follows
        r = c.put("/v1/providers/router", json=body | {"name": "router2"})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "ready" and not (daemon.providers_dir / "router.toml").exists()
        secrets = {s["path"]: s for s in c.get("/v1/secrets").json()}
        assert secrets["providers/router2/apiKey"]["usedBy"] == ["providers/router2"]
        assert secrets["providers/router2/apiKey"]["hosts"] == ["openrouter.ai:443"]
        r = c.put("/v1/providers/router2", json=body | {"name": "router2", "removeKey": True})
        assert r.json().get("key") is None  # absent: none
        assert c.delete("/v1/providers/router2").status_code == 204
        assert c.delete("/v1/providers/router2").status_code == 404
        assert "providers/router2/apiKey" not in {s["path"] for s in c.get("/v1/secrets").json()}
        bad = body | {"name": "x", "endpoints": {"openai-chat": "ftp://x"}}
        assert c.post("/v1/providers", json=bad).status_code == 422


@pytest.mark.rule("access.one-account-or-one-provider", "access.in-use-is-never-renamed")
def test_a_provider_in_use_is_not_renamed_but_deleted(daemon: Daemon) -> None:
    (daemon.providers_dir / "used.toml").write_text(PROVIDER)
    scope = daemon.make_scope()
    used = daemon.create_ad_hoc(None, scope, provider="used", harness="vibe")
    body = {
        "name": "renamed",
        "endpoints": {"openai-chat": "https://x.example"},
        "models": [{"id": "m"}],
    }
    with daemon.http() as c:
        r = c.put("/v1/providers/used", json=body)
        assert r.status_code == 409 and f"an agent in {scope.name}" in r.text
        assert c.delete("/v1/providers/used").status_code == 204
        # its agent keeps the name: a model that cannot start until given another (E1)
        model = c.get(f"/v1/agents/{used['id']}").json()["model"]
        assert model["provider"] == "used" and "no provider 'used'" in model["problem"]


@pytest.mark.rule(
    "access.its-secrets-follow-it",
    "access.in-use-is-never-renamed",
    "access.its-status-says-what-is-missing",
    "account.of-a-harness-that-signs-in",
    "account.no-start-without-its-login",
    "account.its-login-file-is-kept-apart",
    "secrets.set-by-their-owner",
)
def test_accounts(daemon: Daemon) -> None:
    """D.9: created, logged in (a token or a file), renamed while unused, deleted."""
    daemon.create_ad_hoc("fake", daemon.make_scope(), name="uses fake")
    with daemon.http() as c:
        listed = {a["name"]: a for a in c.get("/v1/accounts").json()}
        fake = listed["fake"]
        assert (fake["status"], fake["login"]) == ("ready", "token")  # logged in by the fixture
        assert "uses fake" in fake["agents"]  # an ad-hoc agent: by its name
        assert listed["codex"]["status"] == "incomplete"  # not logged in
        assert listed["codex"]["hosts"] == ["chatgpt.com:443", "auth.openai.com:443"]
        assert listed["echo-box"]["login"] == "token"

        r = c.post("/v1/accounts", json={"name": "plus", "harness": "codex", "description": "d"})
        assert r.status_code == 201, r.text
        assert (r.json()["login"], r.json()["status"]) == ("file", "incomplete")
        assert c.post("/v1/accounts", json={"name": "plus", "harness": "codex"}).status_code == 409
        assert c.post("/v1/accounts", json={"name": "x", "harness": "nope"}).status_code == 409
        assert c.post("/v1/accounts", json={"name": "../x", "harness": "codex"}).status_code == 422

        assert c.put("/v1/accounts/plus/login", json={"token": "t"}).status_code == 422
        r = c.put("/v1/accounts/plus/login", json={"file": '{"tokens": {}}'})
        assert r.json()["status"] == "ready"
        kept = daemon.data_dir / "accounts" / "plus" / "login" / "credential"
        assert kept.read_text() == '{"tokens": {}}' and kept.stat().st_mode & 0o777 == 0o600

        r = c.put("/v1/accounts/plus", json={"name": "chatgpt", "harness": "codex"})
        assert r.status_code == 200 and r.json()["status"] == "ready"  # the login followed
        assert (
            c.put("/v1/accounts/chatgpt", json={"name": "chatgpt", "harness": "pi"}).status_code
            == 409
        )
        r = c.put("/v1/accounts/fake", json={"name": "other", "harness": "fake"})
        assert r.status_code == 409 and "uses fake" in r.text  # in use: by whom

        r = c.delete("/v1/accounts/chatgpt/login")
        assert r.json()["status"] == "incomplete"

        assert c.delete("/v1/accounts/chatgpt").status_code == 204
        assert c.delete("/v1/accounts/chatgpt").status_code == 404
        assert c.put("/v1/secrets/accounts/fake/token", json={"value": "x"}).status_code == 409
    assert not (daemon.accounts_dir / "chatgpt.toml").exists()


@pytest.mark.rule(
    "access.the-api-stores-what-it-is-given",
    "access.its-secrets-follow-it",
    "account.the-sign-in-is-yours",
)
def test_an_account_with_a_token_login(daemon: Daemon) -> None:
    """D.9: the person's token, pasted (handler's store) or where they keep it; it follows a
    rename."""
    with daemon.http() as c:
        assert (
            c.post("/v1/accounts", json={"name": "pro", "harness": "claude-code"}).status_code
            == 201
        )
        r = c.post("/v1/accounts/pro/login/window")
        assert r.status_code == 409 and "claude setup-token" in r.text  # never run by handler
        assert c.put("/v1/accounts/pro/login", json={"file": "x"}).status_code == 422
        r = c.put("/v1/accounts/pro/login", json={"token": "sk-ant-oat01-x"})
        pro = r.json()
        assert (pro["status"], pro["token"]) == ("ready", "secret")
        assert pro["expiresAt"][:4] == str(int(pro["loggedInAt"][:4]) + 1)  # a year
        r = c.put("/v1/accounts/pro", json={"name": "work", "harness": "claude-code"})
        assert r.json()["status"] == "ready"  # renamed: its token followed
        assert 'secret = "accounts/work/token"' in (daemon.accounts_dir / "work.toml").read_text()
        r = c.put("/v1/accounts/work/login", json={"tokenRef": {"env": "MY_CLAUDE"}})
        work = r.json()
        assert (work["status"], work["token"], work.get("loggedInAt")) == ("ready", "env", None)
        token = next(s for s in c.get("/v1/secrets").json() if s["path"] == "accounts/work/token")
        assert (token["source"], token.get("updatedAt")) == ("env", None)  # the pasted one is gone
        r = c.delete("/v1/accounts/work/login")
        assert (r.json()["status"], r.json().get("token")) == ("incomplete", None)
        assert c.delete("/v1/accounts/work").status_code == 204


@pytest.mark.rule("access.one-account-or-one-provider", "access.in-use-is-never-renamed")
def test_an_account_in_use_is_deleted_its_agents_cannot_start(daemon: Daemon) -> None:
    """D.9, E1: once deleted, the agents using it keep its name, a model that cannot start until
    they are given another account."""
    used = daemon.create_ad_hoc("fake", daemon.make_scope(), name="uses fake")
    with daemon.http() as c:
        assert c.delete("/v1/accounts/fake").status_code == 204
        model = c.get(f"/v1/agents/{used['id']}").json()["model"]
        assert model["account"] == "fake" and "no account 'fake'" in model["problem"]


@pytest.mark.rule("account.no-start-without-its-login")
def test_a_sign_in_code_is_not_a_token(daemon: Daemon) -> None:
    """D.9: what Claude Code's sign-in page shows to paste back into `claude setup-token` is
    refused, saying so (its `tokenPrefix`)."""
    with daemon.http() as c:
        c.post("/v1/accounts", json={"name": "code", "harness": "claude-code"}).raise_for_status()
        r = c.put("/v1/accounts/code/login", json={"token": "QhR9xk2vL7mN#a4Bc"})
        assert r.status_code == 422 and "a code its sign-in page shows" in r.text
        [code] = [a for a in c.get("/v1/accounts").json() if a["name"] == "code"]
        assert code["status"] == "incomplete"  # not kept


@pytest.mark.rule("access.its-status-says-what-is-missing", "account.of-a-harness-that-signs-in")
def test_an_account_says_its_plan(daemon: Daemon) -> None:
    """E, D.9: one of its harness's login plans (Claude Code cannot learn it from a token)."""
    with daemon.http() as c:
        body = {"name": "pro", "harness": "claude-code", "description": "me@example.org"}
        r = c.post("/v1/accounts", json=body | {"plan": "pro"})
        assert r.status_code == 201 and r.json()["plan"] == "pro", r.text
        r = c.put("/v1/accounts/pro", json=body | {"plan": "max"})
        assert r.status_code == 200 and r.json()["plan"] == "max"
        assert 'plan = "max"' in (daemon.accounts_dir / "pro.toml").read_text()
        r = c.put("/v1/accounts/pro", json=body | {"plan": "gold"})
        assert r.status_code == 409 and "not one of pro, max, team, enterprise" in r.text
        r = c.post("/v1/accounts", json={"name": "plus", "harness": "codex", "plan": "pro"})
        assert r.status_code == 409 and "has no plans" in r.text
        (daemon.accounts_dir / "pro.toml").write_text(
            'apiVersion = "handler.account/v1"\nharness = "claude-code"\nplan = "gold"\n'
        )  # by hand
        [pro] = [a for a in c.get("/v1/accounts").json() if a["name"] == "pro"]
        assert pro["status"] == "invalid" and "gold" in pro["error"]
        assert c.delete("/v1/accounts/pro").status_code == 204


@pytest.mark.rule("account.of-a-harness-that-signs-in")
def test_an_account_may_use_its_connectors(daemon: Daemon) -> None:
    """E: only where its harness has account connectors (Claude Code), off by default."""
    with daemon.http() as c:
        body = {"name": "linked", "harness": "claude-code"}
        r = c.post("/v1/accounts", json=body | {"connectors": True})
        assert r.status_code == 201 and r.json()["connectors"] is True, r.text
        assert "connectors = true" in (daemon.accounts_dir / "linked.toml").read_text()
        r = c.put("/v1/accounts/linked", json=body)
        assert r.status_code == 200 and r.json().get("connectors", False) is False
        r = c.post("/v1/accounts", json={"name": "nolinks", "harness": "codex", "connectors": True})
        assert r.status_code == 409 and "has no account connectors" in r.text
        assert c.delete("/v1/accounts/linked").status_code == 204


@pytest.mark.rule("provider.its-files-go-to-their-harness")
def test_a_provider_keeps_its_harness_files(daemon: Daemon) -> None:
    """E: a provider's `[files.<harness>]` are given at its creation and kept by form edits."""
    files = {"codex": {"instructions_md": {"content": "You are…"}}}
    body: dict[str, Any] = {"name": "withfiles", "models": [{"id": "m"}]}
    body["endpoints"] = {"responses": "http://127.0.0.1:3000/v1"}
    with daemon.http() as c:
        r = c.post("/v1/providers", json=body | {"files": files})
        assert r.status_code == 201 and r.json()["files"] == ["codex"], r.text
        r = c.put("/v1/providers/withfiles", json=body | {"description": "edited"})
        assert r.status_code == 200 and r.json()["files"] == ["codex"]
        assert "[files.codex]" in (daemon.providers_dir / "withfiles.toml").read_text()
        assert c.delete("/v1/providers/withfiles").status_code == 204


@pytest.mark.rule("network.a-host-kept-blocked-is-not-asked-for")
def test_allow_applies_to_running_sandboxes(daemon: Daemon) -> None:
    """An ad-hoc agent's own hosts, those it keeps blocked and log-only, changed by a full
    update, reach its running filtered sandbox at once (A.4)."""
    require_echo_box()
    scope = daemon.make_scope()
    settings = {"model": {"account": "echo-box"}, "scope": str(scope), "egress": "enforce"}
    ad_hoc = daemon.create_ad_hoc("echo-box", scope, egress="enforce", allow=["a.org:443"])
    client = daemon.connect(ad_hoc["acpUrl"])  # `cat` agent: nothing to initialize
    try:
        with daemon.http() as c:
            url = f"/v1/agents/{ad_hoc['id']}"
            deadline = time.monotonic() + 60
            while not c.get(url).json()["connections"] and time.monotonic() < deadline:
                time.sleep(0.2)
            sandbox = c.get(url).json()["connections"][0]["sandbox"]
            deadline = time.monotonic() + 60  # listed before its launcher made its folder
            while (folder := running_filter(sandbox)) is None and time.monotonic() < deadline:
                time.sleep(0.2)
            assert folder is not None
            state = folder / egress.SETTINGS_FILE
            r = c.put(url, json=settings | {"allow": ["example.com:443"]})
            assert r.status_code == 200, r.text
            written = json.loads(state.read_text())
            assert written.pop("version") >= 2  # the first settings, then these (A.4)
            assert written == {
                "allow": ["example.com:443"],
                "blocked": [],
                "enforcement": "enforce",
                "watched": None,  # no client attached
            }
            kept = {"allow": [], "blocked": ["example.com:443", "pypi.org:443"]}
            r = c.put(url, json=settings | kept)  # kept blocked, taken off the allowed
            assert r.status_code == 200, r.text
            written = json.loads(state.read_text())
            assert {k: written[k] for k in kept} == kept
    finally:
        client.close()
