"""D.18 conformance, the model alone: an agent with no program, on a real handlerd and a stub
provider. Its sessions start no sandbox: a chat is a conversation with the model, a job's run
ends with its result as any run; what only a sandbox has is refused when it is saved, and it has
neither plain connections nor terminals (contract D.18)."""

import json
import socket
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from websockets.exceptions import ConnectionClosed, InvalidStatus

from ..support.daemon import Daemon, start_daemon
from ..support.stub_llm import StubLlm
from .test_runs import RESULT, wait_output
from .test_sessions import attach, create_session, get_session, wait_state

STUB_KEY = "sk-stub-secret-value"
ALONE = {"modelAlone": True, "model": {"provider": "stub"}}


@pytest.fixture(scope="module")
def stub() -> Iterator[StubLlm]:
    s = StubLlm("Hello.")
    yield s
    s.close()


@pytest.fixture(scope="module")
def knowledge() -> Path:
    root = Path(tempfile.mkdtemp(prefix="handler-knowledge-"))
    (root / "acme").mkdir()
    (root / "acme" / "people.md").write_text("Write to Julie, never to support.")
    return root


def closed_port() -> int:
    """A port nothing listens on: a model server that is not running."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


UNREACHABLE = closed_port()


@pytest.fixture(scope="module")
def daemon(stub: StubLlm, knowledge: Path) -> Iterator[Daemon]:
    down = stub.provider().replace(f":{stub.port}/", f":{UNREACHABLE}/")
    yield from start_daemon(
        extra_env={"HANDLER_NOTES_DIR": str(knowledge), "HANDLER_TEST_STUB_KEY": STUB_KEY},
        extra_providers={"stub": stub.provider(), "down": down},
    )


def create(daemon: Daemon, **body: Any) -> dict[str, Any]:
    with daemon.http() as c:
        r = c.post("/v1/agents", json=ALONE | body)
        assert r.status_code == 201, r.text
        return r.json()


@pytest.mark.rule(
    "alone.no-tools", "alone.reads-only-its-notes-and-conversation", "alone.a-session-like-any"
)
def test_a_chat_is_a_conversation_with_the_model(daemon: Daemon, stub: StubLlm) -> None:
    stub.answer = "Hello."
    agent = create(daemon, name="ask", knowledge=["acme"])
    assert agent["modelAlone"] is True and agent["connections"] == []
    assert not {"harness", "problem"} & set(agent["model"])
    session = create_session(daemon, agent, prompt="Who do I write to?")
    session = wait_state(daemon, session["id"], "running")
    assert "harness" not in session
    client, _ = attach(daemon, session)
    try:
        client.prompt(get_session(daemon, session["id"])["acpSessionId"], "Thanks")
        assert client.text() == "Hello.Hello."  # the first turn's, replayed, then this one's
    finally:
        client.close()
    sent = stub.requests[-1]
    assert sent["headers"]["Authorization"] == f"Bearer {STUB_KEY}"
    system, *turns = sent["messages"]
    assert "Write to Julie, never to support." in system["content"]
    assert [t["role"] for t in turns] == ["user", "assistant", "user"]
    assert not {"tools", "tool_choice", "functions"} & set(sent)


@pytest.mark.rule("alone.a-session-like-any")
def test_a_job_run_ends_with_its_result(daemon: Daemon, stub: StubLlm) -> None:
    stub.answer = 'Looks fine.\n```json handler-result\n{"verdict": "good"}\n```'
    agent = create(daemon, name="judge", interface={"result": RESULT})
    run = create_session(daemon, agent, input={})
    done = wait_output(daemon, run["id"])
    assert done["unattended"] is True
    assert done["output"] == {"valid": True, "value": {"verdict": "good"}}


@pytest.mark.rule("alone.a-session-like-any", "job.its-result-is-checked")
def test_a_run_on_a_model_it_cannot_reach_says_why(daemon: Daemon) -> None:
    """The model's own error is the run's: what Ask says when its router cannot answer, instead
    of "no valid result"."""
    agent = create(
        daemon, name="unreachable", model={"provider": "down"}, interface={"result": RESULT}
    )
    run = create_session(daemon, agent, input={})
    done = wait_output(daemon, run["id"])
    error = done["output"]["error"]
    assert done["output"]["valid"] is False
    assert error.startswith(f"127.0.0.1:{UNREACHABLE}: ") and "unavailable" not in error, error
    assert "connect" in error.lower(), error  # httpx's: "All connection attempts failed"


@pytest.mark.rule("alone.notes-fit-in-a-call")
def test_saving_it_with_more_knowledge_than_a_call_takes_is_refused(
    daemon: Daemon, knowledge: Path
) -> None:
    """Notes over 192 KiB in its knowledge folder: the agent on the model alone is refused (400
    `notes too large`) and not kept; notes just under are taken, and an agent program (its
    notes are files it reads, not part of a call) takes the larger ones.

    If this fails: a turn is refused by the provider with an error nobody understands, or an
    agent is saved that can never answer."""
    (knowledge / "big").mkdir()
    (knowledge / "big" / "notes.md").write_text("x" * (192 * 1024 + 1))
    (knowledge / "fits").mkdir()
    (knowledge / "fits" / "notes.md").write_text("x" * (190 * 1024))
    with daemon.http() as c:
        r = c.post("/v1/agents", json=ALONE | {"name": "too-much", "knowledge": ["big"]})
        assert r.status_code == 400 and r.json()["title"] == "notes too large", r.text
        assert "too-much" not in {a.get("name") for a in c.get("/v1/agents").json()}
    assert create(daemon, name="just-fits", knowledge=["fits"])["knowledge"] == ["fits"]
    program = {"model": {"account": "fake"}, "scope": str(daemon.make_scope())}
    with daemon.http() as c:
        r = c.post("/v1/agents", json=program | {"name": "a-program", "knowledge": ["big"]})
        assert r.status_code == 201, r.text


@pytest.mark.rule("alone.only-what-needs-no-sandbox")
def test_what_only_a_sandbox_has_is_refused(daemon: Daemon) -> None:
    refused = [
        {"model": {"account": "fake"}},  # a subscription: its vendor's program signs in
        {"model": {"provider": "stub", "harness": "fake"}},
        {"network": "open"},
        {"addons": [{"addon": "x"}]},
        {"display": True},
        {"permissions": "ask"},
    ]
    with daemon.http() as c:
        for body in refused:
            r = c.post("/v1/agents", json=ALONE | body)
            assert r.status_code in (400, 422), (body, r.text)
        r = c.post("/v1/agents", json=ALONE | {"skills": ["anything"]})
        assert r.status_code == 400 and r.json()["title"] == "model alone"


@pytest.mark.rule("alone.only-what-needs-no-sandbox")
def test_no_plain_connection_and_no_terminal(daemon: Daemon) -> None:
    agent = create(daemon, name="plain")
    client = daemon.connect(agent["acpUrl"])
    # refused: at the handshake, or closed right after it, seen by the send (ConnectionClosed)
    # or, when the send got out first, by the reader (EOFError)
    with pytest.raises((InvalidStatus, ConnectionClosed, EOFError)):
        client.initialize()
    with daemon.http() as c:
        r = c.post(f"/v1/agents/{agent['id']}/terminal", json={})
        assert r.status_code == 409, r.text
        assert "works in sessions only" in json.dumps(r.json())
