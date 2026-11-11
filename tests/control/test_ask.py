"""D.24 conformance, Ask over HTTP: what a request may hold (the exchange, the person's words
last), and an ask with no app offered, answered without running the router."""

import pytest

from ..support.daemon import Daemon


def said(*turns: tuple[str, str]) -> dict[str, list[dict[str, str]]]:
    return {"turns": [{"who": who, "text": text} for who, text in turns]}


@pytest.mark.rule("ask.keeps-no-exchange")
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
