"""The model's host that does not answer, said in the session (contract F.9).

pi is the fake agent here (`start_daemon(fake_pi=True)`), on a provider whose server is on this
computer: its `unreached HOST N` writes N requests to HOST that could not connect, as its
sandbox's filter reports them (A.3), `reached HOST N` N that did.
"""

import time
from collections.abc import Iterator
from typing import Any

import pytest

from handler_control.sessions import EGRESS_LAG

from ..support.daemon import Daemon, start_daemon
from .test_blocked_hosts import lines
from .test_sessions import attach, create_session, get_session

MODEL = "host.containers.internal:3000"
LLAMA = """apiVersion = "handler.provider/v1"
[endpoints]
openai-chat = "http://127.0.0.1:3000/v1"
[[models]]
id = "qwen"
"""


@pytest.fixture(scope="module")
def daemon() -> Iterator[Daemon]:
    yield from start_daemon(extra_providers={"llama": LLAMA}, fake_pi=True)


def lines_of(client: Any) -> list[dict[str, Any]]:
    return [m["params"] for m in client.updates if m["method"] == "_handler/line"]


@pytest.mark.rule("session.an-unreachable-model-is-said")
def test_a_model_that_does_not_answer_is_said_once_per_turn(daemon: Daemon) -> None:
    agent = daemon.create_ad_hoc(
        None, daemon.make_scope(), harness="pi", provider="llama", model="qwen", egress="enforce"
    )
    session = create_session(daemon, agent)
    client, _ = attach(daemon, session)
    acp_id = get_session(daemon, session["id"])["acpSessionId"]
    try:
        client.prompt(acp_id, f"unreached {MODEL} 5")  # the third failure says it, once
        (said,) = lines(client, 1)
        assert said | {"seq": 0} == {
            "seq": 0,
            "event": "model unreached",
            "host": MODEL,
            "error": "connection refused",
            "provider": "llama",
            "local": True,
        }
        client.prompt(acp_id, f"unreached {MODEL} 2")  # two: not yet (MODEL_SILENCE first)
        client.prompt(acp_id, "unreached elsewhere.org:443 5")  # not the model's host
        time.sleep(EGRESS_LAG + 0.5)  # the filter's last events came
        assert [x["seq"] for x in lines_of(client) if x["event"] == "model unreached"] == [
            said["seq"]
        ]
        client.prompt(acp_id, f"unreached {MODEL} 3")  # a new turn: said again
        (again,) = lines(client, 1)
        assert again["event"] == "model unreached" and again["seq"] > said["seq"]
    finally:
        client.close()
    later, _ = attach(daemon, session)  # in the history, in its place
    try:
        replayed = [x for x in lines_of(later) if x["event"] == "model unreached"]
        assert [x["seq"] for x in replayed] == [said["seq"], again["seq"]]
    finally:
        later.close()
