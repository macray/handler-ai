"""H.17 over HTTP: a nudge dismissed, its page opened, its form filled, an app's nudge toned;
what names no nudge is not found. What a nudge does is unit-tested (test_nudges.py)."""

import pytest

from ..support.daemon import Daemon


@pytest.mark.rule("nudge.open-until-done-dismissed-or-expired")
def test_what_names_no_nudge_is_not_found(daemon: Daemon) -> None:
    with daemon.http() as c:
        assert c.post("/v1/inbox/nope/dismiss").status_code == 404
        assert c.post("/v1/inbox/nope/open").status_code == 404
        assert c.post("/v1/inbox/nope/fill", json={"said": "I did it"}).status_code == 404
        assert c.post("/v1/inbox/nope/fill", json={"said": ""}).status_code == 422
        r = c.put("/v1/apps/nope/nudges/daily", json={"setting": "once"})
        assert r.status_code == 404
        r = c.put("/v1/apps/nope/nudges/daily", json={"setting": "less"})  # not a setting now
        assert r.status_code == 422
        assert c.put("/v1/apps/nope/nudges/daily/off", json={"off": True}).status_code == 404
        r = c.put("/v1/apps/nope/nudges/daily", json={"setting": "loud"})
        assert r.status_code == 422
        r = c.put("/v1/apps/nope/nudges/daily/when", json={"when": {"at": "09:00"}})
        assert r.status_code == 404
        r = c.put("/v1/apps/nope/nudges/daily/when", json={"when": {"at": "9h"}})
        assert r.status_code == 422
