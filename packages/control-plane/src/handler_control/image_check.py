"""Checking a freshly built harness image before agents get it (contract D.4), an addon image
(G.4, `check_addon`), and a new toolbox (B.7, at the end): its system packages' checks and the
commands it gives (`toolbox_commands`, the record).

The image is started through the real pipeline (render → compose → sandbox), with no network and a
dummy value in every secret slot: a harness with a token login on an account (a dummy token), any
other on a provider (a dummy key, endpoints nothing answers: no model is called), as the
conformance suite does. It must:
    answer `initialize` and `session/new`;
    offer every ACP session mode the descriptor maps a permission mode to;
    offer the descriptor's model option, if any;
    start the stdio MCP server given at `session/new` (when it takes stdio servers), with the
    sandbox's environment and without the harness's secrets (B.1 mcpEnv, B6), as addons' servers
    are given to every session (P8).
This is the credential-free part of the conformance suite (tests/harness), so a release that
renames a mode or stops starting MCP servers is caught before `:latest` moves. Skills are not
checked: nothing a harness says without a model turn shows it loaded them.
"""

import asyncio
import contextlib
import itertools
import json
import os
import shutil
import tempfile
import uuid
from collections.abc import Callable, Iterator
from typing import Any

from handler_contracts import (
    ADDON_VERSION_FILE,
    DEFAULT_MAX_MESSAGE_BYTES,
    AgentSpec,
    HarnessDescriptor,
    Provider,
    SandboxExit,
    SandboxSpec,
    StdioMcpServer,
)
from handler_harness import addons, catalog, render
from handler_harness import toolbox as toolbox_parts

from . import compose, sandbox_process
from .policy import parse
from .sandbox_process import stop
from .settings import Settings

