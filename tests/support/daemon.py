"""A real `handlerd` for tests: temporary config/state/accounts, and a fake harness.

harnesses/fake        the fake ACP agent (tests/support/fake_agent.py) — run on the host by the
                      fake sandbox (HANDLER_TEST_SANDBOX: tests/support/fake_sandbox.py), so
                      ACP-endpoint tests need no container; its terminal program (D.16) is
                      FAKE_TERMINAL_SCRIPT
harnesses/<real>      symlinks to the repository's harnesses (for listing)
accounts/<harness>    one account per harness, named after it; fake and echo-box logged in
                      (their token in the daemon's secret store; fake's is FAKE_SECRET): a
                      agent names one (`create_ad_hoc("fake", …)`)
providers/            the extra ones only (a test's own); HANDLER_DATA_DIR is the daemon's own, too
config/folders.toml   the work folders: the scope root (Daemon.scope_root)
bindings/browser      the repository's playwright addon: its MCP server, for P8 tests (the fake
                      sandbox ignores the addon's image)
harnesses/echo-box    curl image, tagged as ECHO_IMAGE:latest because
                      descriptors name untagged images, B.6; tries example.com, then `cat` as
                      "agent": live container connection for egress tests
"""

import contextlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

import httpx
from websockets.sync.client import connect

from handler_contracts import ACP_SUBPROTOCOL, BEARER_SUBPROTOCOL_PREFIX
from handler_control import addon_install
from handler_control.secrets import SecretStore
from handler_harness import addons, catalog

from . import dev_env
from .acp_client import AcpClient
from .fake_sandbox import FAKE_IMAGE

REPO = Path(__file__).resolve().parents[2]
FAKE_AGENT = Path(__file__).with_name("fake_agent.py")
FAKE_SANDBOX = Path(__file__).with_name("fake_sandbox.py")
UI_ORIGIN = "http://ui.test"
FAKE_SECRET = "s3cr3t-value-for-redaction"

# the fake harness's terminal program (D.16): what it was given, then one line typed, echoed;
# exits 3. `stty size` follows a resize when sent `resize`.
FAKE_TERMINAL_SCRIPT = (
    '[ -t 0 ] && echo on-a-tty; echo "size:$(stty size)"; echo "TERM=$TERM"; echo "args:$*"; '
    'while read -r line; do [ "$line" = resize ] && echo "size:$(stty size)"; '
    '[ "$line" = quit ] && exit 3; echo "got:$line"; done; exit 4'
)

FAKE_HARNESS = f"""
apiVersion = "handler.harness/v1"
name = "fake"
product = "Fake"
image = "{FAKE_IMAGE}"
acpCommand = ["{sys.executable}", "{FAKE_AGENT}"]
home = "/home/agent"
modelOption = "model"
skillsDir = "~/.fake/skills"
mcpTransports = ["stdio"]
[login]
subscription = "Fake"
unattended = "allowed"
terms = "https://example.org/fake-terms"
token = "FAKE_TOKEN"
tokenCommand = "fake setup-token"
[permissions]
ask = {{ sessionMode = "ask" }}
accept-edits = {{ sessionMode = "edits" }}
bypass = {{ sessionMode = "yolo" }}
[terminal]
command = ["sh", "-c", '{FAKE_TERMINAL_SCRIPT}', "fake-terminal"]
modelFlag = "--model"
mcpConfigFlag = "--mcp-config"
[terminal.permissions]
ask = []
accept-edits = ["--edits"]
bypass = ["--yolo"]
"""

CURL_IMAGE = "docker.io/curlimages/curl:8.11.1"
ECHO_IMAGE = "localhost/handler-ai-test-echo-box"

