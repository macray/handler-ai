"""The shopify tool's guard (its `handler/shopify.mjs`, the `shopify` agents run), against a
stand-in CLI: no store, no image. Unless the connection's `any_theme` is "1", what changes a
theme the agent did not make is refused before the CLI runs; the rest runs as is, its exit code
kept. The tool is the private registry's: HANDLER_TEST_REGISTRY, a checkout of it."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from ..support.sources import REGISTRY, requires_registry

pytestmark = [
    requires_registry("tools/shopify"),
    pytest.mark.skipif(shutil.which("node") is None, reason="node not installed"),
]

THEMES = [
    {"id": 1, "name": "Dawn", "role": "live"},
    {"id": 2, "name": "Summer draft", "role": "unpublished"},
    {"id": 3, "name": "agent: header fix", "role": "unpublished"},
]

# The CLI's stand-in: `theme list --json` prints THEMES; anything else prints its argv, exits 7.
FAKE_CLI = f"""
const argv = process.argv.slice(2);
if (argv.join(" ") === "theme list --json") {{
  console.log({json.dumps(json.dumps(THEMES))});
  process.exit(0);
}}
console.log(JSON.stringify(argv));
process.exit(7);
"""


@pytest.fixture(scope="module")
def guard(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The tool's installed tree, as its Containerfile lays it out, with the stand-in CLI."""
    assert REGISTRY is not None
    root = tmp_path_factory.mktemp("shopify")
    (root / "lib").mkdir()
    shutil.copy(REGISTRY / "tools/shopify/handler/shopify.mjs", root / "lib/shopify.mjs")
    cli = root / "node_modules/@shopify/cli"
    (cli / "bin").mkdir(parents=True)
    (cli / "package.json").write_text('{"type": "module"}')
    (cli / "bin/run.js").write_text(FAKE_CLI)
    (root / "bin").mkdir()
    (root / "bin/shopify").symlink_to("../lib/shopify.mjs")
    return root / "bin/shopify"


def shopify(guard: Path, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
    base = {"PATH": "/usr/bin:/bin", "SHOPIFY_FLAG_STORE": "shop.myshopify.com"}
    return subprocess.run(
        ["node", str(guard), *args],
        capture_output=True,
        text=True,
        env=base | env,
        timeout=30,
        check=False,
    )


def runs(r: subprocess.CompletedProcess[str], *args: str) -> bool:
    """The CLI ran with exactly `args` (and its exit code was kept)."""
    return r.returncode == 7 and json.loads(r.stdout.splitlines()[-1]) == list(args)


ALLOWED = [
    ("theme", "list"),
    ("theme", "pull", "--theme", "1", "--path", "theme/"),
    ("theme", "pull", "--live"),
    ("theme", "duplicate", "--theme", "1", "--name", "agent: header fix", "--force"),
    ("theme", "check", "--path", "theme/"),
    ("theme", "push", "--theme", "3", "--path", "theme/", "--json"),
    ("theme", "push", "--theme", "agent: header fix"),
    ("theme", "push", "-t", "3"),
    ("theme", "push", "--theme=3"),
    ("theme", "push", "--unpublished", "--theme", "agent: new header"),
    ("theme", "push", "--development"),
    ("theme", "dev"),
    ("theme", "dev", "--theme", "3"),
    ("theme", "delete", "--theme", "3", "--force"),
    ("theme", "delete", "--development", "--force"),
    ("theme", "rename", "--theme", "3", "--name", "agent: header fix v2"),
    ("theme:push", "--theme", "3"),
    ("version",),
]

REFUSED = [
    (("theme", "publish", "--theme", "3", "--force"), "changes what customers see"),
    (("theme", "push", "--live"), "live theme"),
    (("theme", "push", "-l"), "live theme"),
    (("theme", "push", "--theme", "1", "--allow-live"), "live theme"),
    (("theme", "push", "--theme", "1"), "the live theme"),
    (("theme", "push", "--theme", "Dawn"), "the live theme"),
    (("theme", "push", "--theme", "2"), "did not make"),
    (("theme", "push", "--theme", "3", "--publish"), "makes the theme live"),
    (("theme", "push", "--unpublished", "--theme", "Copy"), 'named with --theme "agent: '),
    (("theme", "push", "--unpublished"), 'named with --theme "agent: '),
    (("theme", "push"), "name it with --theme"),
    (("theme", "push", "--theme", "99"), "no single theme"),
    (("theme", "push", "-lu"), "short flags"),
    (("theme", "push", "--environment", "prod"), "--environment"),
    (("theme", "dev", "--theme", "2"), "did not make"),
    (("theme", "dev", "--allow-live"), "live theme"),
    (("theme", "delete", "--theme", "2", "--force"), "did not make"),
    (("theme", "delete", "--theme", "3", "--theme", "2", "--force"), "did not make"),
    (("theme", "delete", "--show-all"), "--show-all"),
    (("theme", "rename", "--live", "--name", "x"), "live theme"),
    (("theme", "rename", "--theme", "2", "--name", "agent: mine now"), "did not make"),
    (("theme:publish", "--theme", "3"), "changes what customers see"),
]


@pytest.mark.parametrize("args", ALLOWED, ids=" ".join)
def test_allowed_commands_run_as_is(guard: Path, args: tuple[str, ...]) -> None:
    assert runs(shopify(guard, *args), *args)


@pytest.mark.parametrize(("args", "why"), REFUSED, ids=lambda a: " ".join(a) if a else "")
def test_changes_to_themes_it_did_not_make_are_refused(
    guard: Path, args: tuple[str, ...], why: str
) -> None:
    r = shopify(guard, *args)
    assert r.returncode == 3 and r.stdout == ""  # the CLI never ran
    assert why in r.stderr and "agent: " in r.stderr  # says why, and what to do instead


def test_flags_given_through_env_are_refused(guard: Path) -> None:
    r = shopify(guard, "theme", "push", "--theme", "3", SHOPIFY_FLAG_LIVE="1")
    assert r.returncode == 3 and "SHOPIFY_FLAG_LIVE" in r.stderr


def test_any_theme_lets_everything_run(guard: Path) -> None:
    for args, _ in REFUSED:
        assert runs(shopify(guard, *args, HANDLER_SHOPIFY_ANY_THEME="1"), *args)


def test_signals_reach_the_cli(guard: Path, tmp_path: Path) -> None:
    """`theme dev` runs until stopped: stopping `shopify` stops the CLI, with its exit code."""
    cli = guard.parent.parent / "node_modules/@shopify/cli/bin/run.js"
    saved = cli.read_text()
    cli.write_text(
        "process.on('SIGTERM', () => process.exit(42)); console.log('up'); setInterval(() => {}, 1000);"
    )
    try:
        p = subprocess.Popen(
            ["node", str(guard), "theme", "dev"], stdout=subprocess.PIPE, text=True
        )
        assert p.stdout is not None and p.stdout.readline().strip() == "up"
        p.terminate()
        assert p.wait(timeout=10) == 42
    finally:
        cli.write_text(saved)
