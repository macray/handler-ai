"""Migrations: the user's files brought to the current format at handlerd's start, once each."""

import json
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from handler_contracts import AppManifest
from handler_control import migrations
from handler_control.agents import AgentRegistry
from handler_control.migrations import (
    m0001_agent_home,
    m0002_no_app_shortcuts,
    m0003_chat_and_handler_needs,
    m0004_apps,
    m0005_sources,
)
from handler_control.settings import Settings


def settings(tmp_path: Path) -> Settings:
    return Settings(
        port=0,
        config_dir=tmp_path / "config",
        state_dir=tmp_path / "state",
        data_dir=tmp_path / "data",
        bindings_dir=tmp_path / "config" / "bindings",
        allowed_origins=frozenset(),
        web_ui_dir=tmp_path,
    )


def test_each_migration_runs_once_in_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[str] = []
    monkeypatch.setattr(
        migrations, "MIGRATIONS", [lambda s: ran.append("a"), lambda s: ran.append("b")]
    )
    s = settings(tmp_path)
    migrations.run(s)
    assert ran == ["a", "b"] and migrations.current(s) == 2
    migrations.run(s)
    assert ran == ["a", "b"]


def test_only_the_new_ones_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[str] = []
    s = settings(tmp_path)
    migrations.write_version(s, 1)
    monkeypatch.setattr(
        migrations, "MIGRATIONS", [lambda s: ran.append("a"), lambda s: ran.append("b")]
    )
    migrations.run(s)
    assert ran == ["b"] and migrations.current(s) == 2


def test_a_failure_stops_and_keeps_the_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(s: Settings) -> None:
        raise ValueError("bad file")

    monkeypatch.setattr(migrations, "MIGRATIONS", [lambda s: None, broken])
    s = settings(tmp_path)
    with pytest.raises(migrations.MigrationError, match="migration 2 failed: bad file"):
        migrations.run(s)
    assert migrations.current(s) == 1


def test_files_of_a_newer_handler_are_refused(tmp_path: Path) -> None:
    s = settings(tmp_path)
    migrations.write_version(s, len(migrations.MIGRATIONS) + 1)
    with pytest.raises(migrations.MigrationError, match="newer Handler"):
        migrations.run(s)


def test_m0001_an_agent_s_home_is_stored(tmp_path: Path) -> None:
    s = settings(tmp_path)
    s.state_dir.mkdir(parents=True)
    (s.state_dir / "roles.json").write_text(json.dumps({"skill-review": "given"}))
    model = {"harness": "claude-code", "account": "perso"}

    def agent(aid: str, **extra: object) -> dict[str, object]:
        return {"id": aid, "model": model, "scope": None} | extra

    agents = [
        agent("chat"),
        agent("project", projectId="p1", scope="/home/me/code"),
        agent("folder", scope="/home/me/notes"),
        agent("part", origin="app:planner/plan", scope="/home/me/tasks"),
        agent("job", interface={"fields": {"type": "object"}}),
        agent("given"),
        agent("helper", origin="blueprint:skill-creator@1/skill-creator"),
        agent("mine", origin="blueprint:my-team@2/writer"),
    ]
    (s.state_dir / "agents.json").write_text(json.dumps(agents))

    m0001_agent_home.migrate(s)

    written = {a["id"]: a for a in json.loads((s.state_dir / "agents.json").read_text())}
    homes = {aid: (a.get("projectId"), a["app"]) for aid, a in written.items()}
    assert homes == {
        "chat": (None, "chat"),
        "project": ("p1", None),
        "folder": (None, None),
        "part": (None, "planner"),
        "job": (None, None),
        "given": (None, None),
        "helper": (None, None),
        "mine": (None, "chat"),  # set up from an agents file, a chat with no folder: Chat's
    }
    assert written["part"]["origin"] == {"kind": "app", "name": "planner", "agent": "plan"}
    assert written["helper"]["origin"]["kind"] == "blueprint"
    assert written["helper"]["origin"]["version"] == 1


