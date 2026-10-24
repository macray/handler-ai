"""D.26 through the Control API: the official source read (the test daemon's: the made-up
tests/fixtures/source/, committed), what it offers, an app taken from it, what cannot be done."""

from ..support.daemon import Daemon


def test_the_official_source_offers_what_handler_reviewed(daemon: Daemon) -> None:
    with daemon.http() as c:
        [official] = c.get("/v1/sources").json()
    assert (
        official["id"] == "official" and official["official"] and official["name"] == "Test source"
    )
    assert official["commit"] and "error" not in official
    items = {(i["kind"], i["name"]): i for i in official["items"]}
    assert [
        i for i in official["items"] if "error" in i
    ] == []  # each one valid, as Handler reads it
    assert (
        items[("addon", "fake-shop")]["installed"] and not items[("addon", "fake-shop")]["update"]
    )
    journal = items[("app", "journal")]
    assert journal["version"] and journal["description"] and "error" not in journal


def test_an_app_is_taken_from_a_source_then_its_next_version(daemon: Daemon) -> None:
    with daemon.http() as c:
        c.get("/v1/sources")
        first = c.post("/v1/sources/official/apps/journal")
        assert first.status_code == 201 and first.json()["fromSource"] == "official"
        [official] = c.get("/v1/sources").json()
        journal = next(i for i in official["items"] if i["name"] == "journal")
        assert journal["installed"] and not journal["update"]
        assert c.post("/v1/sources/official/apps/journal").status_code == 200  # the same again
        assert c.delete("/v1/apps/journal").status_code == 204


def test_what_a_source_refuses(daemon: Daemon) -> None:
    with daemon.http() as c:
        assert c.post("/v1/sources", json={"url": "http://example.com/x"}).status_code == 422
        assert c.delete("/v1/sources/official").status_code == 409
        assert c.post("/v1/sources/nope/refresh").status_code == 404
        missing = c.post("/v1/sources/official/agents/nope")
        assert (
            missing.status_code == 404 and "offers no agents named nope" in missing.json()["detail"]
        )
        refreshed = c.post("/v1/sources/official/refresh").json()
        assert refreshed["id"] == "official" and refreshed["items"]


def test_an_item_s_page_says_what_it_is_before_it_is_installed(daemon: Daemon) -> None:
    with daemon.http() as c:
        c.get("/v1/sources")
        journal = c.get("/v1/sources/official/apps/journal").json()
        assert journal["source"]["id"] == "official" and journal["source"]["items"] == []
        assert journal["app"]["name"] == "journal" and journal["readme"]
        assert {"text": "uses 1 folder of yours", "weakens": False} in journal["item"]["notes"]
        shop = c.get("/v1/sources/official/addons/fake-shop").json()
        assert shop["addon"]["image"] and shop["item"]["notes"][0]["weakens"]
        assert c.get("/v1/sources/official/things/journal").status_code == 404
        assert c.get("/v1/sources/official/apps/nope").status_code == 404
