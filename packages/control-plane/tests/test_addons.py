"""Unit tests: addons and bindings (contract G) — loading, selection (G3), composition (G4)."""

from pathlib import Path
from typing import Any

import pytest

from handler_contracts import HARNESS_LAUNCH_API_VERSION, HarnessLaunch
from handler_control import addons, bindings, compose, secrets
from handler_harness import addons as addon_catalog

STORE = secrets.SecretStore(Path("/nonexistent"))  # bindings here use env references

SHOPIFY = """
apiVersion = "handler.addon/v1"
name = "shopify"
image = "localhost/handler-ai-addon-shopify"
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
apiVersion = "handler.addon/v1"
name = "logs"
egress = ["logs.example.com:443"]
"""


@pytest.fixture
def addons_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "addons"
    for name, manifest in (("shopify", SHOPIFY), ("logs", LOGS)):
        (root / name / "skills" / name).mkdir(parents=True)
        (root / name / "addon.toml").write_text(manifest)
        (root / name / "skills" / name / "SKILL.md").write_text(f"# {name}\n")
    (root / "shopify" / "Containerfile").write_text("FROM scratch\n")
    monkeypatch.setenv("HANDLER_ADDONS_DIR", str(root))
    return root


@pytest.fixture
def bindings_dir(tmp_path: Path, addons_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "bindings"
    root.mkdir()
    monkeypatch.setenv("HANDLER_TEST_THEME_TOKEN", "shptka_s3cr3t")
    write(
        root,
        "shop",
        'addon = "shopify"\nsettings = { store = "dev.myshopify.com" }\n'
        'secrets = { theme_token = { env = "HANDLER_TEST_THEME_TOKEN" } }',
    )
    write(root, "logs", 'addon = "logs"')
    return root


def launch() -> HarnessLaunch:
    return HarnessLaunch(
        api_version=HARNESS_LAUNCH_API_VERSION,
        image="localhost/handler-ai-claude-code:latest",
        argv=["claude-agent-acp"],
        home="/home/agent",
        env={"A": "1"},
        files=[],
        mounts=[],
        egress=["api.anthropic.com:443"],
    )


def write(root: Path, name: str, body: str) -> None:
    (root / f"{name}.toml").write_text(f'apiVersion = "handler.binding/v1"\n{body}\n')


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


def test_addon_needs_a_containerfile_iff_it_has_an_image(addons_dir: Path) -> None:
    (addons_dir / "shopify" / "Containerfile").unlink()
    with pytest.raises(addon_catalog.InvalidAddonError, match="Containerfile"):
        addon_catalog.get("shopify")


def test_addon_skill_needs_a_skill_md(addons_dir: Path) -> None:
    (addons_dir / "logs" / "skills" / "logs" / "SKILL.md").unlink()
    with pytest.raises(addon_catalog.InvalidAddonError, match=r"SKILL\.md"):
        addon_catalog.get("logs")


def test_valid_binding(bindings_dir: Path) -> None:
    b = bindings.get(bindings_dir, "shop")
    assert b.error is None and b.addon is not None and b.addon.name == "shopify"


@pytest.mark.parametrize(
    ("body", "error"),
    [
        ('addon = "nope"', "unknown addon"),
        ('addon = "shopify"', "required setting store"),
        ('addon = "shopify"\nsettings = { store = "s", shop = "x" }', "not declared"),
        ('addon = "shopify"\ntypo = 1', "Extra inputs"),
    ],
)
def test_g2_invalid_bindings_carry_their_error(bindings_dir: Path, body: str, error: str) -> None:
    write(bindings_dir, "bad", body)
    b = bindings.get(bindings_dir, "bad")
    assert b.error is not None and error in b.error
    assert "bad" in [x.name for x in bindings.load_all(bindings_dir) if x.error]


def test_unknown_binding(bindings_dir: Path) -> None:
    assert "unknown binding" in (bindings.get(bindings_dir, "missing").error or "")
    assert "unknown binding" in (bindings.get(bindings_dir, "../shop").error or "")


# ── selection (G3) ──────────────────────────────────────────────────────


def test_selection_without_duplicates(bindings_dir: Path) -> None:
    assert [b.name for b in addons.check(bindings_dir, ["shop", "logs", "shop"])] == [
        "shop",
        "logs",
    ]


def test_g3_invalid_binding(tmp_path: Path, bindings_dir: Path) -> None:
    with pytest.raises(addons.SelectionError, match="binding 'missing'"):
        addons.check(bindings_dir, ["missing"])


def test_g3_one_binding_per_addon(tmp_path: Path, bindings_dir: Path) -> None:
    write(bindings_dir, "shop2", 'addon = "shopify"\nsettings = { store = "b.myshopify.com" }')
    with pytest.raises(addons.SelectionError, match="both use addon 'shopify'"):
        addons.check(bindings_dir, ["shop", "shop2"])


def test_g3_no_command_twice(tmp_path: Path, addons_dir: Path, bindings_dir: Path) -> None:
    other = addons_dir / "other"
    other.mkdir()
    (other / "Containerfile").write_text("FROM scratch\n")
    (other / "addon.toml").write_text(
        'apiVersion = "handler.addon/v1"\nname = "other"\nimage = "localhost/o"\n'
        'commands = ["shopify"]'
    )
    write(bindings_dir, "other", 'addon = "other"')
    with pytest.raises(addons.SelectionError, match="both provide 'shopify'"):
        addons.check(bindings_dir, ["shop", "other"])


# ── composition (G4) ────────────────────────────────────────────────────


def test_g4_resolve(tmp_path: Path, addons_dir: Path, bindings_dir: Path) -> None:
    extra = addons.resolve(addons.check(bindings_dir, ["shop", "logs"]), STORE)
    assert [(m.image, m.target) for m in extra.image_mounts] == [
        ("localhost/handler-ai-addon-shopify:latest", "/opt/addons/shopify")
    ]
    assert extra.path_append == ["/opt/addons/shopify/bin"]
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
        "SHOPIFY_CLI_THEME_TOKEN": ("bindings/shop/theme_token", ["*.myshopify.com:443"])
    }
    assert [s.model_dump() for s in extra.mcp_servers] == [
        {"name": "shopify", "command": "shopify", "args": ["mcp", "--stdio"], "env": []}
    ]


