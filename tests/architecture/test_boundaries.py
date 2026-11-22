"""Architecture rules: which block may import which (code map).

Blocks exchange data, not code. The only shared library is `handler_contracts`; the control plane
may also use the harness adapters' pure `render`, and sandbox runtimes the sandbox kit (what every
runtime shares: the network filter). Sandboxes are reached through their executables only
(contract A binding), never imported.
"""

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

ALLOWED: dict[str, set[str]] = {
    "handler_contracts": set(),
    "handler_sandbox_kit": {"handler_contracts"},  # listed by the sandbox runtimes only
    "handler_sandbox_podman": {"handler_contracts", "handler_sandbox_kit"},
    "handler_sandbox_apple": {"handler_contracts", "handler_sandbox_kit"},
    "handler_sandbox_docker": {"handler_contracts", "handler_sandbox_kit"},
    "handler_harness": {"handler_contracts"},
    # and the knowledge format, to read schemas and check documents (D.29)
    "handler_control": {"handler_contracts", "handler_harness", "handler_smd"},
    "handler_cli": {"handler_contracts"},  # a client: talks to handlerd over HTTP/WebSocket only
    # structured markdown, the knowledge ability's format: stands alone, not even the contracts
    "handler_smd": set(),
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


@pytest.mark.rule("blocks.share-only-the-contracts")
def test_every_package_has_a_rule() -> None:
    assert set(package_sources()) == set(ALLOWED), "add the new package to ALLOWED (and code-map)"


@pytest.mark.rule("blocks.share-only-the-contracts")
@pytest.mark.parametrize("package", sorted(ALLOWED))
def test_imports_respect_boundaries(package: str) -> None:
    violations = []
    for path in package_sources().get(package, []):
        for imported in handler_imports(path) - {package} - ALLOWED[package]:
            violations.append(f"{path.relative_to(REPO)} imports {imported}")
    assert violations == []


@pytest.mark.rule("smd.imports-nothing-of-handler")
def test_the_format_imports_nothing_of_handler() -> None:
    assert ALLOWED["handler_smd"] == set()
    sources = package_sources()["handler_smd"]
    assert sources
    assert {imported for path in sources for imported in handler_imports(path)} <= {"handler_smd"}


@pytest.mark.rule("blocks.share-only-the-contracts")
def test_every_package_has_a_readme() -> None:
    missing = [p.name for p in REPO.glob("packages/*") if not (p / "README.md").is_file()]
    assert missing == []


# `DEFAULT_RUNTIME`: the runtime handlerd uses when none was chosen, and `NOT_ON_MACOS`: the one
# never offered there, names only (sandbox_process.py); `ABILITY_NEEDS`: the commands a sandbox
# with an ability runs from the toolbox (B.6), the engine *inside* a sandbox, not the one running
# it; `ENGINES_ON_PATH`: the commands whose folder handlerd's user service must have on its PATH
# (daemon_commands.py), found there, never run.
_NAMES_AN_ENGINE = ("DEFAULT_RUNTIME", "NOT_ON_MACOS", "ABILITY_NEEDS", "ENGINES_ON_PATH")


def _names_the_default_runtime(tree: ast.AST) -> set[int]:
    """The ids of the constants inside `_NAMES_AN_ENGINE`'s assignments."""
    allowed: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        if getattr(targets[0], "id", None) in _NAMES_AN_ENGINE:
            allowed |= {id(constant) for constant in ast.walk(value)}
    return allowed


@pytest.mark.rule("blocks.only-the-runtime-runs-its-engine")
@pytest.mark.parametrize(
    ("engine", "runtime"),
    [("podman", "handler_sandbox_podman"), ("docker", "handler_sandbox_docker")],
)
def test_only_the_sandbox_runs_its_engine(engine: str, runtime: str) -> None:
    """The container engine is the sandbox's (contract A, A.7 for images): every other block asks
    its executable, so another runtime is another executable."""
    violations = []
    for package, paths in package_sources().items():
        if package == runtime:
            continue
        for path in paths:
            tree = ast.parse(path.read_text())
            allowed = _names_the_default_runtime(tree)
            violations += [
                f"{path.relative_to(REPO)}:{node.lineno}"
                for node in ast.walk(tree)
                if isinstance(node, ast.Constant)
                and node.value == engine
                and id(node) not in allowed
            ]
    assert violations == []


@pytest.mark.rule("gateway.imports-nothing-of-handler")
def test_gateway_is_independent() -> None:
    """remote-gateway/ is its own project: it may run on another machine, and must not need handler
    (remote design §1). It only shares the envelope format, as data."""
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
    ("host", {"sandbox_process", "runtime", "display", "desktop", "terminal"}),
    (
        "data",
        {
            *("accounts", "providers", "bindings", "secrets", "skills", "folders"),
            "areas",
            "skill_sources",
            "interfaces",
            *("skill_scan", "definitions", "agents_files", "handler_needs"),
            *("sources", "addon_install", "addon_folders"),
            *("knowledge", "knowledge_schemas", "config_files"),
            *("automation_config", "transcript", "services"),
            *("session_files", "git_read"),
            *("agents", "projects", "pins", "agent_state", "caches", "toolbox"),
        },
    ),
    (
        "launch",
        {
            "launcher",
            "access",
            "compose",
            "addons",
            "llm",
            "service_router",
            "model_agent",
            "transcribe",
            "provider_reach",
        },
    ),
    (
        "features",
        {
            *("sessions", "relay", "policy", "terminals"),
            "agent_service",
            "save_rules",
            *("builds", "image_check", "connection_check", "image_updates", "knowledge_tool"),
            *("apps", "app_http", "app_api", "app_smd", "app_runs", "app_jobs"),
            *("schedules", "inbox", "nudges"),
            *("agent_checks", "improvements", "uses", "notes_history"),
            "refusals",
            "plans",
            "plan_drafts",
            "automations",
            "assistant",
            "ask_history",
            "voice",
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


@pytest.mark.rule("blocks.a-control-module-imports-only-its-layer-or-below")
def test_every_control_module_has_a_layer() -> None:
    assert set(control_modules()) - set(LAYER) == set(), "add it to CONTROL_LAYERS (and README)"


@pytest.mark.rule("blocks.a-control-module-imports-only-its-layer-or-below")
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


@pytest.mark.rule("model-alone.has-no-tools", "model-alone.reads-only-its-notes-and-conversation")
def test_the_model_alone_reaches_no_sandbox_and_no_tool() -> None:
    """An agent on the model alone is text in, text out (D.18): its agent may only call the model
    (llm), read its knowledge and settings. Anything else (the service router, a launcher, an
    addon, a sandbox) would be a way to a tool."""
    modules = control_modules()
    [path] = modules["model_agent"]
    assert control_imports(path, set(modules)) <= {"knowledge", "llm", "services", "settings"}
