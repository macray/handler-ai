"""Contract A.3, injections: the sandbox holds a phantom, its proxy gives the secret's value
towards the secret's hosts only. Against the tests' local echo server (runtimes.local_server: by
address, plain http://, no internet), which checks and echoes credentials; the tunnels the proxy
decrypts, against real hosts (their certificates)."""

import json
import secrets
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from ...support.runtimes import Runtime
from ..conftest import requires_egress, run, spec

CURL = "curl -s -m 20"
STATUS = "-o /dev/null -w '%{http_code}'"


@pytest.fixture
def server(runtime: Runtime) -> Iterator[str]:
    """The secret's host: the echo server, its address and port."""
    with runtime.local_server() as address:
        yield f"{address}:8000"


def _pair() -> tuple[str, str]:
    value = "sk-test-" + secrets.token_hex(12)
    return value, "sk-test-" + secrets.token_hex(12)  # as long as the value


def _injection(value: str, phantom: str, host: str) -> dict[str, Any]:
    return {"name": "tests/token", "phantom": phantom, "value": value, "hosts": [host]}


def _filtered(*allow: str) -> dict[str, Any]:
    return {"mode": "filtered", "allow": list(allow), "enforcement": "enforce"}


def _curl(url: str, options: str = "") -> str:
    """Retried while the echo server, just started, does not listen yet (the proxy's 502)."""
    return f"{CURL} --retry 5 --retry-connrefused {options} '{url}'"


def _events(stderr: bytes) -> list[dict[str, str]]:
    lines = stderr.decode().splitlines()
    return [
        json.loads(x.removeprefix("handler-egress "))
        for x in lines
        if x.startswith("handler-egress ")
    ]


@pytest.mark.rule("secrets.the-sandbox-never-holds-a-secret")
def test_value_reaches_its_host_in_place_of_the_phantom(
    runtime: Runtime, scope: Path, server: str
) -> None:
    """The echo server's basic-auth answers 200 only when the credentials are the ones in its
    path: the value. The sandbox sends the phantom (in `Basic` credentials, base64)."""
    value, phantom = _pair()
    basic = _curl(f"http://{server}/basic-auth/user/{value}", f"{STATUS} -u user:{phantom}")
    echo = _curl(f"http://{server}/anything?key={phantom}", f"-H 'Authorization: Bearer {phantom}'")
    script = (
        f"echo basic=$({basic}); echo echoed=$({echo} | grep -c {phantom}); echo env=$SSL_CERT_FILE"
    )
    doc = spec(scope, ["sh", "-c", script], network=_filtered(server))
    doc["network"]["injections"] = [_injection(value, phantom, server)]
    r = run(runtime.binary, doc, unchained=True)
    out = dict(line.split("=", 1) for line in r.stdout.decode().split())
    assert out["basic"] == "200", r.stderr.decode()[-2000:]
    # the value the server echoes (header and query) comes back as the phantom
    assert out["echoed"] == "3"  # args.key, headers.Authorization, url
    assert value not in r.stdout.decode()
    assert out["env"] == "/run/handler/ca-bundle.pem"
    injected = [e for e in _events(r.stderr) if e["decision"] == "injected"]
    assert {"decision": "injected", "host": server, "secret": "tests/token"} in injected


@pytest.mark.rule("secrets.only-their-hosts-are-decrypted")
@requires_egress
def test_only_secret_hosts_are_decrypted(runtime: Runtime, scope: Path) -> None:
    """A secret host's tunnel is decrypted (signed by the proxy's CA, which the sandbox trusts)
    and the phantom swapped in it; another host stays a tunnel with its own certificate: the
    image's roots verify it, not those of a secret host."""
    value, phantom = _pair()
    own = f"--cacert /cacert.pem {STATUS}"  # the curl image's roots
    script = (
        f"echo other=$({CURL} {own} https://www.example.org);"
        f"echo secret_host=$({CURL} {own} https://example.com);"
        f"echo injected=$({CURL} {STATUS} -H 'X-Key: {phantom}' https://example.com)"
    )
    secret_host = "example.com:443"
    doc = spec(scope, ["sh", "-c", script], network=_filtered(secret_host, "www.example.org:443"))
    doc["network"]["injections"] = [_injection(value, phantom, secret_host)]
    r = run(runtime.binary, doc)
    out = dict(line.split("=", 1) for line in r.stdout.decode().split())
    assert out["other"] not in ("", "000")
    assert out["secret_host"] == "000"
    assert out["injected"] not in ("", "000")
    injected = {"decision": "injected", "host": secret_host, "secret": "tests/token"}
    assert injected in _events(r.stderr)


@pytest.mark.rule("secrets.a-phantom-going-elsewhere-is-refused")
def test_phantom_elsewhere_is_a_leak(runtime: Runtime, scope: Path, server: str) -> None:
    """A phantom the proxy sees going to another host (plain http here) is refused and reported,
    before anything reaches it."""
    value, phantom = _pair()
    elsewhere = server.replace(":8000", ":8001")
    script = f"{CURL} {STATUS} -H 'X-Key: {phantom}' http://{elsewhere}/"
    doc = spec(scope, ["sh", "-c", script], network=_filtered(server, elsewhere))
    doc["network"]["injections"] = [_injection(value, phantom, server)]
    r = run(runtime.binary, doc, unchained=True)
    assert r.stdout.decode() == "403"
    leak = {"decision": "leak", "host": elsewhere, "secret": "tests/token"}
    assert leak in _events(r.stderr)


@pytest.mark.rule("secrets.an-open-sandbox-gets-a-filter-for-them")
def test_open_sandbox_gets_a_proxy_for_its_secrets(
    runtime: Runtime, scope: Path, server: str
) -> None:
    value, phantom = _pair()
    script = _curl(f"http://{server}/basic-auth/user/{value}", f"{STATUS} -u user:{phantom}")
    doc = spec(scope, ["sh", "-c", script], network={"mode": "open"})
    doc["network"]["injections"] = [_injection(value, phantom, server)]
    r = run(runtime.binary, doc, unchained=True)
    assert r.stdout.decode() == "200", r.stderr.decode()[-2000:]
    assert not [e for e in _events(r.stderr) if e["decision"] in ("allowed", "unlisted")]


@pytest.mark.rule("secrets.a-phantom-is-as-long-as-its-value")
def test_phantom_as_long_as_its_value(runtime: Runtime, scope: Path) -> None:
    value, _ = _pair()
    doc = spec(scope, ["true"], network=_filtered("example.com:443"))
    doc["network"]["injections"] = [_injection(value, "sk-short-phantom", "example.com:443")]
    assert run(runtime.binary, doc).returncode == 65