def test_m0003_chat_has_its_own_home_and_blueprints_are_gone(tmp_path: Path) -> None:
    s = settings(tmp_path)
    s.state_dir.mkdir(parents=True)
    (s.state_dir / "roles.json").write_text(json.dumps({"skill-review": "helper"}))
    staged = s.state_dir / "agent-imports" / "my-team"
    staged.mkdir(parents=True)
    (staged / "blueprint.toml").write_text('name = "my-team"\nversion = 1\n')
    model = {"harness": "claude-code", "account": "perso"}

    def agent(aid: str, **extra: object) -> dict[str, object]:
        return {"id": aid, "model": model, "scope": None, "app": None} | extra

    agents = [
        agent("chat", app="chat"),
        agent("part", app="planner", origin={"kind": "app", "name": "planner", "agent": "plan"}),
        agent(
            "helper",
            origin={
                "kind": "blueprint",
                "name": "skill-review",
                "version": 1,
                "agent": "skill-review",
            },
        ),
        agent(
            "mine", origin={"kind": "blueprint", "name": "my-team", "version": 2, "agent": "writer"}
        ),
    ]
    (s.state_dir / "agents.json").write_text(json.dumps(agents))

    m0003_chat_and_handler_needs.migrate(s)

    registry = AgentRegistry(s.state_dir)  # the current format reads it
    homes = {a.id: (a.app, a.chat) for a in registry.agents.values()}
    assert homes == {
        "chat": (None, True),
        "part": ("planner", False),
        "helper": (None, False),
        "mine": (None, False),
    }
    helper, mine = registry.agents["helper"].origin, registry.agents["mine"].origin
    assert helper is not None and (helper.kind, helper.name, helper.agent) == (
        "handler-need",
        "skill-review",
        None,
    )
    assert mine is not None and (mine.kind, mine.version, mine.agent) == (
        "agents-file",
        2,
        "writer",
    )
    assert json.loads((s.state_dir / "handler-needs.json").read_text()) == {
        "skill-review": "helper"
    }
    assert not (s.state_dir / "roles.json").exists()
    assert (staged / "agents.toml").is_file() and not (staged / "blueprint.toml").exists()


GNOME = m0002_no_app_shortcuts.SCHEMA
BINDINGS = m0002_no_app_shortcuts.BASE


