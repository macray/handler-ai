"""Architecture rules: which block may import which (docs/dev/code-map.md).

Blocks exchange data, not code. The only shared library is `handler_contracts`; the control plane
may also use the harness adapters' pure `render`. Sandboxes are reached through their
executables only (contract A binding), never imported.
"""

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

ALLOWED: dict[str, set[str]] = {
    "handler_contracts": set(),
    "handler_sandbox_podman": {"handler_contracts"},
    "handler_harness": {"handler_contracts"},
    "handler_control": {"handler_contracts", "handler_harness"},
    "handler_cli": {"handler_contracts"},  # a client: talks to handlerd over HTTP/WebSocket only
}


def package_sources() -> dict[str, list[Path]]:
    found: dict[str, list[Path]] = {}
    for src in sorted(REPO.glob("packages/*/src/*")):
        if src.is_dir() and src.name.startswith("handler_"):
            found[src.name] = sorted(src.rglob("*.py"))
    return found


def handler_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return {n for n in names if n.startswith("handler_")}


def test_every_package_has_a_rule() -> None:
    assert set(package_sources()) == set(ALLOWED), "add the new package to ALLOWED (and code-map)"


@pytest.mark.parametrize("package", sorted(ALLOWED))
def test_imports_respect_boundaries(package: str) -> None:
    violations = []
    for path in package_sources().get(package, []):
        for imported in handler_imports(path) - {package} - ALLOWED[package]:
            violations.append(f"{path.relative_to(REPO)} imports {imported}")
    assert violations == []


def test_every_package_has_a_readme() -> None:
    missing = [p.name for p in REPO.glob("packages/*") if not (p / "README.md").is_file()]
    assert missing == []


def test_only_the_sandbox_runs_podman() -> None:
    """The container engine is the sandbox's (contract A, A.7 for images): every other block asks
    its executable, so another runtime is another executable."""
    violations = [
        f"{path.relative_to(REPO)}:{node.lineno}"
        for package, paths in package_sources().items()
        if package != "handler_sandbox_podman"
        for path in paths
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.Constant) and node.value == "podman"
    ]
    assert violations == []


def test_gateway_is_independent() -> None:
    """remote-gateway/ is its own project: it may run on another machine, and must not need handler
    (docs/dev/design/remote.md §1). It only shares the envelope format, as data."""
    sources = sorted((REPO / "remote-gateway" / "src").rglob("*.py"))
    assert sources
    violations = [
        f"{path.relative_to(REPO)} imports {imported}"
        for path in sources
        for imported in handler_imports(path) - {"handler_gateway"}
    ]
    assert violations == []


# ── inside the control plane ────────────────────────────────────────────

CONTROL = REPO / "packages" / "control-plane" / "src" / "handler_control"

# Its layers, lowest first (packages/control-plane/README.md): a module imports only from its own
# layer or the ones below. Moving a module to another layer is a design decision: change it here.
CONTROL_LAYERS: list[tuple[str, set[str]]] = [
    ("base", {"__init__", "settings", "files"}),
    ("migrations", {"migrations"}),
    ("host", {"sandbox_process", "runtime", "display", "desktop", "shortcuts", "terminal"}),
    (
        "data",
        {
            *("accounts", "providers", "bindings", "secrets", "skills", "folders"),
            "contexts",
            "skill_sources",
            "interfaces",
            *("skill_scan", "builtin_agents"),
            "addon_install",
            *("knowledge", "config_files"),
            *("automation_config", "transcript", "services"),
            *("session_files", "git_read"),
            *("agents", "projects", "agent_state", "caches"),
        },
    ),
    ("launch", {"launcher", "access", "compose", "addons", "llm", "service_router"}),
    (
        "features",
        {
            *("sessions", "relay", "policy", "terminals"),
            "checks",
            *("builds", "image_check", "image_updates"),
            *("apps", "app_http", "app_api", "schedules", "inbox"),
            "automations",
        },
    ),
    ("remote", {"remote", "remote_crypto", "webpush", "app_remote"}),
    ("surface", {"api", "auth", "webui", "daemon"}),
]
LAYER = {module: rank for rank, (_, modules) in enumerate(CONTROL_LAYERS) for module in modules}


def control_modules() -> dict[str, list[Path]]:
    """Top-level module name (a sub-package counts as one) → its files. `data/` is platform
    data, not code of handler (built-in agents' skills may hold scripts)."""
    found: dict[str, list[Path]] = {}
    for path in sorted(CONTROL.rglob("*.py")):
        if path.relative_to(CONTROL).parts[0] == "data":
            continue
        found.setdefault(path.relative_to(CONTROL).parts[0].removesuffix(".py"), []).append(path)
    return found


def control_imports(path: Path, modules: set[str]) -> set[str]:
    """The control plane's modules `path` imports, outside its own sub-package."""
    depth = len(path.relative_to(CONTROL).parts) - 1  # 1 inside a sub-package such as api/
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom) and node.level and node.level - 1 == depth:
            if node.module:
                names.add(node.module.split(".")[0])
            else:
                names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            parts = node.module.split(".")
            if parts[0] == "handler_control" and len(parts) > 1:
                names.add(parts[1])
    return names & modules


def test_every_control_module_has_a_layer() -> None:
    assert set(control_modules()) - set(LAYER) == set(), "add it to CONTROL_LAYERS (and README)"


def test_control_modules_import_only_their_layer_or_below() -> None:
    modules = control_modules()
    violations = [
        f"{path.relative_to(REPO)} ({CONTROL_LAYERS[LAYER[name]][0]}) imports {imported} "
        f"({CONTROL_LAYERS[LAYER[imported]][0]})"
        for name, paths in modules.items()
        for path in paths
        for imported in control_imports(path, set(modules)) - {name}
        if LAYER[imported] > LAYER[name]
    ]
    assert violations == []
