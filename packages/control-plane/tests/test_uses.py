"""Unit tests: what uses what (D.22), read from the stores as they are: the links an
automation, an app, Handler's helpers, a provider and a project's addon make, each seen from both
ends. The stores are stand-ins holding only what `UseGraph` reads; an agent's skills, knowledge and
account are tested through a real handlerd (tests/control/test_uses.py)."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from handler_contracts import UseKind
from handler_control import handler_needs
from handler_control.settings import Settings
from handler_control.uses import UseGraph


def an_agent(ident: str, name: str, **more: Any) -> SimpleNamespace:
    fields: dict[str, Any] = {
        "id": ident, "name": name, "scope": None, "project_id": None, "model_alone": False,
        "skills": [], "project_skills": [], "knowledge": [], "addons": [], "project_addons": [],
        "model": SimpleNamespace(account="fake", provider=None),
    }  # fmt: skip
    return SimpleNamespace(**(fields | more))


@pytest.fixture
def graph(tmp_path: Path) -> UseGraph:
    settings = Settings(
        port=0, config_dir=tmp_path, state_dir=tmp_path / "state", bindings_dir=tmp_path,
        allowed_origins=frozenset(), web_ui_dir=tmp_path,
    )  # fmt: skip
    project = SimpleNamespace(id="p1", name="shop", skills=[], addons=[SimpleNamespace(addon="db")])
    agents = {
        "a1": an_agent("a1", "sorter"),
        "a2": an_agent("a2", "local", model=SimpleNamespace(account=None, provider="llamacpp")),
        "a3": an_agent("a3", "dev", project_id="p1", project_addons=[SimpleNamespace(addon="db")]),
        "a4": an_agent("a4", "keeper"),
        "a5": an_agent("a5", "writer"),
    }
    registry = SimpleNamespace(agents=agents, get=agents.get)
    projects = SimpleNamespace(registry=registry, projects={"p1": project}, get={"p1": project}.get)
    morning = SimpleNamespace(
        name="morning",
        agent_id="a1",
        only_agents=["a3"],
        definition=SimpleNamespace(append=[SimpleNamespace(to="acme/log/notes.md")]),
    )
    automations = SimpleNamespace(views=lambda: [morning])
    need = SimpleNamespace(agent_id="a4", description="Sorts your things", name="keeper")
    apps = SimpleNamespace(views=lambda: [SimpleNamespace(name="keeper", agents=[need])])
    settings.state_dir.mkdir(parents=True)
    handler_needs.give(settings.state_dir, "prompt-writer", "a5")
    return UseGraph(settings, cast(Any, projects), cast(Any, automations), cast(Any, apps))


def links(graph: UseGraph, kind: UseKind, ident: str, side: str) -> set[tuple[str, str, str]]:
    found = graph.of(kind, ident)
    refs = found.uses if side == "uses" else found.used_by
    return {(r.kind, r.id, r.how) for r in refs}


@pytest.mark.rule("uses.seen-from-both-ends")
@pytest.mark.parametrize(
    ("user", "used", "how"),
    [
        pytest.param(("automation", "morning"), ("agent", "a1"), "runs it", id="automation-agent"),
        pytest.param(
            ("automation", "morning"),
            ("agent", "a3"),
            "runs when its sessions stop",
            id="automation-on-an-agent-s-sessions",
        ),
        pytest.param(
            ("automation", "morning"),
            ("knowledge", "acme/log"),
            "appends to acme/log/notes.md",
            id="automation-notes",
        ),
        pytest.param(
            ("app", "keeper"), ("agent", "a4"), "needs it: Sorts your things", id="app-s-agent"
        ),
        pytest.param(
            ("handler", "prompt-writer"),
            ("agent", "a5"),
            "its prompt writer",
            id="handler-s-helper",
        ),
        pytest.param(("agent", "a2"), ("provider", "llamacpp"), "runs on it", id="provider"),
        pytest.param(
            ("project", "p1"), ("addon", "db"), "gives it to all its agents", id="project-s-addon"
        ),
        pytest.param(
            ("agent", "a3"),
            ("addon", "db"),
            "given by its project",
            id="addon-given-by-the-project",
        ),
    ],
)
def test_each_link_is_seen_from_both_ends(
    graph: UseGraph, user: tuple[UseKind, str], used: tuple[UseKind, str], how: str
) -> None:
    """If this fails: a page says nobody uses a thing while something does, or the other way."""
    assert (*used, how) in links(graph, *user, "uses")
    assert (*user, how) in links(graph, *used, "usedBy")


@pytest.mark.rule("uses.seen-from-both-ends")
def test_a_knowledge_folder_stands_for_the_folders_in_it(graph: UseGraph) -> None:
    """Notes appended in `acme/log` are a use of `acme` and of the root, not of `acm`.

    If this fails: a folder's page says nothing writes into it while an automation does."""
    appends = ("automation", "morning", "appends to acme/log/notes.md")
    assert appends in links(graph, "knowledge", "acme", "usedBy")
    assert appends in links(graph, "knowledge", ".", "usedBy")
    assert links(graph, "knowledge", "acm", "usedBy") == set()