ECHO_HARNESS = f"""
apiVersion = "handler.harness/v1"
name = "echo-box"
product = "Echo box"
image = "{ECHO_IMAGE}"
acpCommand = ["sh", "-c", "curl -s -m 5 -o /dev/null https://example.com; exec cat"]
home = "/home/agent"
[login]
subscription = "Echo"
unattended = "check-terms"
terms = "https://example.org/echo-terms"
token = "ECHO_TOKEN"
tokenCommand = "echo-box setup-token"
[permissions]
ask = {{}}
accept-edits = {{}}
bypass = {{}}
"""

# a file login that needs its terminal (D.9), on the host: asks for a code, writes it into handler's
# folder (`{dir}`, given as BOX_HOME; as Vibe's `.env`: a new file renamed over it)
LOGIN_SCRIPT = (
    "test -t 0 || exit 3; echo 'sign in at https://example.org/sign-in?session=abc'; "
    "printf 'code? '; read code; "
    'echo "$code" > "$BOX_HOME/new" && mv "$BOX_HOME/new" "$BOX_HOME/credential"'
)
LOGIN_HARNESS = f"""
apiVersion = "handler.harness/v1"
name = "login-box"
product = "Login box"
image = "{ECHO_IMAGE}"
acpCommand = ["cat"]
home = "/home/agent"
writablePaths = ["~/.box"]
[stateSlots.cred]
target = "~/.box/credential"
kind = "file"
required = false
credential = true
[login]
subscription = "Login box"
unattended = "refused"
terms = "https://example.org/login-terms"
command = ["sh", "-c", {json.dumps(LOGIN_SCRIPT)}]
env = {{ BOX_HOME = "{{dir}}" }}
file = "cred"
[permissions]
bypass = {{}}
"""


def _tag_echo_image() -> None:
    """Best effort: the echo-box tests need podman and the curl image anyway."""
    exists = ["podman", "image", "exists", f"{ECHO_IMAGE}:latest"]
    if subprocess.run(exists, check=False).returncode:
        subprocess.run(["podman", "pull", "-q", CURL_IMAGE], capture_output=True, check=False)
        subprocess.run(
            ["podman", "tag", CURL_IMAGE, f"{ECHO_IMAGE}:latest"], capture_output=True, check=False
        )


@dataclass
class Daemon:
    base_url: str
    token: str
    config_dir: Path
    scope_root: Path
    process: subprocess.Popen[bytes]
    env: dict[str, str]
    log: IO[bytes]

    def restart(self, kill: bool = False) -> None:
        """handlerd stopped (`kill`: at once, as if it crashed) and started again, same state."""
        if kill:
            self.process.kill()
        else:
            self.process.terminate()
        self.process.wait(timeout=30)
        self.process = _launch(self.env, self.log, self.base_url)

    @property
    def accounts_dir(self) -> Path:
        return self.config_dir.parent / "accounts"

    @property
    def providers_dir(self) -> Path:
        return self.config_dir.parent / "providers"

    @property
    def data_dir(self) -> Path:
        return self.config_dir.parent / "data"

    @property
    def cache_dir(self) -> Path:
        return self.config_dir.parent / "cache"

    @property
    def ws_base(self) -> str:
        return self.base_url.replace("http://", "ws://")

    def http(self, token: str | None = "default", **headers: str) -> httpx.Client:
        auth = (
            {"Authorization": f"Bearer {self.token if token == 'default' else token}"}
            if token
            else {}
        )
        return httpx.Client(base_url=self.base_url, headers=auth | headers, timeout=30)

    def create_ad_hoc(self, account: str | None, scope: Path, **body: Any) -> dict[str, Any]:
        """An ad-hoc agent of the harness of `account`; None: `body` names a provider and its
        harness. Its one model: `account` with the `harness`, `provider` and `model` of `body`.
        What it widens is confirmed (D.8; tests of that call the API themselves)."""
        model = {k: body.pop(k) for k in ("harness", "provider", "model") if k in body}
        model |= {"account": account} if account else {}
        body = {"models": [model], "scope": str(scope), "confirmRisks": True} | body
        with self.http() as c:
            r = c.post("/v1/agents", json=body)
            r.raise_for_status()
            return r.json()

    def make_scope(self) -> Path:
        path = self.scope_root / f"scope-{uuid.uuid4().hex[:8]}"
        path.mkdir()
        if dev_env.DEV_MODE:
            path.chmod(0o777)
        return path

    def connect(
        self, acp_url: str, *, token: str | None = "default", origin: str | None = None
    ) -> AcpClient:
        protocols = [ACP_SUBPROTOCOL]
        if token:
            protocols.append(
                BEARER_SUBPROTOCOL_PREFIX + (self.token if token == "default" else token)
            )
        headers = {"Origin": origin} if origin else None
        stack = contextlib.ExitStack()
        ws = stack.enter_context(
            connect(acp_url, subprotocols=protocols, additional_headers=headers, max_size=None)  # ty: ignore[invalid-argument-type]
        )
        return AcpClient.over_websocket(ws, close=stack.close)


