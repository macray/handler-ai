"""D.24 conformance, Ask over HTTP: what a request may hold (the exchange, the person's words
last), an ask with no app offered, answered without running the router, and Ask's history."""

import pytest

from ..support.daemon import Daemon


def said(*turns: tuple[str, str]) -> dict[str, list[dict[str, str]]]:
    return {"turns": [{"who": who, "text": text} for who, text in turns]}


@pytest.mark.rule("ask.the-client-sends-the-whole-exchange")
def test_the_exchange_ends_with_your_words(daemon: Daemon) -> None:
    with daemon.http() as c:
        r = c.post("/v1/ask", json=said(("you", "Call the bank"), ("handler", "Which day?")))
        assert r.status_code == 400 and r.json()["title"] == "the last turn is yours"
        assert c.post("/v1/ask", json=said(*[("you", "again")] * 21)).status_code == 422
        assert c.post("/v1/ask", json=said(("you", "x" * 2001))).status_code == 422
        assert c.post("/v1/ask", json={"turns": []}).status_code == 422


@pytest.mark.rule("ask.only-the-actions-offered")
def test_with_no_app_offered_the_router_is_not_run(daemon: Daemon) -> None:
    with daemon.http() as c:
        r = c.post("/v1/ask", json=said(("you", "Tomorrow I call the bank at 10")))
        assert r.status_code == 200, r.text
        assert (r.json()["kind"], r.json()["actions"]) == ("none", [])
        assert "routerRun" not in r.json()
        assert c.get("/v1/sessions").json() == []  # no run of any router


@pytest.mark.rule("ask.each-ask-is-kept", "ask.a-failure-is-told", "ask.history-yours-to-turn-off")
def test_each_ask_is_in_its_history_and_one_no_app_does_in_the_inbox(daemon: Daemon) -> None:
    """Over HTTP: an ask from a key is kept with where it came from and how it ended, told to
    the inbox when no app does it; deleted one by one, or turned off (emptied)."""
    with daemon.http() as c:
        assert c.delete("/v1/ask/history").status_code == 204  # the other tests' asks
        r = c.post("/v1/ask", json=said(("you", "Call the bank")) | {"via": "key"})
        assert r.status_code == 200, r.text
        kept = c.get("/v1/ask/history").json()
        assert kept["keep"] is True
        (ask,) = kept["asks"]
        said_then = (ask["via"], ask["outcome"], ask["turns"][0]["text"])
        assert said_then == ("key", "none", "Call the bank")
        inbox = c.get("/v1/inbox").json()
        assert any(m["source"] == "ask" and "Call the bank" in m["summary"] for m in inbox)
        assert c.delete(f"/v1/ask/history/{ask['id']}").status_code == 204
        assert c.delete(f"/v1/ask/history/{ask['id']}").status_code == 404
        c.post("/v1/ask", json=said(("you", "Call the bank")))
        assert c.put("/v1/ask/history", json={"keep": False}).json() == {"keep": False, "asks": []}
        c.post("/v1/ask", json=said(("you", "Call the bank")))
        assert c.get("/v1/ask/history").json()["asks"] == []
