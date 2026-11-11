"""Contract D conformance: the menu's Pinned, projects and apps mixed, in the person's order
(contract D.28)."""

import pytest

from ..support.daemon import Daemon
from .test_projects import create_project


def pins(daemon: Daemon) -> list[dict[str, str]]:
    with daemon.http() as c:
        return c.get("/v1/pins").json()["items"]


@pytest.mark.rule("project.only-the-first-is-pinned-by-itself", "pin.gone-with-what-it-pins")
def test_the_first_project_alone_is_pinned_by_itself(daemon: Daemon) -> None:
    assert pins(daemon) == []  # this module's own daemon: no project yet
    first = create_project(daemon, daemon.make_scope())
    second = create_project(daemon, daemon.make_scope())
    assert pins(daemon) == [{"kind": "project", "id": first["id"]}]
    with daemon.http() as c:
        assert c.delete(f"/v1/projects/{first['id']}").status_code == 204
        assert c.delete(f"/v1/projects/{second['id']}").status_code == 204
    assert pins(daemon) == []


@pytest.mark.rule("pin.only-what-exists", "pin.gone-with-what-it-pins")
def test_pins_are_the_persons_order_of_what_exists(daemon: Daemon) -> None:
    a = create_project(daemon, daemon.make_scope())
    b = create_project(daemon, daemon.make_scope())
    order = [{"kind": "project", "id": b["id"]}, {"kind": "project", "id": a["id"]}]
    with daemon.http() as c:
        r = c.put("/v1/pins", json={"items": order})
        assert r.status_code == 200 and r.json()["items"] == order
        assert pins(daemon) == order  # reordered: the whole list, as given

        for refused in (
            [*order, {"kind": "project", "id": "p_0000000000"}],  # no such project
            [{"kind": "app", "id": "chat"}],  # Chat is no app: it has its own menu entry
            [*order, order[0]],  # twice
        ):
            r = c.put("/v1/pins", json={"items": refused})
            assert r.status_code == 422, refused
        assert pins(daemon) == order  # nothing changed

        assert c.delete(f"/v1/projects/{b['id']}").status_code == 204
        assert pins(daemon) == order[1:]
        assert c.delete(f"/v1/projects/{a['id']}").status_code == 204
