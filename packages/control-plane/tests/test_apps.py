"""Unit tests: mini apps (contract H) — manifest, sandbox spec, snapshot, links and cookies.
The daemon running real apps is tests/apps."""

import asyncio
import re
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from handler_contracts import (
    APP_CODE_DIR,
    APP_SOCKET,
    RUNTIME_IMAGE,
    AppUi,
    FilteredNetwork,
    MiniAppManifest,
    MiniAppNeeds,
    NoNetwork,
    SandboxSpec,
)
from handler_control import compose
from handler_control.app_remote import AppChannel, RemoteAppError
from handler_control.apps import AppError, AppStore, DeployError, Deployment, snapshot
from handler_control.inbox import Inbox
from handler_control.settings import Settings
from handler_harness import addons

MINIAPP = addons.BUILTIN_DIR / "miniapp"
TEMPLATE = MINIAPP / "skills" / "miniapp" / "template"


def manifest(**overrides: Any) -> MiniAppManifest:
    data = {"apiVersion": "handler.miniapp/v1", "name": "notes", "version": "0.1.0"} | overrides
    return MiniAppManifest.model_validate(data)


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
        {"needs": {"secrets": ["DENO_DIR"]}},
        {"needs": {"secrets": ["HTTPS_PROXY"]}},
        {"needs": {"unknown": ["x"]}},  # unknown keys are errors: nothing asked is ignored
        {"typo": 1},
    ],
)
def test_invalid(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        manifest(**overrides)


def test_added_needs() -> None:
    m = manifest(needs={"egress": ["a.example.com:443", "b.example.com:443"], "secrets": ["K"]})
    before = MiniAppNeeds(egress=["a.example.com:443"])
    assert m.added_needs(before) == ["egress b.example.com:443", "secret K"]
    assert m.added_needs(m.needs) == []
    assert m.added_needs(None) == [
        "egress a.example.com:443", "egress b.example.com:443", "secret K",
    ]  # fmt: skip


def test_template_manifest_is_valid() -> None:
    m = MiniAppManifest.from_toml((TEMPLATE / "app.toml").read_text())
    assert (TEMPLATE / m.server.entry).is_file()


def test_addon_ships_the_runtime_deno_version() -> None:
    """Agents test apps with the Deno they will run on."""
    runtime = RUNTIME_IMAGE.rsplit("-", 1)[1]
    containerfile = (MINIAPP / "Containerfile").read_text()
    m = re.search(r"denoland/deno:bin-([0-9.]+)", containerfile)
    assert m and m[1] == runtime


# ── sandbox spec (H.3) ──────────────────────────────────────────────────


def spec(m: MiniAppManifest, test: bool = False) -> SandboxSpec:
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
    assert s.argv[0] == "run" and s.argv[-1] == f"{APP_CODE_DIR}/server/main.ts"
    assert "--allow-write=/d/data,/run/handler-app" in s.argv
    assert f"--allow-net=unix:{APP_SOCKET}" in s.argv
    assert "--cached-only" in s.argv and "-A" not in s.argv
    assert s.env["HANDLER_APP_SOCKET"] == APP_SOCKET and s.env["HANDLER_APP_DATA"] == "/d/data"
    assert s.resources and s.resources.memory == "512m"


def test_spec_with_egress() -> None:
    s = spec(manifest(needs={"egress": ["api.example.com:443"]}))
    assert isinstance(s.network, FilteredNetwork)
    assert s.network.allow == ["api.example.com:443"] and s.network.enforcement == "enforce"
    assert f"--allow-net=unix:{APP_SOCKET},api.example.com:443" in s.argv
    wildcard = spec(manifest(needs={"egress": ["*.example.com:443"]}))
    assert "--allow-net" in wildcard.argv  # Deno cannot say it: the proxy filters


def test_test_spec() -> None:
    s = spec(manifest(), test=True)
    assert s.argv[0] == "test" and s.argv[-1] == f"{APP_CODE_DIR}/server"


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
        'apiVersion = "handler.miniapp/v1"\nname = "notes"\nversion = "0.1.0"\n'
    )
    return src


def test_snapshot_copies_only_what_is_installed(tmp_path: Path) -> None:
    src = app_folder(tmp_path)
    (src / "server" / "link.ts").symlink_to("main.ts")  # inside: kept as a link
    snapshot(src, tmp_path / "v1", MiniAppManifest.from_toml((src / "app.toml").read_text()))
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
    m = MiniAppManifest.from_toml((src / "app.toml").read_text())
    with pytest.raises(DeployError, match="link to outside"):
        snapshot(src, tmp_path / "v1", m)


def test_snapshot_needs_a_built_ui(tmp_path: Path) -> None:
    src = app_folder(tmp_path)
    (src / "ui" / "dist" / "index.html").unlink()
    with pytest.raises(DeployError, match="build the UI"):
        snapshot(src, tmp_path / "v1", MiniAppManifest.from_toml((src / "app.toml").read_text()))


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
    return AppStore(settings, token="t0ken", inbox=Inbox(settings))


def test_link_is_one_time_and_per_app(tmp_path: Path) -> None:
    s = store(tmp_path)
    s.add(str(app_folder(tmp_path)))
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
    other = AppStore(s.settings, token="another", inbox=s.inbox)
    assert not other.cookie_matches("notes", s.cookie("notes"))


def test_registry_survives_a_restart(tmp_path: Path) -> None:
    s = store(tmp_path)
    s.add(str(app_folder(tmp_path)))
    assert (tmp_path / "data" / "apps" / "notes" / "data").is_dir()
    again = AppStore(s.settings, token="t0ken", inbox=s.inbox)
    assert again.records["notes"].source_dir == str((tmp_path / "src").resolve())
    with pytest.raises(AppError, match="already registered"):
        again.add(str(tmp_path / "src"))
    assert tomllib.loads((tmp_path / "src" / "app.toml").read_text())["name"] == "notes"


# ── a device's calls on an app's channel (H.8, D.7) ─────────────────────


def shared_app(tmp_path: Path) -> AppStore:
    s = store(tmp_path)
    s.add(str(app_folder(tmp_path)))
    s.records["notes"].deployments.append(Deployment(1, "0.1.0", datetime.now(UTC)))
    s.records["notes"].persons = ["owner"]
    return s


def test_channel_params_are_checked(tmp_path: Path) -> None:
    channel = AppChannel(shared_app(tmp_path))

    def call(method: str, params: dict[str, Any], person: str = "owner") -> object:
        return asyncio.run(channel.handle("notes", person, method, params))

    assert call("_handler/app/ui", {"have": "0.1.0#1"}) == AppUi(version="0.1.0#1", unchanged=True)
    for params, reason in [
        ({"method": "GET"}, "path"),  # path required
        ({"path": "/api/x", "headers": {"x": 1}}, "headers"),  # header values are text
        ({"path": "/api/x", "method": "TRACE"}, "method"),
        ({"path": "/other"}, "/api/"),  # only the app's API
        ({"path": "/api/x", "body": "%%"}, "base64"),
    ]:
        with pytest.raises(RemoteAppError, match=reason):
            call("_handler/app/http", params)
    with pytest.raises(RemoteAppError, match="not shared"):
        call("_handler/app/ui", {}, person="family")