@pytest.fixture
def gnome(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """gsettings on a keyfile, with the part of GNOME's schema the shortcuts used: the person's
    own keybinding and the one Handler made for the app notes."""
    if not (shutil.which("gsettings") and shutil.which("glib-compile-schemas")):
        pytest.skip("gsettings not installed")
    schemas = tmp_path / "schemas"
    schemas.mkdir()
    shutil.copy(Path(__file__).parent / "fixtures" / f"{GNOME}.gschema.xml", schemas)
    subprocess.run(["glib-compile-schemas", str(schemas)], check=True)
    monkeypatch.setenv("GSETTINGS_SCHEMA_DIR", str(schemas))
    monkeypatch.setenv("GSETTINGS_BACKEND", "keyfile")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    ours = f"{GNOME}.custom-keybinding:{BINDINGS}handler-notes/"
    subprocess.run(["gsettings", "set", ours, "binding", "<Super>n"], check=True)
    listed = f"['{BINDINGS}custom0/', '{BINDINGS}handler-notes/']"
    subprocess.run(["gsettings", "set", GNOME, "custom-keybindings", listed], check=True)
    yield


def gsettings(*args: str) -> str:
    r = subprocess.run(["gsettings", *args], check=True, capture_output=True, text=True)
    return r.stdout.strip()


def test_app_shortcuts_are_removed(tmp_path: Path, gnome: None) -> None:
    s = settings(tmp_path)
    s.state_dir.mkdir(parents=True)
    apps = {"notes": {"shortcut": "<Super>n", "askable": True}, "coach": {"shortcut": None}}
    (s.state_dir / "apps.json").write_text(json.dumps({"apps": apps}))

    m0002_no_app_shortcuts.migrate(s)

    after = json.loads((s.state_dir / "apps.json").read_text())["apps"]
    assert after == {"notes": {"askable": True}, "coach": {}}
    assert gsettings("get", GNOME, "custom-keybindings") == f"['{BINDINGS}custom0/']"  # yours kept
    ours = f"{GNOME}.custom-keybinding:{BINDINGS}handler-notes/"
    assert gsettings("get", ours, "binding") == "''"


def test_app_shortcuts_without_gnome(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(m0002_no_app_shortcuts.shutil, "which", lambda _: None)
    s = settings(tmp_path)
    s.state_dir.mkdir(parents=True)
    apps = {"notes": {"shortcut": "<Super>n"}}
    (s.state_dir / "apps.json").write_text(json.dumps({"apps": apps}))

    m0002_no_app_shortcuts.migrate(s)  # the keybinding is left, said in the log: no failure

    assert json.loads((s.state_dir / "apps.json").read_text()) == {"apps": {"notes": {}}}


def test_m0004_apps_and_their_actions(tmp_path: Path) -> None:
    s = settings(tmp_path)
    old = (
        '# Planner\napiVersion = "handler.miniapp/v2"\nname = "planner"\nversion = "0.3.0"\n'
        '[asks.add]\ndescription = "Add"\nroute = "POST /api/asks/add"\n'
        '[asks.add.fields]\ntype = "object"\n'
    )
    for folder in ("source", "versions/1"):
        (s.data_dir / "apps" / "planner" / folder).mkdir(parents=True)
        (s.data_dir / "apps" / "planner" / folder / "app.toml").write_text(old)
    draft = s.state_dir / "sessions" / "s1" / "work"
    draft.mkdir(parents=True)
    (draft / "app.toml").write_text(old)
    s.bindings_dir.mkdir(parents=True)
    (s.bindings_dir / "miniapp.toml").write_text(
        'apiVersion = "handler.binding/v1"\naddon = "miniapp"\n'
    )
    model = {"harness": "claude-code", "account": "perso"}
    router = {
        "id": "r",
        "model": model,
        "scope": None,
        "instructions": "Pick which ask of which app does it, and fill that ask's form.\n{{asks}}",
        "interface": {
            "fields": {"type": "object", "required": ["said", "asks"], "properties": {
                "said": {"type": "string"}, "asks": {"type": "string"}}},
            "result": {"type": "object", "required": ["status", "summary"], "properties": {
                "status": {"enum": ["ok"]}, "summary": {"type": "string"},
                "ask": {"type": "string", "title": "Ask"}}},
        },
        "origin": {"kind": "handler-need", "name": "ask-router", "version": 1},
    }  # fmt: skip
    creator = {"id": "c", "model": model, "scope": None, "bindings": ["miniapp"]}
    (s.state_dir / "agents.json").write_text(json.dumps([router, creator]))

    m0004_apps.migrate(s)

    for path in (*(s.data_dir / "apps" / "planner").glob("**/app.toml"), draft / "app.toml"):
        read = AppManifest.from_toml(path.read_text())  # the current format reads it
        assert read.actions["add"].route == "POST /api/asks/add"  # the app's own path
    assert not (s.bindings_dir / "miniapp.toml").exists()
    assert 'addon = "app-builder"' in (s.bindings_dir / "app-builder.toml").read_text()
    registry = AgentRegistry(s.state_dir)
    assert registry.agents["c"].bindings == ["app-builder"]
    r = registry.agents["r"]
    assert r.origin is not None and r.origin.version == 2 and r.interface is not None
    assert r.interface.fields is not None and r.interface.result is not None
    assert r.interface.fields["required"] == ["said", "actions"]
    assert "action" in r.interface.result["properties"]
    assert r.instructions == (
        "Pick which action of which app does it, and fill that action's form.\n{{actions}}"
    )


def test_m0005_what_handler_shipped_comes_from_its_official_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HANDLER_ADDONS_DIR", str(tmp_path / "config" / "addons"))
    s = settings(tmp_path)
    lock = tmp_path / "config" / "addons.lock.toml"
    lock.parent.mkdir(parents=True)
    lock.write_text(
        '[addons.shopify]\nsource = "catalog:shopify"\ndigest = "d"\n'
        '[addons.notes]\nsource = "/home/me/notes"\ndigest = "e"\n'
    )
    s.state_dir.mkdir()
    apps = {"planner": {"fromHandler": True, "files": {}}, "notes": {"fromHandler": False}}
    (s.state_dir / "apps.json").write_text(json.dumps({"apps": apps}))
    m0005_sources.migrate(s)
    assert 'source = "source:official/shopify"' in lock.read_text()
    assert 'source = "/home/me/notes"' in lock.read_text()
    migrated = json.loads((s.state_dir / "apps.json").read_text())["apps"]
    assert migrated == {"planner": {"files": {}, "fromSource": "official"}, "notes": {}}
    m0005_sources.migrate(settings(tmp_path / "nothing"))  # no file: nothing to do
