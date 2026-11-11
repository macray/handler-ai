"""Unit tests: addons and bindings (contract G) — loading, selection (G3), composition (G4)."""

from pathlib import Path
from typing import Any

import pytest

from handler_contracts import HARNESS_LAUNCH_API_VERSION, AddonUse, HarnessLaunch
from handler_control import addons, bindings, compose, secrets
from handler_control.settings import Settings
from handler_harness import addons as addon_catalog

STORE = secrets.SecretStore(Path("/nonexistent"))  # bindings here use env references

SHOPIFY = """
apiVersion = "handler.tool/v1"
name = "shopify"
image = "localhost/handler-ai-tool-shopify"
commands = ["shopify"]
env = { SHOPIFY_CLI_NO_ANALYTICS = "1" }
egress = ["*.myshopify.com:443"]

[settings.store]
env = "SHOPIFY_FLAG_STORE"
required = true

[secretSlots.theme_token]
env = "SHOPIFY_CLI_THEME_TOKEN"

[mcp]
command = ["shopify", "mcp", "--stdio"]
"""

LOGS = """
apiVersion = "handler.tool/v1"
name = "logs"
egress = ["logs.example.com:443"]
"""


@pytest.fixture
def addons_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "addons"
    for name, manifest in (("shopify", SHOPIFY), ("logs", LOGS)):
        (root / name / "skills" / name).mkdir(parents=True)
        (root / name / "tool.toml").write_text(manifest)
        (root / name / "skills" / name / "SKILL.md").write_text(f"# {name}\n")
    (root / "shopify" / "Containerfile").write_text("FROM scratch\n")
    monkeypatch.setenv("HANDLER_TOOLS_DIR", str(root))
    return root