CHECK_TIMEOUT = 180.0  # image start included
STDERR_DRAIN_TIMEOUT = 5.0
DUMMY_SECRET = "handler-image-check"
CLIENT_INFO = {"name": "handler-image-check", "version": "1"}
# in the check's scratch scope: the probe server's environment
MCP_PROBE_FILE = ".handler-mcp-probe"
MCP_PROBE_ENV = "HANDLER_IMAGE_CHECK"  # in the sandbox's environment: the probe must see it
MCP_PROBE_TIMEOUT = 30.0
CHECK_ENDPOINT = "http://127.0.0.1:9/v1"  # never reached: no network, and no model is called
CAPABILITIES = {"fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False}

Log = Callable[[str], None]


class ImageCheckError(RuntimeError):
    """The image does not work as its descriptor says (the reason is shown to the user)."""


@contextlib.contextmanager
def _scratch_scope(settings: Settings, prefix: str) -> Iterator[str]:
    """An empty folder for a check's sandbox to work in, checked, removed afterwards."""
    base = settings.state_dir / "image-check"
    base.mkdir(parents=True, exist_ok=True)
    scope = tempfile.mkdtemp(prefix=prefix, dir=base)
    if os.environ.get("HANDLER_SANDBOX_DEV_UID"):  # dev containers: the agent is another uid
        os.chmod(scope, 0o777)
    try:
        yield compose.check_scope([str(base)], scope)
    finally:
        shutil.rmtree(scope, ignore_errors=True)


async def check(settings: Settings, harness: catalog.Harness, image: str, log: Log) -> None:
    descriptor = harness.descriptor
    with _scratch_scope(settings, f"{descriptor.name}-") as scope:
        await _check_session(descriptor, image, scope, log)


def check_agent(descriptor: HarnessDescriptor) -> tuple[AgentSpec, str | None, str | None]:
    """The agent a check starts, its account token and its provider key: the dummy secret."""
    if (descriptor.login and descriptor.login.token) or not descriptor.provider_protocols:
        token = DUMMY_SECRET if descriptor.login and descriptor.login.token else None
        return AgentSpec(harness=descriptor.name, account="image-check"), token, None
    provider = Provider.model_validate(
        {
            "apiVersion": "handler.provider/v1",
            "endpoints": {p: CHECK_ENDPOINT for p in descriptor.provider_protocols},
            "models": [{"id": "handler-check-model", "contextWindow": 32000}],
        }
    )
    agent = AgentSpec(harness=descriptor.name, provider="image-check", provider_spec=provider)
    return agent, None, DUMMY_SECRET


async def _check_session(descriptor: HarnessDescriptor, image: str, checked: str, log: Log) -> None:
    agent, token, key = check_agent(descriptor)
    probe = os.path.join(checked, MCP_PROBE_FILE)
    probing = "stdio" in descriptor.mcp_transports
    servers = [mcp_probe(probe)] if probing else []
    launch = render(
        descriptor,
        agent,
        {},
        account_token=token,
        provider_key=key,
        permission_mode="bypass",
        mcp_servers=servers,
    )
    marker = uuid.uuid4().hex
    spec = compose.sandbox_spec(
        name=f"handler-check-{uuid.uuid4().hex[:8]}",
        launch=launch.model_copy(
            update={"image": image, "env": launch.env | {MCP_PROBE_ENV: marker}}
        ),
        scope=checked,
        network="none",
        enforcement="enforce",
        confinement="strict",
        labels={"handler.check": descriptor.name},
    )
    log(f"check: starting {image} (no network, dummy secrets)")
    proc = await sandbox_process.start_async(spec, line_limit=DEFAULT_MAX_MESSAGE_BYTES)
    stderr = asyncio.create_task(_forward_stderr(proc, log, "agent"))
    try:
        async with asyncio.timeout(CHECK_TIMEOUT):
            params = {"protocolVersion": 1, "clientCapabilities": CAPABILITIES}
            await _request(proc, "initialize", params | {"clientInfo": CLIENT_INFO})
            log("check: initialize ok")
            given = (launch.session_defaults.mcp_servers or []) if launch.session_defaults else []
            new = {
                "cwd": checked,
                "mcpServers": [s.model_dump(mode="json", by_alias=True) for s in given],
            }
            session = await _request(proc, "session/new", new)
            if probing:
                await _wait_for(probe, MCP_PROBE_TIMEOUT)
    except TimeoutError:
        raise ImageCheckError(f"no answer from the agent within {CHECK_TIMEOUT:.0f} s") from None
    finally:
        await stop(proc)
        stderr.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await stderr
    problems = mismatches(descriptor, session)
    if probing:
        problems += mcp_problems(_read(probe), marker, DUMMY_SECRET)
    if problems:
        raise ImageCheckError("; ".join(problems))
    log("check: session/new ok, every mapped permission mode and the model option are offered")
    if probing:
        log("check: the stdio MCP server started, with the sandbox's environment, no secret")
    else:
        log("check: no stdio MCP servers for this harness (mcpTransports): not probed")


def mcp_probe(path: str) -> StdioMcpServer:
    """A stdio MCP server that writes the environment it was started with to `path`, then
    waits, reading what the harness sends without answering or echoing it (a request echoed back
    reads as one from the server: Vibe logs it as invalid). The check only needs it started."""
    return StdioMcpServer(
        name="handler-check-probe", command="sh", args=["-c", f"env > {path}; exec cat > /dev/null"]
    )


def mcp_problems(dump: str | None, marker: str, secret: str) -> list[str]:
    """What the probe server's environment (None: it was never started) says is wrong."""
    if dump is None:
        return [
            f"the harness did not start the stdio MCP server given at session/new within "
            f"{MCP_PROBE_TIMEOUT:.0f} s"
        ]
    problems = []
    if f"{MCP_PROBE_ENV}={marker}" not in dump.splitlines():
        problems.append("the stdio MCP server did not get the sandbox's environment (B6)")
    if secret in dump:
        problems.append("the stdio MCP server got the harness's secret (B6)")
    return problems


async def _wait_for(path: str, timeout: float) -> None:
    """Until `path` exists and stopped growing, or `timeout`."""
    deadline = asyncio.get_running_loop().time() + timeout
    while not os.path.exists(path) and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.5)
    await asyncio.sleep(0.5)  # `env >` may still be writing


def _read(path: str) -> str | None:
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return None