def _launch(env: dict[str, str], log: IO[bytes], base: str) -> subprocess.Popen[bytes]:
    """handlerd, once it answers."""
    proc = subprocess.Popen(
        [str(Path(sys.executable).parent / "handlerd")], env=env, stdout=log, stderr=log
    )
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{base}/v1/health", timeout=1).status_code == 200:
                return proc
        except httpx.HTTPError:
            time.sleep(0.1)
    proc.kill()
    raise RuntimeError(f"handlerd did not start (its log: {log.name})")


def fake_terminal(folder: Path, typed: str = "terminal-code") -> Path:
    """A stand-in for the desktop's terminal (HANDLER_TERMINAL, D.9): records how it was called
    (`<script>.calls`), runs the command with `typed` as what the person types, its output in
    `<script>.log`."""
    script = folder / "fake-terminal"
    script.write_text(
        "#!/bin/sh\n"
        'printf "%s\\n" "$*" >> "$0.calls"\n'
        f'printf \'{typed}\\n\' | "$@" >> "$0.log" 2>&1\n'
    )
    script.chmod(0o755)
    return script


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _accounts(directory: Path, harnesses: Path, extra: dict[str, str]) -> Path:
    """One account per harness, named after it, and the extra ones."""
    directory.mkdir()
    for harness in [h.name for h in harnesses.iterdir()]:
        text = f'apiVersion = "handler.account/v1"\nharness = "{harness}"\n'
        (directory / f"{harness}.toml").write_text(text)
    for name, text in extra.items():
        (directory / f"{name}.toml").write_text(text)
    return directory


def _install_catalog_addons(config: Path, names: tuple[str, ...]) -> None:
    """Into `config`, as `handler addon add NAME` would (G.5): the folders and their lock."""
    lock = ""
    for name in names:
        shutil.copytree(addons.CATALOG_DIR / name, config / "addons" / name)
        digest = addon_install.catalog_digest(name)
        lock += f'[addons.{name}]\nsource = "catalog:{name}"\ndigest = "{digest}"\n'
        lock += 'installedAt = "2026-10-03T00:00:00+00:00"\n'
    (config / "addons.lock.toml").write_text(lock)


