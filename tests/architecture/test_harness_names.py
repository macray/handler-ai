"""Architecture rule: only the harness adapters know a harness (rule
`harness.known-by-its-descriptor-only`). handlerd, the CLI and the web apps read what a harness's
descriptor says; none of their code compares with, or picks by, a harness's name or product.

Comments and docstrings may name one as an example, and a sentence shown to people may name
products ("Claude Code, Codex…"): what is refused is a string that is a harness's name alone, the
shape of `if harness == "codex"`.
"""

import ast
import re
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HARNESSES = REPO / "packages/harness-adapters/src/handler_harness/data/harnesses"
PYTHON = ("packages/control-plane/src", "packages/cli/src")
WEB = ("packages/web-ui/src", "packages/remote-client/src", "packages/acp-view/src")
COMMENTS = re.compile(r"/\*.*?\*/|//[^\n]*|<!--.*?-->", re.S)


def harness_names() -> set[str]:
    found: set[str] = set()
    for descriptor in HARNESSES.glob("*/harness.toml"):
        data = tomllib.loads(descriptor.read_text())
        found |= {data["name"], data["product"]}
    return found


def _docstrings(tree: ast.Module) -> set[int]:
    kinds = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    return {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, kinds)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }


def _where(path: Path) -> Path:
    return path.relative_to(REPO) if path.is_relative_to(REPO) else path


def python_names(path: Path, names: set[str]) -> list[str]:
    tree = ast.parse(path.read_text())
    docs = _docstrings(tree)
    return [
        f"{_where(path)}:{node.lineno} {node.value!r}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and node.value in names and id(node) not in docs
    ]


def web_names(path: Path, names: set[str]) -> list[str]:
    alternatives = "|".join(map(re.escape, sorted(names)))
    quoted = re.compile(rf"([\"'`])({alternatives})\1")
    code = COMMENTS.sub(lambda m: "\n" * m.group().count("\n"), path.read_text())
    return [
        f"{_where(path)}:{n} {line.strip()[:80]}"
        for n, line in enumerate(code.splitlines(), 1)
        if quoted.search(line)
    ]


def sources() -> list[Path]:
    python = [p for d in PYTHON for p in (REPO / d).rglob("*.py") if "data" not in p.parts]
    web = [
        p
        for d in WEB
        for p in (REPO / d).rglob("*")
        if p.suffix in (".ts", ".svelte") and not p.name.endswith((".test.ts", ".gen.ts"))
    ]
    return python + web


@pytest.mark.rule("harness.known-by-its-descriptor-only")
def test_no_client_of_the_harnesses_names_one() -> None:
    """If this fails: a harness works in one client and not another, or adding one means
    changing handlerd and every client."""
    names = harness_names()
    assert {"claude-code", "Claude Code", "codex", "vibe", "pi"} <= names  # the scan sees them
    found = [
        hit
        for path in sources()
        for hit in (python_names if path.suffix == ".py" else web_names)(path, names)
    ]
    assert found == []


@pytest.mark.parametrize(
    ("source", "named"),
    [
        pytest.param('if harness == "codex":\n    pass\n', True, id="python-compares-with-a-name"),
        pytest.param('PRODUCT = "Claude Code"\n', True, id="python-product-name"),
        pytest.param('"""For `codex`, say."""\n', False, id="python-docstring-may-name-one"),
        pytest.param('x = "Claude Code, Codex…"\n', False, id="python-a-sentence-may-name-them"),
    ],
)
def test_the_python_scan_finds_a_name_used_as_code(
    tmp_path: Path, source: str, named: bool
) -> None:
    path = tmp_path / "scanned.py"
    path.write_text(source)
    assert bool(python_names(path, harness_names())) == named


@pytest.mark.parametrize(
    ("source", "named"),
    [
        pytest.param('if (h.name === "codex") {}', True, id="ts-compares-with-a-name"),
        pytest.param("const p = `pi`;", True, id="ts-template-literal"),
        pytest.param('// never `claude-code`, say "Claude Code"', False, id="ts-line-comment"),
        pytest.param('/** "Claude Code" */', False, id="ts-block-comment"),
        pytest.param("<p>Claude Code, Codex…</p>", False, id="svelte-a-sentence"),
    ],
)
def test_the_web_scan_finds_a_name_used_as_code(tmp_path: Path, source: str, named: bool) -> None:
    path = tmp_path / "scanned.ts"
    path.write_text(source)
    assert bool(web_names(path, harness_names())) == named
