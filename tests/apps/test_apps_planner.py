"""H.12, H.13 and D.24 with Handler's own Planner, in a real sandbox: installed from Handler's
copy, given its folder and its agent (set up from its definition on the fake harness), deployed (its own
tests run), then asked: by its code (calendar.md written, a clash said, at once), by its agent (a
run, whose result is the action's), and through Ask (the router on the model alone, a stub
provider playing it). Planner is the private registry's: opt-in, HANDLER_TEST_REGISTRY."""

import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from handler_control.secrets import SecretStore

from ..support.daemon import FAKE_SECRET, Daemon, start_daemon
from ..support.remote import Device, DeviceError, Gateway, start_gateway
from ..support.sources import REGISTRY, requires_registry
from ..support.stub_llm import StubLlm
from .conftest import api, real_sandbox_env, requires_app_runtime

pytestmark = [requires_app_runtime, requires_registry("apps/planner")]


ROUTER = Path(__file__).parents[2] / (
    "packages/control-plane/src/handler_control/data/handler-needs/ask-router"
)


def route(body: dict[str, Any]) -> str:
    """The router's answer: the calendar for a call, nothing for the rest."""
    said = json.dumps(body["messages"])
    if "You: Tomorrow I call the bank" in said:
        fields = {"what": "Call the bank", "day": "2026-10-22", "time": "10:00"}
        result: dict[str, Any] = {"status": "ok", "summary": "Planner adds it", "kind": "pick"}
        result |= {"app": "planner"}
        result |= {"action": "add", "fields": fields, "why": "a call on a day"}
    else:
        result = {"status": "failed", "summary": "None of your apps books tables.", "kind": "none"}
    return f"```json handler-result\n{json.dumps(result)}\n```"


@pytest.fixture(scope="module")
def stub() -> Iterator[StubLlm]:
    s = StubLlm(route)
    yield s
    s.close()


@pytest.fixture(scope="module")
def daemon(data_root: Path, stub: StubLlm) -> Iterator[Daemon]:
    env = {"HANDLER_DATA_DIR": str(data_root / "handler"), "HANDLER_TEST_STUB_KEY": "sk-stub"}
    SecretStore(data_root / "handler").put("accounts/fake/token", FAKE_SECRET)
    providers = {"stub": stub.provider()}
    assert REGISTRY is not None
    yield from start_daemon(
        extra_env=env | real_sandbox_env(), extra_providers=providers, source=REGISTRY, addons=()
    )


@pytest.fixture(scope="module")
def folder(daemon: Daemon) -> Path:
    return daemon.make_scope() / "my-planner"  # in the work folders, its agent's: made when given


@pytest.fixture(scope="module")
def installed(daemon: Daemon, folder: Path) -> dict[str, Any]:
    """Planner from Handler's source (D.26), given a new folder and its agent, deployed."""
    api(daemon, "GET", "/v1/sources")  # the official source read
    r = api(daemon, "POST", "/v1/sources/official/apps/planner")
    assert r.status_code == 201, r.text
    app = r.json()
    assert app["fromSource"] == "official"
    r = api(daemon, "PUT", "/v1/apps/planner/files/tasks", {"path": str(folder), "create": True})
    assert r.status_code == 200, r.text
    (need,) = r.json()["agents"]
    definition = need["definition"]
    body = {
        "name": definition["agentName"],
        "model": {"account": "fake"},
        "permissions": definition["permissions"],
        "interface": definition["interface"],
        "origin": need["origin"],
        "app": need["origin"]["name"],
        "scope": str(folder),
    }
    agent = api(daemon, "POST", "/v1/agents", body)
    assert agent.status_code == 201, agent.text
    r = api(daemon, "PUT", "/v1/apps/planner/agents/planner", {"agentId": agent.json()["id"]})
    assert r.status_code == 200, r.text
    r = api(daemon, "POST", "/v1/apps/planner/deploy")
    assert r.status_code == 200, api(daemon, "GET", "/v1/apps/planner/log").json()["text"]
    return r.json()


