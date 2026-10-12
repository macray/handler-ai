"""D.4: the network filter (the egress proxy's image, A.7) as handlerd shows and builds it. The fake
sandbox says it is built; with HANDLER_TEST_FAKE_NETWORK_FILTER=broken it is not and its build
fails, so what happens before it is built can be seen."""

import json
import time
from collections.abc import Iterator
from typing import Any

import pytest
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect

from handler_contracts import ACP_SUBPROTOCOL, BEARER_SUBPROTOCOL_PREFIX

from ..support.daemon import Daemon, start_daemon


@pytest.fixture(scope="module")
def unbuilt() -> Iterator[Daemon]:
    yield from start_daemon({"HANDLER_TEST_FAKE_NETWORK_FILTER": "broken"})


def _network_filter_builds(d: Daemon) -> list[dict[str, Any]]:
    with d.http() as c:
        return [b for b in c.get("/v1/builds").json() if b["target"] == "network-filter"]


def test_built_it_is_shown(daemon: Daemon) -> None:
    with daemon.http() as c:
        found = c.get("/v1/network-filter").json()
    assert found["imagePresent"] and found["builtAt"] and found["image"]
    assert _network_filter_builds(daemon) == []  # built: handlerd built nothing


def test_missing_handlerd_builds_it_as_it_starts(unbuilt: Daemon) -> None:
    with unbuilt.http() as c:
        assert c.get("/v1/network-filter").json()["imagePresent"] is False
    deadline = time.monotonic() + 30
    while not (builds := _network_filter_builds(unbuilt)) or builds[0]["state"] == "running":
        assert time.monotonic() < deadline
        time.sleep(0.2)
    assert builds[0]["state"] == "failed" and len(builds) == 1
    with unbuilt.http() as c:
        assert "STEP 1/2" in c.get(f"/v1/builds/{builds[0]['id']}/log").json()["text"]
        r = c.post("/v1/network-filter/rebuild")
        assert r.status_code == 202 and r.json()["target"] == "network-filter"


def test_missing_a_filtered_agent_does_not_start_and_says_why(unbuilt: Daemon) -> None:
    ad_hoc = unbuilt.create_ad_hoc("fake", unbuilt.make_scope(), network="filtered")
    protocols = [ACP_SUBPROTOCOL, BEARER_SUBPROTOCOL_PREFIX + unbuilt.token]
    with connect(ad_hoc["acpUrl"], subprotocols=protocols) as ws:  # ty: ignore[invalid-argument-type]
        ws.send(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}))
        with pytest.raises(ConnectionClosed) as closed:
            while True:
                ws.recv(timeout=30)
    assert closed.value.rcvd is not None
    assert "network filter is not built" in closed.value.rcvd.reason
    # an agent without network needs no filter
    offline = unbuilt.create_ad_hoc("fake", unbuilt.make_scope(), network="none")
    client = unbuilt.connect(offline["acpUrl"])
    try:
        client.initialize()
    finally:
        client.close()