def mismatches(descriptor: HarnessDescriptor, session: dict[str, Any]) -> list[str]:
    """What the descriptor relies on but the agent's `session/new` result does not offer."""
    modes = {m.get("id") for m in (session.get("modes") or {}).get("availableModes") or []}
    options = {o.get("id") for o in session.get("configOptions") or []}
    problems = [
        f"permission mode '{neutral}' maps to session mode '{m.session_mode}', which the agent "
        f"does not offer (it offers: {', '.join(sorted(str(x) for x in modes)) or 'none'})"
        for neutral, m in descriptor.permissions.items()
        if m.session_mode and m.session_mode not in modes
    ]
    if descriptor.model_option and descriptor.model_option not in options:
        problems.append(f"the agent has no '{descriptor.model_option}' config option")
    return problems


_ids = itertools.count(1)


async def _request(proc: asyncio.subprocess.Process, method: str, params: Any) -> Any:
    """Send one request and return its result; agent requests meanwhile are refused (P4)."""
    request_id = f"check-{next(_ids)}"
    assert proc.stdin is not None and proc.stdout is not None
    message = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
    proc.stdin.write((json.dumps(message) + "\n").encode())
    await proc.stdin.drain()
    async for raw in proc.stdout:
        msg = parse(raw.decode(errors="replace"))
        if msg is None:
            continue
        if msg.get("id") == request_id and "method" not in msg:
            if "error" in msg:
                error = msg["error"] if isinstance(msg["error"], dict) else {}
                raise ImageCheckError(f"{method} failed: {error.get('message', msg['error'])}")
            return msg.get("result") or {}
        if "method" in msg and "id" in msg:  # the agent asks the client something: refuse
            refusal = {"code": -32601, "message": "not available during an image check"}
            reply = {"jsonrpc": "2.0", "id": msg["id"], "error": refusal}
            proc.stdin.write((json.dumps(reply) + "\n").encode())
            await proc.stdin.drain()
    raise ImageCheckError(f"the agent exited during {method} (exit code {await proc.wait()})")


async def _forward_stderr(
    proc: asyncio.subprocess.Process, log: Log, prefix: str, said: list[str] | None = None
) -> None:
    """Its lines to the log; those of the launcher itself (why it did not start) also to
    `said`."""
    assert proc.stderr is not None
    own = sandbox_process.launcher_prefix()
    async for raw in proc.stderr:
        line = raw.decode(errors="replace").rstrip()
        if said is not None and line.startswith(own):
            said.append(line.removeprefix(own))
        log(f"{prefix}: {line}")


# ── addon images (G.4) ──────────────────────────────────────────────────


async def check_addon(
    settings: Settings, addon: addons.Addon, folder: str, toolbox: str, log: Log
) -> str:
    """G.4: mount the addon's folder (its image extracted) into the toolbox as agents get it
    (through the sandbox: no network, `strict`, the host user) and check that `bin/` holds
    exactly the declared commands, that the toolbox does not already provide one of them but has
    all it needs, that `version` is readable, and that the manifest's `check` succeeds with the
    addon on PATH. Returns the version line."""
    manifest = addon.manifest
    target = manifest.mount_target
    with _scratch_scope(settings, f"addon-{manifest.name}-") as scope:

        async def run(script: str, *args: str, on_path: bool = False) -> tuple[int, str]:
            spec = compose.addon_check_spec(
                name=f"handler-check-{uuid.uuid4().hex[:8]}",
                toolbox=toolbox,
                source=folder,
                target=target,
                scope=scope,
                argv=["sh", "-c", f"exec 2>&1\n{script}", "sh", *args],
                path=manifest.bin_dir if on_path else None,
            )
            return await _run_check(spec, log)

        log(f"check: its folder mounted at {target} in {toolbox} (no network, as agents get it)")
        code, listing = await run(f'ls -1A "{target}/bin"')
        found = sorted(listing.splitlines()) if code == 0 else []
        if found != sorted(manifest.commands):
            raise ImageCheckError(
                f"bin/ holds {', '.join(found) or 'nothing'}; "
                f"the manifest declares {', '.join(sorted(manifest.commands))}"
            )
        # the addon is not on PATH here: whatever `command -v` finds belongs to the toolbox
        _, shadowed = await run('for c; do command -v "$c"; done', *manifest.commands)
        if shadowed:
            raise ImageCheckError(
                f"the toolbox already provides {', '.join(shadowed.splitlines())}: "
                "it would hide the tool's command (tools come last on PATH)"
            )
        if manifest.needs:
            _, lacking = await run(
                'for c; do command -v "$c" >/dev/null || echo "$c"; done', *manifest.needs
            )
            if lacking:
                raise ImageCheckError(
                    f"the toolbox lacks {', '.join(lacking.splitlines())}, which the tool needs"
                )
        code, version = await run(f'cat "{target}/{ADDON_VERSION_FILE}"')
        if code != 0 or not version:
            raise ImageCheckError(f"{target}/{ADDON_VERSION_FILE} is missing or empty")
        version = version.splitlines()[0]
        log(f"check: {version}")
        if manifest.check:
            code, out = await run('exec "$@"', *manifest.check, on_path=True)
            for line in out.splitlines():
                log(f"tool: {line}")
            if code != 0:
                raise ImageCheckError(f"'{' '.join(manifest.check)}' exited with {code}")
    log("check: commands, version and check ok")
    return version


