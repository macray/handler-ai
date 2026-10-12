"""Contract H, A2: secrets and egress. The test app (tests/fixtures/miniapp-llm) calls a fake
OpenAI-compatible model server — a container on podman's network, reached by IP like a model
server on the LAN — with its key as a secret. (A model on the host itself is reached as
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

from ..support.daemon import Daemon
from .conftest import FIXTURES, AppClient, api, copy_fixture, requires_podman

pytestmark = requires_podman
KEY = "sk-local-" + uuid.uuid4().hex


@pytest.fixture(scope="module")
def model() -> Iterator[str]:
    """The fake model server's host:port."""
    name = f"handler-test-model-{uuid.uuid4().hex[:6]}"
    subprocess.run(["podman", "pull", "-q", RUNTIME_IMAGE], capture_output=True, check=False)
    subprocess.run(
        [
            "podman", "run", "-d", "--rm", "--name", name, "--network", "podman",
            "-v", f"{FIXTURES / 'miniapp-llm' / 'fakellm.ts'}:/fake.ts:ro",
            RUNTIME_IMAGE, "run", "--allow-net", "/fake.ts",
        ],
        check=True, capture_output=True,
    )  # fmt: skip
    try:
        ip = subprocess.run(
            ["podman", "inspect", name, "--format",
             "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()  # fmt: skip
        yield f"{ip}:8000"
    finally:
        subprocess.run(["podman", "rm", "-f", name], capture_output=True, check=False)


@pytest.fixture(scope="module")
def source(data_root: Path, model: str) -> Path:
    path = copy_fixture("miniapp-llm", data_root)
    ip = model.split(":", maxsplit=1)[0]
    (path / "server" / "config.ts").write_text(
        f'export const MODEL_URL = "http://{model}/v1/chat/completions";\n'
        f'export const OTHER_URL = "http://{ip}:8001/";\n'  # not allowed
    )
    (path / "app.toml").write_text(
        'apiVersion = "handler.miniapp/v1"\nname = "ask"\nversion = "1.0.0"\n'
        f'[needs]\negress = ["{model}"]\nsecrets = ["LLM_KEY"]\n'
    )
    return path


def test_registered_with_its_needs(daemon: Daemon, source: Path, model: str) -> None:
    app = api(daemon, "POST", "/v1/apps", {"sourceDir": str(source)}).json()
    assert app["secrets"] == [{"name": "LLM_KEY", "set": False}]
    assert app["source"]["addedNeeds"] == [f"egress {model}", "secret LLM_KEY"]


def test_deploy_needs_the_secret(daemon: Daemon) -> None:
    r = api(daemon, "POST", "/v1/apps/ask/deploy")
    assert r.status_code == 422
    assert "secret LLM_KEY not set" in r.json()["detail"]


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


def test_calls_the_model_with_its_key(daemon: Daemon) -> None:
    r = api(daemon, "POST", "/v1/apps/ask/deploy")
    assert r.status_code == 200, api(daemon, "GET", "/v1/apps/ask/log").json()["text"]
    browser = AppClient(daemon, "ask")
    browser.login(api(daemon, "POST", "/v1/apps/ask/open").json()["url"])
    answer = browser.request_json("POST", "/api/ask", {"text": "hello"})
    assert answer == {"answer": f"echo:hello auth:Bearer {KEY}"}


def test_other_hosts_are_refused(daemon: Daemon) -> None:
    browser = AppClient(daemon, "ask")
    browser.login(api(daemon, "POST", "/v1/apps/ask/open").json()["url"])
    other = browser.request("GET", "/api/other").json()
    assert other["reached"] is False
    assert "net access" in other["error"]  # Deno's own permission, before the proxy


def test_log_hides_the_secret(daemon: Daemon) -> None:
    log = api(daemon, "GET", "/v1/apps/ask/log").json()["text"]
    assert "starting with key [secret LLM_KEY]" in log
    assert KEY not in log


def test_unset_secret_stops_the_app(daemon: Daemon) -> None:
    r = api(daemon, "DELETE", "/v1/apps/ask/secrets/LLM_KEY")
    assert r.json()["secrets"] == [{"name": "LLM_KEY", "set": False}]
    assert r.json()["state"] == "stopped"
    browser = AppClient(daemon, "ask")
    browser.login(api(daemon, "POST", "/v1/apps/ask/open").json()["url"])
    r = browser.request("GET", "/api/health")
    assert r.status_code == 503
    assert "secret LLM_KEY not set" in r.text
