"""Contract D conformance: the web UI's event stream (contract D.30)."""

from ..support.daemon import Daemon


def test_the_event_stream_is_the_owner_s(daemon: Daemon) -> None:
    """If this fails: the web UI's pages never learn of a change, or anyone may follow them."""
    with daemon.http(token=None) as c:
        assert c.get("/v1/events").status_code == 401
    with daemon.http() as c, c.stream("GET", "/v1/events") as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        assert next(r.iter_lines()) == "retry: 2000"


def test_a_change_made_through_the_api_tells_its_area(daemon: Daemon) -> None:
    """Another tab, the CLI, an editor: what they change is told to every open page.

    If this fails: a page shows what another tab changed only once reloaded."""
    with daemon.http() as c, c.stream("GET", "/v1/events") as r:
        lines = r.iter_lines()
        assert next(lines) == "retry: 2000"
        with daemon.http() as other:
            assert other.put("/v1/pins", json={"items": []}).status_code == 200
        assert next(line for line in lines if line) == "data: pins"
