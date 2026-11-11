"""D.26 through the Control API: the official source read (the test daemon's: the made-up
tests/fixtures/source/, committed), what it offers, an app taken from it, what cannot be done."""

from pathlib import Path

import pytest
from dulwich import porcelain

from ..support.daemon import Daemon


@pytest.mark.rule("source.each-item-by-its-kind-s-rules")
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


@pytest.mark.rule("source.never-over-an-app-from-elsewhere")
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


@pytest.mark.rule("source.added-once-read")
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


@pytest.mark.rule("source.each-item-by-its-kind-s-rules")
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


def _commit(repo: Path, changes: dict[str, str]) -> None:
    """A commit to the source's repository: each file's new text."""
    for path, text in changes.items():
        (repo / path).write_text(text)
    with porcelain.open_repo_closing(str(repo)) as r:
        porcelain.add(r, [str(repo / p) for p in changes])
        porcelain.commit(r, b"next", author=b"t <t@t>", committer=b"t <t@t>")


@pytest.mark.rule("source.only-offers")
def test_a_new_commit_is_offered_never_applied(daemon: Daemon) -> None:
    """The source's next commit changes an app taken from it and an addon installed from it:
    read again, both stay as they are, each offered as an update.

    If this fails: a commit to a repository you added changes an app or an addon you use."""
    repo = daemon.config_dir.parent / "official-source"
    app_toml, addon_toml = "apps/journal/app.toml", "tools/fake-shop/tool.toml"
    before = {p: (repo / p).read_text() for p in (app_toml, addon_toml)}
    with daemon.http() as c:
        c.get("/v1/sources")
        assert c.post("/v1/sources/official/apps/journal").status_code == 201
        version = c.get("/v1/apps/journal").json()["source"]["version"]
        installed = (daemon.config_dir / "tools" / "fake-shop" / "tool.toml").read_text()
        try:
            _commit(
                repo,
                {
                    app_toml: before[app_toml].replace(f'"{version}"', '"9.9.9"'),
                    addon_toml: before[addon_toml].replace("for the tests", "changed upstream"),
                },
            )
            items = {i["name"]: i for i in c.post("/v1/sources/official/refresh").json()["items"]}
            assert items["journal"]["update"] and items["fake-shop"]["update"]
            assert c.get("/v1/apps/journal").json()["source"]["version"] == version
            kept = daemon.config_dir / "tools" / "fake-shop" / "tool.toml"
            assert kept.read_text() == installed
        finally:
            _commit(repo, before)
            c.post("/v1/sources/official/refresh")
            c.delete("/v1/apps/journal")


@pytest.mark.rule("source.each-item-by-its-kind-s-rules")
def test_agents_whose_file_has_no_name_are_listed_with_why_never_offered(daemon: Daemon) -> None:
    """An `agents.toml` without its `name` cannot be set up (D.23): Discover lists it with that
    error instead of offering a *Set up…* that fails.

    If this fails: Discover offers agents that its set-up then refuses."""
    repo = daemon.config_dir.parent / "official-source"
    meta = "agents/helpers/agents.toml"
    before = (repo / meta).read_text()
    with daemon.http() as c:
        c.get("/v1/sources")
        try:
            _commit(repo, {meta: before.replace('name = "helpers"\n', "")})
            items = c.post("/v1/sources/official/refresh").json()["items"]
            helpers = next(i for i in items if (i["kind"], i["name"]) == ("agents", "helpers"))
            assert "its name '' is not one" in helpers["error"]
            page = c.get("/v1/sources/official/agents/helpers").json()
            assert page["item"]["error"] == helpers["error"] and "agents" not in page
        finally:
            _commit(repo, {meta: before})
            c.post("/v1/sources/official/refresh")
