"""Contract A.3, injections: the sandbox holds a phantom, its proxy gives the secret's value
towards the secret's hosts only. Against httpbin.org, which checks and echoes credentials."""

import json
import secrets
from pathlib import Path
from typing import Any

from .conftest import requires_egress, requires_podman, run, spec

BIN = "handler-sandbox-podman"
pytestmark = [requires_podman, requires_egress]

SECRET_HOST = "httpbin.org:443"
CURL = "curl -s -m 20"


def _pair() -> tuple[str, str]:
    value = "sk-test-" + secrets.token_hex(12)
    return value, "sk-test-" + secrets.token_hex(12)  # as long as the value


def _injection(value: str, phantom: str) -> dict[str, Any]:
    return {"name": "tests/token", "phantom": phantom, "value": value, "hosts": [SECRET_HOST]}


def _filtered(*allow: str) -> dict[str, Any]:
    return {"mode": "filtered", "allow": [SECRET_HOST, *allow], "enforcement": "enforce"}


def _events(stderr: bytes) -> list[dict[str, str]]:
    lines = stderr.decode().splitlines()
    return [
        json.loads(x.removeprefix("handler-egress "))
        for x in lines
        if x.startswith("handler-egress ")
    ]


def test_value_reaches_its_host_in_place_of_the_phantom(scope: Path) -> None:
    """httpbin's basic-auth answers 200 only when the credentials are the ones in its path: the
    value. The sandbox sends the phantom (in `Basic` credentials, base64)."""
    value, phantom = _pair()
    script = (
        f"echo basic=$({CURL} -o /dev/null -w '%{{http_code}}' -u user:{phantom}"
        f" https://httpbin.org/basic-auth/user/{value});"
        f"echo echoed=$({CURL} -H 'Authorization: Bearer {phantom}'"
        f" 'https://httpbin.org/anything?key={phantom}' | grep -c {phantom});"
        f"echo env=$SSL_CERT_FILE"
    )
    doc = spec(scope, ["sh", "-c", script], network=_filtered())
    doc["injections"] = [_injection(value, phantom)]
    r = run(BIN, doc)
    out = dict(line.split("=", 1) for line in r.stdout.decode().split())
    assert out["basic"] == "200", r.stderr.decode()[-2000:]
    # the value httpbin echoes (header and query) comes back as the phantom
    assert out["echoed"] == "3"  # args.key, headers.Authorization, url
    assert value not in r.stdout.decode()
    assert out["env"] == "/run/handler/ca-bundle.pem"
    injected = [e for e in _events(r.stderr) if e["decision"] == "injected"]
    assert {"decision": "injected", "host": SECRET_HOST, "secret": "tests/token"} in injected


def test_only_secret_hosts_are_decrypted(scope: Path) -> None:
    """Another host stays a tunnel with its own certificate: the image's roots verify it, not
    those of a secret host (signed by the proxy's CA)."""
    value, phantom = _pair()
    own = "--cacert /cacert.pem -o /dev/null -w '%{http_code}'"  # the curl image's roots
    script = (
        f"echo other=$({CURL} {own} https://www.example.org);"
        f"echo secret_host=$({CURL} {own} https://httpbin.org/get)"
    )
    doc = spec(scope, ["sh", "-c", script], network=_filtered("www.example.org:443"))
    doc["injections"] = [_injection(value, phantom)]
    out = dict(line.split("=", 1) for line in run(BIN, doc).stdout.decode().split())
    assert out["other"] not in ("", "000")
    assert out["secret_host"] == "000"


def test_phantom_elsewhere_is_a_leak(scope: Path) -> None:
    """A phantom the proxy sees going to another host (plain http here) is refused and reported."""
    value, phantom = _pair()
    script = f"{CURL} -o /dev/null -w '%{{http_code}}' -H 'X-Key: {phantom}' http://example.com/"
    doc = spec(scope, ["sh", "-c", script], network=_filtered("example.com:80"))
    doc["injections"] = [_injection(value, phantom)]
    r = run(BIN, doc)
    assert r.stdout.decode() == "403"
    leak = {"decision": "leak", "host": "example.com:80", "secret": "tests/token"}
    assert leak in _events(r.stderr)


def test_open_sandbox_gets_a_proxy_for_its_secrets(scope: Path) -> None:
    value, phantom = _pair()
    script = (
        f"{CURL} -o /dev/null -w '%{{http_code}}' -u user:{phantom}"
        f" https://httpbin.org/basic-auth/user/{value}"
    )
    doc = spec(scope, ["sh", "-c", script], network={"mode": "open"})
    doc["injections"] = [_injection(value, phantom)]
    r = run(BIN, doc)
    assert r.stdout.decode() == "200"
    assert not [e for e in _events(r.stderr) if e["decision"] in ("allowed", "unlisted")]


def test_injections_need_a_network(scope: Path) -> None:
    value, phantom = _pair()
    doc = spec(scope, ["true"])
    doc["injections"] = [_injection(value, phantom)]
    assert run(BIN, doc).returncode == 65


def test_phantom_as_long_as_its_value(scope: Path) -> None:
    value, _ = _pair()
    doc = spec(scope, ["true"], network=_filtered())
    doc["injections"] = [_injection(value, "sk-short-phantom")]
    assert run(BIN, doc).returncode == 65