@pytest.mark.rule("action.done-by-its-code-or-its-agent")
def test_its_actions_are_listed_with_their_forms(installed: dict[str, Any]) -> None:
    actions = {a["name"]: a for a in installed["actions"]}
    assert {n: a["by"] for n, a in actions.items()} == {
        "add": "code",
        "todo": "code",
        "planned": "code",
        "plan": "agent",
    }
    assert actions["add"]["fields"]["required"] == ["what", "day"]
    assert "request" in actions["plan"]["fields"]["properties"]  # its agent's form
    assert actions["add"]["examples"][0] == "Tomorrow I call the bank at 10"


@pytest.mark.rule("action.done-by-its-code-or-its-agent")
def test_an_ask_done_by_its_code(daemon: Daemon, installed: dict[str, Any], folder: Path) -> None:
    add = {"fields": {"what": "Dentist", "day": "2026-10-21", "time": "11:00"}}
    r = api(daemon, "POST", "/v1/apps/planner/actions/add", add)
    assert r.status_code == 200, r.text
    assert r.json()["result"] == {
        "status": "ok",
        "summary": "Added Wednesday 21 October at 11:00: Dentist.",
        "data": r.json()["result"]["data"],
    }
    add = {"fields": {"what": "Call the bank", "day": "2026-10-21", "time": "11:00"}}
    clash = api(daemon, "POST", "/v1/apps/planner/actions/add", add).json()
    assert (clash["state"], clash["result"]["status"]) == ("succeeded", "attention")
    assert clash["result"]["summary"].endswith("It clashes with Dentist at 11:00.")
    assert "- [ ] 11:00 Dentist" in (folder / "calendar.md").read_text()

    bad = api(daemon, "POST", "/v1/apps/planner/actions/add", {"fields": {"what": "x"}})
    assert bad.status_code == 400 and "day" in bad.json()["detail"]
    assert api(daemon, "POST", "/v1/apps/planner/actions/nope", {}).status_code == 404


@pytest.mark.rule("action.done-by-its-code-or-its-agent")
def test_an_ask_done_by_its_agent(daemon: Daemon, installed: dict[str, Any]) -> None:
    answer = {"status": "attention", "summary": "The bank first, then the dentist."}
    fields = {"request": "Plan my day.", "fake": "valid", "answer": answer}  # the fake agent's
    r = api(daemon, "POST", "/v1/apps/planner/actions/plan", {"fields": fields})
    assert r.status_code == 200, r.text
    run = r.json()
    deadline = time.monotonic() + 60
    while run["state"] == "running":
        assert time.monotonic() < deadline
        time.sleep(0.5)
        run = api(daemon, "GET", f"/v1/apps/planner/actions/plan/runs/{run['runId']}").json()
    assert run["state"] == "succeeded", run.get("error")
    assert run["result"] == answer | {"data": answer}
    session = api(daemon, "GET", f"/v1/sessions/{run['sessionId']}").json()
    assert (session["origin"], session["app"]) == ("app", "planner")


@pytest.mark.rule("router.the-one-you-gave")
def test_ask_without_a_router(daemon: Daemon, installed: dict[str, Any]) -> None:
    said = {"turns": [{"who": "you", "text": "Tomorrow I call the bank at 10"}]}
    r = api(daemon, "POST", "/v1/ask", said)
    assert r.status_code == 409 and "Ask router" in r.json()["detail"]


