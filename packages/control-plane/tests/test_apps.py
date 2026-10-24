"""Unit tests: apps (contract H) — manifest, sandbox spec, snapshot, app files (H.15),
links and cookies. The daemon running real apps is tests/apps."""

import io
import json
import re
import tomllib
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from source_repo import TEST_SOURCE

from handler_contracts import (
    APP_CODE_DIR,
    APP_SOCKET,
    RUNTIME_IMAGE,
    RUNTIME_VERSION,
    AppManifest,
    AppManifestNeeds,
    FilteredNetwork,
    NoNetwork,
    SandboxSpec,
)
from handler_control import compose
from handler_control.agents import AgentRegistry
from handler_control.app_runs import AppRuns
from handler_control.apps import AppError, AppStore, DeployError, Deployment, snapshot
from handler_control.inbox import Inbox
from handler_control.projects import ProjectRegistry
from handler_control.sessions import SessionStore
from handler_control.settings import Settings
from handler_harness import addons

BUILDER = addons.BUILTIN_DIR / "app-builder"
TEMPLATE = BUILDER / "skills" / "app-builder" / "template"


def manifest(**overrides: Any) -> AppManifest:
    data = {"apiVersion": "handler.app/v1", "name": "notes", "version": "0.1.0"} | overrides
    return AppManifest.model_validate(data)


# ── manifest ────────────────────────────────────────────────────────────


