"""The inbox from a paired phone (D.7, H.9, I.3): a device marks read its own person's messages,
whatever its scope, and only those; what it marks is read on the computer too."""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from ..support.daemon import Daemon, start_daemon
from ..support.remote import Device, DeviceError, Gateway, start_gateway
from .test_remote import pair, wait_light


def message(id: str, person: str) -> dict[str, str]:
    return {
        "id": id,
        "source": "app",
        "name": "worklog",
        "person": person,
        "title": f"for {person}",
        "at": "2026-11-15T09:00:00Z",
    }


@pytest.fixture(scope="module")
def gateway() -> Iterator[Gateway]:
    yield from start_gateway()


@pytest.fixture(scope="module")
def daemon(gateway: Gateway) -> Iterator[Daemon]:
    for d in start_daemon():
        with d.http() as c:
            body = {"gatewayUrl": gateway.url, "hostToken": gateway.host_token}
            assert c.put("/v1/remote/gateway", json=body).status_code == 200
            made = c.post(
                "/v1/agents", json={"model": {"account": "fake"}, "name": "Claude", "chat": True}
            )
            assert made.status_code == 201, made.text  # someone to talk to: the host polls
        inbox = [message("m_owner", "owner"), message("m_kid", "kid"), message("m_other", "owner")]
        (Path(d.env["HANDLER_STATE_DIR"]) / "inbox.json").write_text(json.dumps(inbox))
        d.restart()  # handlerd reads its inbox when it starts
        yield d


def read_on_the_computer(daemon: Daemon) -> dict[str, bool]:
    with daemon.http() as c:
        return {m["id"]: m["read"] for m in c.get("/v1/inbox").json()}


@pytest.mark.rule("device.marks-read-only-its-person-s-messages")
def test_a_device_marks_its_person_s_messages_read(daemon: Daemon) -> None:
    """The owner's device marks one of the owner's messages read: the computer shows it read. A
    family member's device (apps only) marks its own. Another person's message and an unknown
    one are refused alike (-32602, "no such message").

    If this fails: a family member's phone clears your inbox's dots, or learns which messages you
    have; or a read on the phone comes back unread on the computer."""
    wait_light(daemon, "ok")
    owner = pair(daemon, "phone")
    with daemon.http() as c:
        r = c.post("/v1/remote/devices", json={"name": "kid", "person": "kid", "scope": "apps"})
    kid = Device(r.json()["pairingUrl"])
    assert not any(read_on_the_computer(daemon).values())

    marked = owner.request(None, "_handler/remote/inbox_read", {"id": "m_owner"})
    assert (marked["id"], marked["read"]) == ("m_owner", True)
    assert read_on_the_computer(daemon) == {"m_owner": True, "m_kid": False, "m_other": False}
    again = owner.request(None, "_handler/remote/inbox_read", {"id": "m_owner"})
    assert again == marked  # twice: harmless
    assert kid.request(None, "_handler/remote/inbox_read", {"id": "m_kid"})["read"] is True

    refusals = [(kid, "m_other"), (kid, "nope"), (owner, "m_kid"), (owner, "nope")]
    for device, message_id in refusals:
        with pytest.raises(DeviceError) as refused:
            device.request(None, "_handler/remote/inbox_read", {"id": message_id})
        assert (refused.value.code, str(refused.value)) == (-32602, "-32602: no such message")
    assert read_on_the_computer(daemon) == {"m_owner": True, "m_kid": True, "m_other": False}
    assert [m["read"] for m in owner.request(None, "_handler/remote/inbox")["messages"]] == [
        False,
        True,
    ]  # newest first: the other, then the one marked
