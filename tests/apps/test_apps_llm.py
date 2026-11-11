"""Contract H, A2: secrets and egress. The test app (tests/fixtures/app-llm) calls a fake
OpenAI-compatible model server — a container on the app runtime's network (Podman's; Apple's
default one on a Mac), reached by IP like a model server on the LAN — with its key as a secret. (A model on the host itself is reached as
host.containers.internal:<port> through the same filtered: scripts/host-check.sh
--model-endpoint checks that path on the host.)
"""

import json
import subprocess
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from handler_contracts import RUNTIME_IMAGE

from ..support import dev_env
from ..support.daemon import Daemon
from ..support.runtimes import default_runtime
from .conftest import FIXTURES, AppClient, add_app, api, copy_fixture, requires_app_runtime

pytestmark = requires_app_runtime
KEY = "sk-local-" + uuid.uuid4().hex


@pytest.fixture(scope="module")
def model() -> Iterator[str]:
    """The fake model server's host:port: its folder mounted (Apple mounts folders only)."""
    name = f"handler-test-model-{uuid.uuid4().hex[:6]}"
    runtime = default_runtime()
    assert runtime is not None
    apple = runtime.name == "apple"
    dev_env.ensure_image(RUNTIME_IMAGE, runtime.binary if apple else "podman")
    engine = "container" if apple else "podman"
    network = [] if apple else ["--network", "podman"]
    subprocess.run(
        [
            engine, "run", "-d", "--rm", "--name", name, *network,
            "--mount", f"type=bind,source={FIXTURES / 'app-llm'},target=/llm,readonly",
            RUNTIME_IMAGE, "run", "/llm/fakellm.ts",
        ],
        check=True, capture_output=True,
    )  # fmt: skip
    try:
        yield f"{address(engine, name)}:8000"
    finally:
        rm = ["container", "delete", "--force"] if apple else ["podman", "rm", "-f"]
        subprocess.run([*rm, name], capture_output=True, check=False)


def address(engine: str, name: str) -> str:
    """The container's address on its network."""
    if engine == "podman":
        return subprocess.run(
            ["podman", "inspect", name, "--format",
             "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()  # fmt: skip
    from handler_sandbox_apple.container import find  # noqa: PLC0415 — on a Mac only

    out = subprocess.run(
        ["container", "inspect", name], check=True, capture_output=True, text=True
    ).stdout
    found = [
        a for key in ("ipv4Address", "address") for a in find(json.loads(out), key)
        if isinstance(a, str) and a.count(".") == 3
    ]  # fmt: skip
    return found[0].split("/")[0]


@pytest.fixture(scope="module")
def source(data_root: Path, model: str) -> Path:
    path = copy_fixture("app-llm", data_root)
    ip = model.split(":", maxsplit=1)[0]
    (path / "server" / "config.ts").write_text(
        f'export const MODEL_URL = "http://{model}/v1/chat/completions";\n'
        f'export const OTHER_URL = "http://{ip}:8001/";\n'  # not allowed
    )
    (path / "app.toml").write_text(
        'apiVersion = "handler.app/v1"\nname = "ask"\nversion = "1.0.0"\n'
        f'[needs]\negress = ["{model}"]\nsecrets = ["LLM_KEY"]\n'
    )
    return path


@pytest.mark.rule("deploy.what-it-adds-is-said-first")
def test_registered_with_its_needs(daemon: Daemon, source: Path, model: str) -> None:
    app = add_app(daemon, source).json()
    assert app["secrets"] == [{"name": "LLM_KEY", "set": False}]
    assert app["source"]["addedNeeds"] == [f"egress {model}", "secret LLM_KEY"]


@pytest.mark.rule("deploy.only-with-all-it-needs")
def test_deploy_needs_the_secret(daemon: Daemon) -> None:
    r = api(daemon, "POST", "/v1/apps/ask/deploy")
    assert r.status_code == 422
    assert "secret LLM_KEY not set" in r.json()["detail"]


@pytest.mark.rule("backend.its-secrets-reach-it-alone", "need.yours-kept-by-handler")
def test_secret_is_stored_not_shown(daemon: Daemon, data_root: Path) -> None:
    assert api(daemon, "PUT", "/v1/apps/ask/secrets/OTHER", {"value": "x"}).status_code == 409
    r = api(daemon, "PUT", "/v1/apps/ask/secrets/LLM_KEY", {"value": KEY})
    assert r.status_code == 200
    assert r.json()["secrets"] == [{"name": "LLM_KEY", "set": True}]
    assert KEY not in r.text
    stored = data_root / "secrets.json"  # the secret store (D.14), in HANDLER_DATA_DIR
    assert stored.stat().st_mode & 0o777 == 0o600
    assert json.loads(stored.read_text())["apps/ask/LLM_KEY"]["value"] == KEY
    listed = api(daemon, "GET", "/v1/secrets")
    assert KEY not in listed.text
    assert {"path": "apps/ask/LLM_KEY", "usedBy": ["apps/ask"]}.items() <= next(
        s for s in listed.json() if s["path"] == "apps/ask/LLM_KEY"
    ).items()


@pytest.mark.rule("backend.its-secrets-reach-it-alone")
def test_calls_the_model_with_its_key(daemon: Daemon) -> None:
    r = api(daemon, "POST", "/v1/apps/ask/deploy")
    assert r.status_code == 200, api(daemon, "GET", "/v1/apps/ask/log").json()["text"]
    browser = AppClient(daemon, "ask")
    browser.login(api(daemon, "POST", "/v1/apps/ask/open").json()["url"])
    answer = browser.request_json("POST", "/api/ask", {"text": "hello"})
    assert answer == {"answer": f"echo:hello auth:Bearer {KEY}"}


@pytest.mark.rule("backend.in-a-strict-sandbox")
def test_other_hosts_are_refused(daemon: Daemon) -> None:
    browser = AppClient(daemon, "ask")
    browser.login(api(daemon, "POST", "/v1/apps/ask/open").json()["url"])
    other = browser.request("GET", "/api/other").json()
    assert other["reached"] is False
    assert (
        other["status"] == 403 and "Blocked by Handler's network filter" in other["error"]
    )  # the sandbox's proxy


@pytest.mark.rule("backend.its-secrets-reach-it-alone")
def test_log_hides_the_secret(daemon: Daemon) -> None:
    log = api(daemon, "GET", "/v1/apps/ask/log").json()["text"]
    assert "starting with key [secret LLM_KEY]" in log
    assert KEY not in log


@pytest.mark.rule("deploy.only-with-all-it-needs", "backend.runs-only-while-used")
def test_unset_secret_stops_the_app(daemon: Daemon) -> None:
    r = api(daemon, "DELETE", "/v1/apps/ask/secrets/LLM_KEY")
    assert r.json()["secrets"] == [{"name": "LLM_KEY", "set": False}]
    assert r.json()["state"] == "stopped"
    browser = AppClient(daemon, "ask")
    browser.login(api(daemon, "POST", "/v1/apps/ask/open").json()["url"])
    r = browser.request("GET", "/api/health")
    assert r.status_code == 503
    assert "secret LLM_KEY not set" in r.text