@pytest.fixture
def bindings_dir(tmp_path: Path, addons_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "bindings"
    root.mkdir()
    monkeypatch.setenv("HANDLER_TEST_THEME_TOKEN", "shptka_s3cr3t")
    write(
        root,
        "shop",
        'tool = "shopify"\nsettings = { store = "dev.myshopify.com" }\n'
        'secrets = { theme_token = { env = "HANDLER_TEST_THEME_TOKEN" } }',
    )
    return root


# the shopify addon in the configuration "shop", the logs addon (no settings) by its name
SHOP = AddonUse(addon="shopify", binding="shop")
LOGS_USE = AddonUse(addon="logs")


def settings(tmp_path: Path) -> Settings:
    return Settings(
        port=0,
        config_dir=tmp_path,
        state_dir=tmp_path / "state",
        bindings_dir=tmp_path / "bindings",
        allowed_origins=frozenset(),
        web_ui_dir=tmp_path,
        data_dir=tmp_path / "data",
    )


def launch() -> HarnessLaunch:
    return HarnessLaunch(
        api_version=HARNESS_LAUNCH_API_VERSION,
        image="localhost/handler-ai-claude-code:latest",
        argv=["claude-agent-acp"],
        home="/home/agent",
        env={"A": "1"},
        egress=["api.anthropic.com:443"],
    )


def write(root: Path, name: str, body: str) -> None:
    (root / f"{name}.toml").write_text(f'apiVersion = "handler.connection/v1"\n{body}\n')


# an agent's sandbox: filtered, with a host of its own
AGENT: dict[str, Any] = {
    "network": "filtered",
    "enforcement": "enforce",
    "confinement": "strict",
    "allow": ["pypi.org:443"],
}


# ── loading (G.1, G.2) ──────────────────────────────────────────────────


def test_addon_catalog(addons_dir: Path) -> None:
    shop = addon_catalog.get("shopify")
    assert [s.name for s in shop.skills] == ["shopify"]
    assert addon_catalog.names() == ["app-builder", "logs", "shopify"]  # + the built-in one
    assert not shop.builtin and not shop.overrides_builtin  # shopify is in the catalog only
    logs, builder = addon_catalog.get("logs"), addon_catalog.get("app-builder")
    assert not logs.builtin and not logs.overrides_builtin
    assert builder.builtin and builder.directory == addon_catalog.BUILTIN_DIR / "app-builder"
    with pytest.raises(addon_catalog.UnknownAddonError):
        addon_catalog.get("../shopify")


@pytest.mark.rule("tool.its-manifest-holds-together")
def test_addon_needs_a_containerfile_iff_it_has_an_image(addons_dir: Path) -> None:
    (addons_dir / "shopify" / "Containerfile").unlink()
    with pytest.raises(addon_catalog.InvalidAddonError, match="Containerfile"):
        addon_catalog.get("shopify")


@pytest.mark.rule("tool.its-manifest-holds-together")
def test_addon_skill_needs_a_skill_md(addons_dir: Path) -> None:
    (addons_dir / "logs" / "skills" / "logs" / "SKILL.md").unlink()
    with pytest.raises(addon_catalog.InvalidAddonError, match=r"SKILL\.md"):
        addon_catalog.get("logs")


@pytest.mark.rule("connection.fills-its-tool-s-slots")
def test_valid_binding(bindings_dir: Path) -> None:
    b = bindings.get(bindings_dir, "shop")
    assert b.error is None and b.addon is not None and b.addon.name == "shopify"


@pytest.mark.rule("access.its-status-says-what-is-missing", "connection.fills-its-tool-s-slots")
@pytest.mark.parametrize(
    ("body", "error"),
    [
        ('tool = "nope"', "unknown tool"),
        ('tool = "shopify"', "required setting store"),
        ('tool = "shopify"\nsettings = { store = "s", shop = "x" }', "not declared"),
        ('tool = "shopify"\ntypo = 1', "Extra inputs"),
        ('tool = "logs"', "has no settings: it is used without a connection"),
    ],
)
def test_g2_invalid_bindings_carry_their_error(bindings_dir: Path, body: str, error: str) -> None:
    write(bindings_dir, "bad", body)
    b = bindings.get(bindings_dir, "bad")
    assert b.error is not None and error in b.error
    assert "bad" in [x.name for x in bindings.load_all(bindings_dir) if x.error]


@pytest.mark.rule("connection.fills-its-tool-s-slots")
def test_unknown_binding(bindings_dir: Path) -> None:
    assert "unknown connection" in (bindings.get(bindings_dir, "missing").error or "")
    assert "unknown connection" in (bindings.get(bindings_dir, "../shop").error or "")


# ── selection (G3) ──────────────────────────────────────────────────────


@pytest.mark.rule("tool.its-use-is-checked-when-saved")
def test_selection(bindings_dir: Path) -> None:
    selected = addons.check(bindings_dir, [SHOP, LOGS_USE])
    assert [(s.addon.name, s.binding and s.binding.name) for s in selected] == [
        ("shopify", "shop"),
        ("logs", None),
    ]


@pytest.mark.rule("tool.its-use-is-checked-when-saved")
@pytest.mark.parametrize(
    ("use", "error"),
    [
        (AddonUse(addon="shopify", binding="missing"), "connection 'missing'"),
        (AddonUse(addon="shopify"), "tool 'shopify' needs a connection"),
        (AddonUse(addon="logs", binding="shop"), "tool 'logs' has no settings"),
        (AddonUse(addon="nope"), "unknown tool 'nope'"),
    ],
)
def test_g3_a_binding_exactly_when_the_addon_has_slots(
    bindings_dir: Path, use: AddonUse, error: str
) -> None:
    with pytest.raises(addons.SelectionError, match=error):
        addons.check(bindings_dir, [use])


@pytest.mark.rule("tool.its-use-is-checked-when-saved")
def test_g3_a_binding_of_its_addon(addons_dir: Path, bindings_dir: Path) -> None:
    other = addons_dir / "other"
    other.mkdir()
    (other / "tool.toml").write_text(
        'apiVersion = "handler.tool/v1"\nname = "other"\n[settings.x]\nenv = "X"'
    )
    with pytest.raises(addons.SelectionError, match="one of tool 'shopify', not 'other'"):
        addons.check(bindings_dir, [AddonUse(addon="other", binding="shop")])


@pytest.mark.rule("tool.its-use-is-checked-when-saved")
def test_g3_one_use_per_addon(bindings_dir: Path) -> None:
    """An agent's own and its project's together: not the same addon twice."""
    write(bindings_dir, "shop2", 'tool = "shopify"\nsettings = { store = "b.myshopify.com" }')
    with pytest.raises(addons.SelectionError, match="'shopify' is chosen twice"):
        addons.check(bindings_dir, [SHOP, AddonUse(addon="shopify", binding="shop2")])


@pytest.mark.rule("tool.its-use-is-checked-when-saved")
def test_g3_no_command_twice(tmp_path: Path, addons_dir: Path, bindings_dir: Path) -> None:
    other = addons_dir / "other"
    other.mkdir()
    (other / "Containerfile").write_text("FROM scratch\n")
    (other / "tool.toml").write_text(
        'apiVersion = "handler.tool/v1"\nname = "other"\nimage = "localhost/o"\n'
        'commands = ["shopify"]'
    )
    with pytest.raises(addons.SelectionError, match="both provide 'shopify'"):
        addons.check(bindings_dir, [SHOP, AddonUse(addon="other")])


@pytest.mark.rule("tool.its-use-is-checked-when-saved")
def test_g3_an_addon_s_cache_has_a_folder_of_its_own(addons_dir: Path, bindings_dir: Path) -> None:
    """A cache is its target (D.8): one whose folder would be another target's is refused."""
    (addons_dir / "m2").mkdir()
    (addons_dir / "m2" / "tool.toml").write_text(
        'apiVersion = "handler.tool/v1"\nname = "m2"\n'
        '[[caches]]\ntarget = "~/m2"\nabout = "not Maven\'s"\n'
    )
    (addons_dir / "java").mkdir()
    (addons_dir / "java" / "tool.toml").write_text(
        'apiVersion = "handler.tool/v1"\nname = "java"\n'
        '[[caches]]\ntarget = "~/.m2"\nabout = "Maven repository"\n'
    )
    with pytest.raises(addons.SelectionError, match=r"would share the folder of ~/\.m2"):
        addons.check(bindings_dir, [AddonUse(addon="m2")])
    assert [s.addon.name for s in addons.check(bindings_dir, [AddonUse(addon="java")])] == ["java"]


# ── composition (G4) ────────────────────────────────────────────────────


@pytest.mark.rule("tool.each-start-gets-what-it-gives")
def test_g4_resolve(tmp_path: Path, addons_dir: Path, bindings_dir: Path) -> None:
    extra = addons.resolve(addons.check(bindings_dir, [SHOP, LOGS_USE]), STORE)
    assert extra.env == {
        "SHOPIFY_CLI_NO_ANALYTICS": "1",
        "SHOPIFY_FLAG_STORE": "dev.myshopify.com",
        "SHOPIFY_CLI_THEME_TOKEN": "shptka_s3cr3t",
    }
    assert extra.egress == ["*.myshopify.com:443", "logs.example.com:443"]
    assert extra.skills == [
        str(addons_dir / "shopify" / "skills" / "shopify"),
        str(addons_dir / "logs" / "skills" / "logs"),
    ]
    assert extra.secret_values == ["shptka_s3cr3t"]
    # what holds a secret, its name and hosts: for its delivery through the proxy (A.3)
    assert extra.secret_env == {
        "SHOPIFY_CLI_THEME_TOKEN": ("connections/shop/theme_token", ["*.myshopify.com:443"])
    }
    assert [s.model_dump() for s in extra.mcp_servers] == [
        {"name": "shopify", "command": "shopify", "args": ["mcp", "--stdio"], "env": []}
    ]


@pytest.mark.rule("tool.each-start-gets-what-it-gives")
def test_g4_tools_are_the_addons_folders(tmp_path: Path, bindings_dir: Path) -> None:
    """A.1: each addon with a tool, its current folder (addon_folders) read-only at its place,
    its bin/ on PATH; one not built names a folder that does not exist (a launch refuses it)."""
    s = settings(tmp_path)
    selected = addons.check(bindings_dir, [SHOP, LOGS_USE])  # logs has no tool
    [tool] = addons.tools(s, selected)
    assert (tool.target, tool.path) == ("/opt/tools/shopify", "/opt/tools/shopify/bin")
    assert tool.source == str(s.data_dir / "addons" / "shopify" / "not-built")
    (s.data_dir / "addons" / "shopify" / "abc").mkdir(parents=True)
    (s.data_dir / "addons" / "shopify" / "current").write_text("abc\n")
    assert addons.tools(s, selected)[0].source == str(s.data_dir / "addons" / "shopify" / "abc")


@pytest.mark.rule("tool.each-start-gets-what-it-gives")
def test_g4_sandbox_spec(tmp_path: Path, bindings_dir: Path) -> None:
    selected = addons.check(bindings_dir, [SHOP])
    extra = addons.resolve(selected, STORE)
    extra.images.extend(addons.tools(settings(tmp_path), selected))
    spec = compose.sandbox_spec(
        name="handler-x-y", launch=launch(), scope=str(tmp_path), addons=extra, **AGENT
    )
    assert [(a.target, a.path) for a in spec.addons] == [
        ("/opt/tools/shopify", "/opt/tools/shopify/bin")
    ]
    assert spec.env["A"] == "1" and spec.env["SHOPIFY_FLAG_STORE"] == "dev.myshopify.com"
    assert spec.network.mode == "filtered"
    assert "*.myshopify.com:443" in spec.network.allow and "pypi.org:443" in spec.network.allow


@pytest.mark.rule("tool.each-start-gets-what-it-gives")
def test_g4_addon_env_never_overrides_the_harness(tmp_path: Path, bindings_dir: Path) -> None:
    extra = addons.resolve(addons.check(bindings_dir, [SHOP]), STORE)
    harness = launch().model_copy(update={"env": {"SHOPIFY_FLAG_STORE": "harness"}})
    with pytest.raises(compose.AddonConflictError, match="SHOPIFY_FLAG_STORE"):
        compose.sandbox_spec(
            name="handler-x-y", launch=harness, scope=str(tmp_path), addons=extra, **AGENT
        )


def test_secret_values_for_redaction(tmp_path: Path, bindings_dir: Path) -> None:
    assert addons.secret_values(bindings_dir, [SHOP], STORE) == ["shptka_s3cr3t"]
    missing = AddonUse(addon="shopify", binding="missing")
    assert addons.secret_values(bindings_dir, [missing], STORE) == []