def test_defaults() -> None:
    m = manifest()
    assert (m.server.entry, m.server.dir, m.ui.dir) == ("server/main.ts", "server", "ui/dist")
    assert m.needs.egress == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"name": "Notes"},  # not a DNS label
        {"name": "a" * 31},
        {"version": "1.0"},
        {"server": {"entry": "main.ts"}},  # the whole folder would be installed
        {"server": {"entry": "../main.ts"}},
        {"ui": {"dir": "/srv/ui"}},
        {"ui": {"dir": "server/public"}},  # overlaps the backend's directory
        {"needs": {"egress": ["example.com"]}},  # no port
        {"needs": {"secrets": ["api_key"]}},  # env var names in capitals
        {"needs": {"secrets": ["HANDLER_APP_DATA"]}},  # set by handler
        {"needs": {"secrets": ["BUN_RUNTIME_TRANSPILER_CACHE_PATH"]}},
        {"needs": {"secrets": ["HTTPS_PROXY"]}},
        {"needs": {"unknown": ["x"]}},  # unknown keys are errors: nothing asked is ignored
        {"typo": 1},
        {"actions": {"add": {"description": "Add"}}},  # done by nothing
        {"actions": {"add": {"description": "Add", "route": "POST /api/a", "agent": "x"}}},  # both
        {"actions": {"add": {"description": "Add", "route": "GET /api/a"}}},  # a POST
        {"actions": {"plan": {"description": "Plan", "agent": "nope"}}},  # no such agents need
        {"actions": {"add": {"description": "", "route": "POST /api/a"}}},
    ],
)
def test_invalid(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        manifest(**overrides)


def test_added_needs() -> None:
    m = manifest(needs={"egress": ["a.example.com:443", "b.example.com:443"], "secrets": ["K"]})
    before = AppManifestNeeds(egress=["a.example.com:443"])
    assert m.added_needs(before) == ["egress b.example.com:443", "secret K"]
    assert m.added_needs(m.needs) == []
    assert m.added_needs(None) == [
        "egress a.example.com:443", "egress b.example.com:443", "secret K",
    ]  # fmt: skip


def test_template_manifest_is_valid() -> None:
    m = AppManifest.from_toml((TEMPLATE / "app.toml").read_text())
    assert (TEMPLATE / m.server.entry).is_file()


def test_the_default_toolbox_has_the_runtime_bun_version() -> None:
    """A new toolbox starts with the Bun apps run on (the person may change it: only its presence
    is checked, B.6)."""
    containerfile = (addons.BUILTIN_DIR.parent / "toolbox" / "Containerfile").read_text()
    m = re.search(r"ARG BUN_VERSION=bun-v([0-9.]+)", containerfile)
    assert m and m[1] == RUNTIME_VERSION


# ── sandbox spec (H.3) ──────────────────────────────────────────────────


def spec(m: AppManifest, test: bool = False) -> SandboxSpec:
    return compose.app_sandbox_spec(
        name="handler-app-notes-1", manifest=m, code="/c", data="/d/data", run="/r", test=test
    )


def test_spec_is_offline_and_read_only() -> None:
    s = spec(manifest())
    assert s.image == RUNTIME_IMAGE
    assert s.confinement == "strict"
    assert isinstance(s.network, NoNetwork)
    mounts = {m.target: (m.source, m.read_only) for m in s.mounts}
    assert mounts == {
        "/d/data": ("/d/data", False),
        APP_CODE_DIR: ("/c", True),
        "/run/handler-app": ("/r", False),
    }
    assert s.workdir == "/d/data"
    assert s.argv == ["run", "--no-install", "--no-env-file", f"{APP_CODE_DIR}/server/main.ts"]
    assert s.env["HANDLER_APP_SOCKET"] == APP_SOCKET and s.env["HANDLER_APP_DATA"] == "/d/data"
    assert s.resources and s.resources.memory == "512m"


def test_spec_with_folders_names_them_by_need() -> None:
    m = manifest(needs={"files": {"tasks": {"mode": "rw"}, "notes": {}}})
    files = [("tasks", "/h/planner", True), ("notes", "/h/notes.md", False)]
    s = compose.app_sandbox_spec(
        name="handler-app-notes-1", manifest=m, code="/c", data="/d/data", run="/r", files=files
    )
    assert json.loads(s.env["HANDLER_APP_FILES"]) == {"tasks": "/h/planner", "notes": "/h/notes.md"}
    mounts = {m.target: m.read_only for m in s.mounts}
    assert (mounts["/h/planner"], mounts["/h/notes.md"]) == (False, True)


def test_spec_with_egress() -> None:
    s = spec(manifest(needs={"egress": ["api.example.com:443"]}))
    assert isinstance(s.network, FilteredNetwork)
    assert s.network.allow == ["api.example.com:443"] and s.network.enforcement == "enforce"


def test_test_spec() -> None:
    s = spec(manifest(), test=True)
    assert s.argv[0] == "test" and s.argv[-1] == f"{APP_CODE_DIR}/server"
    assert "--no-install" in s.argv and "--pass-with-no-tests" in s.argv


def test_secrets_go_to_the_backend_not_to_tests() -> None:
    m = manifest(needs={"secrets": ["API_KEY"]})

    def build(test: bool) -> SandboxSpec:
        return compose.app_sandbox_spec(
            name="n",
            manifest=m,
            code="/c",
            data="/d",
            run="/r",
            secrets={"API_KEY": "v"},
            test=test,
        )

    assert build(test=False).env["API_KEY"] == "v"
    tested = build(test=True)
    assert "API_KEY" not in tested.env
    assert all(a != "v" for a in tested.argv)


# ── snapshot (H.6) ──────────────────────────────────────────────────────


def app_folder(root: Path) -> Path:
    src = root / "src"
    (src / "server").mkdir(parents=True)
    (src / "server" / "main.ts").write_text("// main\n")
    (src / "ui" / "dist").mkdir(parents=True)
    (src / "ui" / "dist" / "index.html").write_text("<!doctype html>")
    (src / "ui" / "src").mkdir()
    (src / "ui" / "src" / "App.svelte").write_text("<p>source</p>")
    (src / "app.toml").write_text(
        'apiVersion = "handler.app/v1"\nname = "notes"\nversion = "0.1.0"\n'
    )
    return src


def zipped(folder: Path, top: str = "") -> bytes:
    """The app file of a folder (H.15), its files at the root or in one folder `top`."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                zf.write(path, top + path.relative_to(folder).as_posix())
    return buffer.getvalue()


def test_snapshot_copies_only_what_is_installed(tmp_path: Path) -> None:
    src = app_folder(tmp_path)
    (src / "server" / "link.ts").symlink_to("main.ts")  # inside: kept as a link
    snapshot(src, tmp_path / "v1", AppManifest.from_toml((src / "app.toml").read_text()))
    copied = sorted(str(p.relative_to(tmp_path / "v1")) for p in (tmp_path / "v1").rglob("*"))
    assert copied == [
        "app.toml", "server", "server/link.ts", "server/main.ts",
        "ui", "ui/dist", "ui/dist/index.html",
    ]  # fmt: skip
    assert (tmp_path / "v1" / "server" / "link.ts").is_symlink()


@pytest.mark.parametrize("where", ["ui/dist/leak.txt", "server/leak.ts"])
def test_snapshot_refuses_links_outside(tmp_path: Path, where: str) -> None:
    src = app_folder(tmp_path)
    (tmp_path / "secret").write_text("key")
    (src / where).symlink_to(tmp_path / "secret")
    m = AppManifest.from_toml((src / "app.toml").read_text())
    with pytest.raises(DeployError, match="link to outside"):
        snapshot(src, tmp_path / "v1", m)


def test_snapshot_needs_a_built_ui(tmp_path: Path) -> None:
    src = app_folder(tmp_path)
    (src / "ui" / "dist" / "index.html").unlink()
    with pytest.raises(DeployError, match="build the UI"):
        snapshot(src, tmp_path / "v1", AppManifest.from_toml((src / "app.toml").read_text()))


# ── links and cookies (H.4) ─────────────────────────────────────────────


def store(tmp_path: Path) -> AppStore:
    settings = Settings(
        port=7430,
        config_dir=tmp_path / "config",
        state_dir=tmp_path / "state",
        bindings_dir=tmp_path / "bindings",
        allowed_origins=frozenset(),
        web_ui_dir=tmp_path / "ui",
        data_dir=tmp_path / "data",
    )
    inbox, registry = Inbox(settings), AgentRegistry(settings.state_dir)
    sessions = SessionStore(settings, registry)
    runs = AppRuns(settings, sessions, ProjectRegistry(settings.state_dir, registry), inbox)
    return AppStore(settings, token="t0ken", inbox=inbox, runs=runs)


def test_link_is_one_time_and_per_app(tmp_path: Path) -> None:
    s = store(tmp_path)
    s.add_file(zipped(app_folder(tmp_path)))
    s.records["notes"].deployments.append(Deployment(1, "0.1.0", datetime.now(UTC)))
    url = s.open_link("notes")
    assert url.startswith("http://notes.localhost:7430/_handler/login?code=")
    code = url.split("code=")[1]
    assert not s.redeem("other", code)  # a code opens its own app only, and is spent
    url = s.open_link("notes")
    code = url.split("code=")[1]
    assert s.redeem("notes", code)
    assert not s.redeem("notes", code)


def test_cookie_is_per_app_and_per_token(tmp_path: Path) -> None:
    s = store(tmp_path)
    assert s.cookie_matches("notes", s.cookie("notes"))
    assert not s.cookie_matches("notes", s.cookie("other"))
    assert not s.cookie_matches("notes", None)
    other = AppStore(s.settings, token="another", inbox=s.inbox, runs=s.runs)
    assert not other.cookie_matches("notes", s.cookie("notes"))


def test_registry_survives_a_restart(tmp_path: Path) -> None:
    s = store(tmp_path)
    record, new = s.add_file(zipped(app_folder(tmp_path)))
    assert new and record.name == "notes"
    assert (tmp_path / "data" / "apps" / "notes" / "data").is_dir()
    again = AppStore(s.settings, token="t0ken", inbox=s.inbox, runs=s.runs)
    assert "notes" in again.records and again.records["notes"].from_source is None
    source = tmp_path / "data" / "apps" / "notes" / "source"
    assert tomllib.loads((source / "app.toml").read_text())["name"] == "notes"


def test_an_app_file_is_its_code_kept_by_handler(tmp_path: Path) -> None:
    """Its code is Handler's copy: the folder it came from can go; the file of an app you have
    is its next version; one folder at the zip's root is the app's; its export is the code."""
    s = store(tmp_path)
    folder = app_folder(tmp_path)
    s.add_file(zipped(folder, top="notes-0.1.0/"))
    source = tmp_path / "data" / "apps" / "notes" / "source"
    assert (source / "ui" / "src" / "App.svelte").read_text() == "<p>source</p>"
    (folder / "app.toml").write_text((folder / "app.toml").read_text().replace("0.1.0", "0.2.0"))
    _, new = s.add_file(zipped(folder))
    assert not new and s.view("notes").source.version == "0.2.0"
    name, data = s.export("notes")
    assert name == "notes-0.2.0.zip"
    assert "ui/src/App.svelte" in zipfile.ZipFile(io.BytesIO(data)).namelist()
    for bad, why in [(b"nope", "not an app file"), (zipped(folder / "ui"), "no app.toml")]:
        with pytest.raises(AppError, match=why):
            s.add_file(bad)


def test_an_app_file_over_one_from_a_source_makes_it_yours(tmp_path: Path) -> None:
    s = store(tmp_path)
    s.add_from_source("official", TEST_SOURCE / "apps" / "journal")
    _, data = s.export("journal")
    s.add_file(data)
    assert s.view("journal").from_source is None


# ── from a source (D.26) ────────────────────────────────────────────────


def test_an_app_from_a_source_is_a_copy_that_keeps_its_source(tmp_path: Path) -> None:
    s = store(tmp_path)
    record, new = s.add_from_source("official", TEST_SOURCE / "apps" / "journal")
    copy = tmp_path / "data" / "apps" / "journal" / "source"
    assert new and record.from_source == "official" and (copy / "app.toml").is_file()
    assert s.view("journal").from_source == "official"
    assert s.view("journal").source.version == manifest_version(TEST_SOURCE / "apps" / "journal")
    _, new = s.add_from_source("official", TEST_SOURCE / "apps" / "journal")
    assert not new  # its next version
    again = AppStore(s.settings, token="t0ken", inbox=s.inbox, runs=s.runs)
    assert again.records["journal"].from_source == "official"


def test_a_source_never_replaces_an_app_from_elsewhere(tmp_path: Path) -> None:
    """Only the source an app came from gives it a next version: another source offering an app
    of that name, or any source once the app is yours, would replace its code with a stranger's."""
    s = store(tmp_path)
    s.add_from_source("official", TEST_SOURCE / "apps" / "journal")
    with pytest.raises(AppError, match="from the source official: remove it first"):
        s.add_from_source("acme", TEST_SOURCE / "apps" / "journal")
    _, data = s.export("journal")
    s.add_file(data)  # yours from now on
    with pytest.raises(AppError, match="journal, yours: remove it first"):
        s.add_from_source("official", TEST_SOURCE / "apps" / "journal")
    assert s.view("journal").from_source is None


def test_an_app_named_other_than_its_folder_is_refused(tmp_path: Path) -> None:
    s = store(tmp_path)
    folder = app_folder(tmp_path)
    renamed = folder.rename(folder.parent / "other")
    with pytest.raises(AppError, match="names another app, notes"):
        s.add_from_source("acme", renamed)


def test_an_app_of_yours_comes_from_no_source(tmp_path: Path) -> None:
    s = store(tmp_path)
    s.add_file(zipped(app_folder(tmp_path)))
    assert s.view("notes").from_source is None


def manifest_version(folder: Path) -> str:
    return AppManifest.from_toml((folder / "app.toml").read_text()).version