@pytest.mark.rule(
    "ask.only-the-actions-offered",
    "ask.a-pick-runs-at-once-as-the-owner",
    "ask.none-leads-to-chat",
    "router.one-run-per-ask",
)
def test_ask_routes_to_an_ask_and_runs_it(
    daemon: Daemon, installed: dict[str, Any], stub: StubLlm, folder: Path
) -> None:
    router = {
        "name": "Ask router",
        "modelAlone": True,
        "model": {"provider": "stub"},
        "instructions": (ROUTER / "instructions.md").read_text(),
        "interface": json.loads((ROUTER / "interface.json").read_text()),
    }
    agent = api(daemon, "POST", "/v1/agents", router)
    assert agent.status_code == 201, agent.text
    given = api(daemon, "PUT", "/v1/handler-needs/ask-router", {"agentId": agent.json()["id"]})
    assert given.status_code == 200, given.text

    said = {"turns": [{"who": "you", "text": "Tomorrow I call the bank at 10"}]}
    answer = api(daemon, "POST", "/v1/ask", said | {"timezone": "Europe/Paris"}).json()
    assert (answer["kind"], answer["app"], answer["action"]) == ("pick", "planner", "add"), answer
    assert answer["why"] == "a call on a day"
    assert (
        answer["run"]["result"]["summary"] == "Added Thursday 22 October at 10:00: Call the bank."
    )
    assert "- [ ] 10:00 Call the bank" in (folder / "calendar.md").read_text()
    prompt = json.dumps(stub.requests[-1]["messages"])
    assert "action `add`" in prompt and "Europe/Paris" in prompt  # what it read
    run = api(daemon, "GET", f"/v1/sessions/{answer['routerRun']}").json()
    assert (run["origin"], run["agentId"]) == ("ask", agent.json()["id"])

    said = {"turns": [{"who": "you", "text": "Book a table at Chez Paul"}]}
    none = api(daemon, "POST", "/v1/ask", said).json()
    assert none["kind"] == "none" and none["summary"] == "None of your apps books tables."
    assert {(o["app"], o["action"]) for o in none["actions"]} >= {
        ("planner", "add"),
        ("planner", "plan"),
    }

    assert api(daemon, "PUT", "/v1/apps/planner/askable", {"askable": False}).is_success
    off = api(daemon, "POST", "/v1/ask", said).json()
    assert off["kind"] == "none" and off["actions"] == []  # nothing offered to Ask
    assert api(daemon, "PUT", "/v1/apps/planner/askable", {"askable": True}).is_success


@pytest.fixture(scope="module")
def gateway() -> Iterator[Gateway]:
    yield from start_gateway()


@pytest.mark.rule("ask.the-owner-s-devices-only")
def test_ask_from_the_owner_s_phone(
    daemon: Daemon, installed: dict[str, Any], gateway: Gateway
) -> None:
    """D.24 on the device channel (D.7): the owner's phone lists what can be asked and asks (the
    host polls for it, nothing else being shared); a family member's phone cannot Ask."""
    body = {"gatewayUrl": gateway.url, "hostToken": gateway.host_token}
    assert api(daemon, "PUT", "/v1/remote/gateway", body).status_code == 200
    owner = Device(
        api(daemon, "POST", "/v1/remote/devices", {"name": "phone"}).json()["pairingUrl"]
    )
    options = owner.request(None, "_handler/remote/ask_options")["actions"]
    assert {
        "app": "planner",
        "action": "todo",
        "description": "Add a to-do, maybe for a day",
    } in options
    said = {"turns": [{"who": "you", "text": "Tomorrow I call the bank at 10"}], "timezone": "UTC"}
    answer = owner.request(None, "_handler/remote/ask", said, timeout=60)
    assert (answer["kind"], answer["app"], answer["action"]) == ("pick", "planner", "add")
    assert answer["run"]["result"]["summary"].startswith("Added Thursday 22 October at 10:00")

    family = {"name": "kid", "person": "kid", "scope": "apps"}
    kid = Device(api(daemon, "POST", "/v1/remote/devices", family).json()["pairingUrl"])
    with pytest.raises(DeviceError):
        kid.request(None, "_handler/remote/ask", said)
    with pytest.raises(DeviceError):
        kid.request(None, "_handler/remote/ask_options")
