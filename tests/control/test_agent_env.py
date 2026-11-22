"""An agent's own environment variables (contract D.8), through a real handlerd: they reach its
sandbox, and never set what Handler, its harness or its tools set.

The agent is the fake agent on the host (the fake sandbox): it reports the MY_FLAG it got.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from ..support.daemon import Daemon


def seen_flag(daemon: Daemon, agent: dict[str, Any], scope: Path) -> str | None:
    client = daemon.connect(agent["acpUrl"])
    try:
        client.initialize()
        session = client.new_session(str(scope))["sessionId"]
        client.prompt(session, "report")
        return json.loads(client.text())["myFlag"]
    finally:
        client.close()


@pytest.mark.rule("agent.its-env-reaches-each-start")
def test_its_variables_reach_its_sandbox(daemon: Daemon) -> None:
    scope = daemon.make_scope()
    plain = daemon.create_ad_hoc("fake", scope)
    flagged = daemon.create_ad_hoc("fake", scope, name="flagged", env={"MY_FLAG": "1"})
    assert plain["env"] == {} and flagged["env"] == {"MY_FLAG": "1"}
    assert seen_flag(daemon, plain, scope) is None
    assert seen_flag(daemon, flagged, scope) == "1"


@pytest.mark.rule("agent.its-env-never-sets-what-others-own")
def test_what_others_set_is_refused_when_saved(daemon: Daemon) -> None:
    scope = str(daemon.make_scope())
    body = {"model": {"account": "fake"}, "scope": scope}
    with daemon.http() as c:
        for name in ("HTTP_PROXY", "http_proxy", "HOME", "SSL_CERT_FILE", "TERM", "DISPLAY"):
            r = c.post("/v1/agents", json=body | {"env": {name: "x"}})
            assert r.status_code == 422 and "set by Handler" in r.text, (name, r.text)
        r = c.post("/v1/agents", json=body | {"env": {"FAKE_TOKEN": "x"}})  # its login's
        assert r.status_code == 400, r.text
        assert r.json()["title"] == "environment variables taken"
        assert r.json()["detail"] == "FAKE_TOKEN is set by Fake"
        browser = [{"addon": "fake-browser", "binding": "browser"}]
        taken = {"HANDLER_FAKE_BROWSER_HEADLESS": "1"}  # the tool's setting
        r = c.post("/v1/agents", json=body | {"addons": browser, "env": taken})
        assert r.status_code == 400, r.text
        assert "is set by the tool fake-browser" in r.json()["detail"]
        project = {"folder": str(daemon.make_scope()), "addons": browser}
        agent = {"name": "Dev", "model": {"account": "fake"}, "env": taken}
        r = c.post("/v1/projects", json=project | {"agents": [agent]})  # given by its project
        assert r.status_code == 400 and "fake-browser" in r.text, r.text