def start_daemon(  # noqa: PLR0915 — one setup, top to bottom
    extra_env: dict[str, str] | None = None,
    extra_accounts: dict[str, str] | None = None,
    extra_providers: dict[str, str] | None = None,
) -> Iterator[Daemon]:
    """`extra_accounts`, `extra_providers`: name → TOML."""
    tmp = Path(tempfile.mkdtemp(prefix="handlerd-"))
    scope_root = dev_env.scope_root() / f"daemon-{uuid.uuid4().hex[:8]}"
    scope_root.mkdir(parents=True)
    if dev_env.DEV_MODE:
        scope_root.chmod(0o777)
    harnesses = tmp / "harnesses"
    (harnesses / "fake").mkdir(parents=True)
    (harnesses / "fake" / "harness.toml").write_text(FAKE_HARNESS)
    (harnesses / "echo-box").mkdir()
    (harnesses / "echo-box" / "harness.toml").write_text(ECHO_HARNESS)
    (harnesses / "login-box").mkdir()
    (harnesses / "login-box" / "harness.toml").write_text(LOGIN_HARNESS)
    with contextlib.suppress(OSError):
        _tag_echo_image()
    dev_env.ensure_network_filter()  # echo-box sandboxes are real (the fake answers it is built)
    for real in (catalog.DATA / "harnesses").iterdir():
        if (real / "harness.toml").exists():
            (harnesses / real.name).symlink_to(real)
    accounts = _accounts(tmp / "accounts", harnesses, extra_accounts or {})
    store = SecretStore(tmp / "data")
    for name, token in (("fake", FAKE_SECRET), ("echo-box", "echo-token")):  # logged in
        store.put(f"accounts/{name}/token", token)
        with (accounts / f"{name}.toml").open("a") as f:
            f.write(f'token = {{ secret = "accounts/{name}/token" }}\n')
    providers = tmp / "providers"
    providers.mkdir()
    for name, text in (extra_providers or {}).items():
        (providers / f"{name}.toml").write_text(text)

    fake_sandbox = tmp / "fake-sandbox"  # run by the daemon's interpreter (handler_contracts' venv)
    (tmp / "fake-ran").mkdir()
    fake_sandbox.write_text(
        f'#!/bin/sh\nHANDLER_TEST_FAKE_RAN="{tmp / "fake-ran"}" exec "{sys.executable}" '
        f'"{FAKE_SANDBOX}" "$@"\n'
    )
    fake_sandbox.chmod(0o755)
    bindings = tmp / "config" / "bindings"
    bindings.mkdir(parents=True)
    (tmp / "config" / "folders.toml").write_text(f"roots = {json.dumps([str(scope_root)])}\n")
    (bindings / "browser.toml").write_text(
        'apiVersion = "handler.binding/v1"\naddon = "playwright"\n'
    )
    if "HANDLER_ADDONS_DIR" not in (extra_env or {}):  # else the test brings its own addons
        _install_catalog_addons(tmp / "config", ("playwright", "shopify"))
    port = _free_port()
    env = (
        os.environ
        | {
            "HANDLER_PORT": str(port),
            "HANDLER_CONFIG_DIR": str(tmp / "config"),
            "HANDLER_STATE_DIR": str(tmp / "state"),
            "HANDLER_ACCOUNTS_DIR": str(accounts),
            "HANDLER_PROVIDERS_DIR": str(providers),
            "HANDLER_DATA_DIR": str(tmp / "data"),
            "HANDLER_CACHE_DIR": str(tmp / "cache"),
            "HANDLER_RUNTIME_DIR": str(tmp / "run"),
            "HANDLER_HARNESSES_DIR": str(harnesses),
            "HANDLER_ALLOWED_ORIGINS": UI_ORIGIN,
            "HANDLER_TEST_SANDBOX": str(fake_sandbox),
        }
        | (extra_env or {})
    )
    log = open(tmp / "handlerd.log", "wb")  # noqa: SIM115 — kept open for the daemon's lifetime
    base = f"http://127.0.0.1:{port}"
    proc = _launch(env, log, base)
    token = (tmp / "config" / "token").read_text().strip()
    daemon = Daemon(
        base_url=base,
        token=token,
        config_dir=tmp / "config",
        scope_root=scope_root,
        process=proc,
        env=env,
        log=log,
    )
    try:
        yield daemon
    finally:
        daemon.process.terminate()
        daemon.process.wait(timeout=30)
        log.close()
        if os.environ.get("HANDLER_TEST_KEEP_DAEMON_LOG"):
            print(f"handlerd log: {tmp / 'handlerd.log'}")
        dev_env.remove_scope(scope_root)