def test_g4_sandbox_spec(tmp_path: Path, bindings_dir: Path) -> None:
    extra = addons.resolve(addons.check(bindings_dir, ["shop"]), STORE)
    spec = compose.sandbox_spec(
        name="handler-x-y", launch=launch(), scope=str(tmp_path), addons=extra, **AGENT
    )
    assert spec.image_mounts[0].target == "/opt/addons/shopify"
    assert spec.path_append == ["/opt/addons/shopify/bin"]
    assert spec.env["A"] == "1" and spec.env["SHOPIFY_FLAG_STORE"] == "dev.myshopify.com"
    assert spec.network.mode == "filtered"
    assert "*.myshopify.com:443" in spec.network.allow and "pypi.org:443" in spec.network.allow


def test_g4_addon_env_never_overrides_the_harness(tmp_path: Path, bindings_dir: Path) -> None:
    extra = addons.resolve(addons.check(bindings_dir, ["shop"]), STORE)
    harness = launch().model_copy(update={"env": {"SHOPIFY_FLAG_STORE": "harness"}})
    with pytest.raises(compose.AddonConflictError, match="SHOPIFY_FLAG_STORE"):
        compose.sandbox_spec(
            name="handler-x-y", launch=harness, scope=str(tmp_path), addons=extra, **AGENT
        )


def test_secret_values_for_redaction(tmp_path: Path, bindings_dir: Path) -> None:
    assert addons.secret_values(bindings_dir, ["shop"], STORE) == ["shptka_s3cr3t"]
    assert addons.secret_values(bindings_dir, ["missing"], STORE) == []