async def _in_toolbox(settings: Settings, toolbox: str, script: str, log: Log) -> tuple[int, str]:
    """`script` run by `sh -eu` in the toolbox alone, as agents get it: its exit code and what it
    printed (stderr included)."""
    with _scratch_scope(settings, "toolbox-") as scope:
        spec = compose.toolbox_check_spec(
            name=f"handler-check-{uuid.uuid4().hex[:8]}",
            toolbox=toolbox,
            scope=scope,
            argv=["sh", "-euc", f"exec 2>&1\n{script}"],
        )
        return await _run_check(spec, log)


async def check_system_packages(
    settings: Settings, toolbox: str, packages: list[toolbox_parts.SystemPackage], log: Log
) -> None:
    """B.7: each system package's check.sh in the new toolbox (static: files, capabilities,
    versions). One failing fails the build."""
    for package in packages:
        code, out = await _in_toolbox(settings, toolbox, package.check, log)
        for line in out.splitlines():
            log(f"{package.name}: {line}")
        if code != 0:
            raise ImageCheckError(f"system package {package.name}: its check exited with {code}")
        log(f"check: system package {package.name} ok")


async def toolbox_commands(
    settings: Settings, toolbox: str, commands: list[str], log: Log
) -> dict[str, str]:
    """B.6, the record: where `command -v` finds each of `commands` in the toolbox."""
    script = 'for c; do p=$(command -v "$c") && printf "%s\\t%s\\n" "$c" "$p"; done; true'
    code, out = await _in_toolbox(settings, toolbox, f"set -- {' '.join(commands)}\n{script}", log)
    if code != 0:
        raise ImageCheckError(f"the toolbox's commands could not be listed (exit code {code})")
    found = dict(line.split("\t", 1) for line in out.splitlines() if "\t" in line)
    log(f"check: the toolbox gives {len(found)} of {len(commands)} known commands")
    return found


async def _run_check(spec: SandboxSpec, log: Log) -> tuple[int, str]:
    """One check command in its sandbox: its exit code and what it printed. The sandbox's own
    lines (stderr) go to the log. A sandbox that did not start (A.1: refused, invalid, its setup
    failed) is said as such, its launcher's reason with it, not as the command's failure."""
    proc = await sandbox_process.start_async(spec, line_limit=DEFAULT_MAX_MESSAGE_BYTES)
    assert proc.stdin is not None and proc.stdout is not None
    proc.stdin.close()
    said: list[str] = []
    stderr = asyncio.create_task(_forward_stderr(proc, log, "sandbox", said))
    try:
        async with asyncio.timeout(CHECK_TIMEOUT):
            out = await proc.stdout.read()
            code = await proc.wait()
        # its last lines (why it did not start) read before `said` is: a process ended can
        # still have them in the pipe; a little while only (a child of its may hold stderr open)
        await asyncio.wait({stderr}, timeout=STDERR_DRAIN_TIMEOUT)
    except TimeoutError:
        raise ImageCheckError(f"no answer within {CHECK_TIMEOUT:.0f} s") from None
    finally:
        await stop(proc)
        stderr.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await stderr
    if (
        code in (SandboxExit.UNENFORCEABLE, SandboxExit.INVALID_SPEC, SandboxExit.SETUP_FAILED)
        and said
    ):
        raise ImageCheckError(f"its sandbox did not start: {said[-1]}")
    return code, out.decode(errors="replace").strip()
