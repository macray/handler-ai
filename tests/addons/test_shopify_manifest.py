"""The shopify tool's manifest says what its design requires (no store, no image needed): themes
only, one Theme Access password, sent to Shopify's Theme Access proxy and the store only. The
tool is the private registry's: HANDLER_TEST_REGISTRY, a checkout of it."""

import tomllib

import pytest

from handler_contracts.addon import AddonManifest

from ..support.sources import REGISTRY, requires_registry

pytestmark = requires_registry("tools/shopify")

THEME_PROXY = "theme-kit-access.shopifyapps.com:443"
STORE = "*.myshopify.com:443"


@pytest.fixture(scope="module")
def manifest() -> AddonManifest:
    assert REGISTRY is not None
    text = (REGISTRY / "tools/shopify/tool.toml").read_text()
    return AddonManifest.model_validate(tomllib.loads(text))


def test_a_connection_needs_the_store_and_a_theme_token(manifest: AddonManifest) -> None:
    assert manifest.settings["store"].required
    assert manifest.settings["store"].env == "SHOPIFY_FLAG_STORE"
    token = manifest.secret_slots["theme_token"]
    assert token.required  # without it the CLI asks for `shopify auth login`, which nobody answers
    assert token.env == "SHOPIFY_CLI_THEME_TOKEN"
    assert token.delivery == "proxy"  # the agent gets a stand-in


def test_the_theme_token_reaches_the_theme_proxy_and_the_store_only(
    manifest: AddonManifest,
) -> None:
    assert sorted(manifest.secret_hosts("theme_token") or []) == sorted([THEME_PROXY, STORE])


def test_themes_only_no_app_token_nor_app_hosts(manifest: AddonManifest) -> None:
    assert list(manifest.secret_slots) == ["theme_token"]
    assert "app" not in (manifest.description or "").lower().replace("shopify", "")
    for host in manifest.egress:
        name = host.rsplit(":", 1)[0]
        assert name != "*.shopify.com", "a wildcard reaching Partners and the admin"
        assert not name.startswith(("partners.", "admin.", "app.")), host


def test_the_check_runs_offline(manifest: AddonManifest) -> None:
    # `shopify version` looks up the latest release and exits 1 without network
    assert (manifest.check or [])[:2] == ["shopify", "theme"]


def test_a_connection_is_checked_by_listing_the_themes(manifest: AddonManifest) -> None:
    # read-only, and let through by the guard: a wrong store or token fails at Connect
    assert manifest.connection_check == ["shopify", "theme", "list"]
