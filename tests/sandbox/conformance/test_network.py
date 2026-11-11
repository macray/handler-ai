"""Contract A.3, A.4 conformance, every runtime: no network, open, filtered (allow-list, log only,
live changes), and the egress events."""

import json
import subprocess
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from ...support.runtimes import Runtime
from ..conftest import popen, requires_egress, requires_internet, run, spec

# Hosts no agent has a secret for: an agent running these tests chains to its own proxy, which
# decrypts its secrets' hosts with a CA these sandboxes do not trust.
ALLOW = {"mode": "filtered", "allow": ["www.example.org:443"], "enforcement": "enforce"}
CURL = "curl -s -m 10 -o /dev/null -w '%{http_code}'"
OUTCOMES = ("reached", "unreached")  # how a connection let through went (A.3), after its decision


def sh(script: str) -> list[str]:
    return ["sh", "-c", script]


def events(stderr: bytes) -> list[dict[str, str]]:
    return [
        json.loads(line.removeprefix("handler-egress "))
        for line in stderr.decode().splitlines()
        if line.startswith("handler-egress ")
    ]


@pytest.mark.rule("network.none-has-no-route")
def test_network_none_has_no_egress(runtime: Runtime, scope: Path) -> None:
    r = run(
        runtime.binary, spec(scope, sh("curl -s -m 5 -o /dev/null https://1.1.1.1; echo rc=$?"))
    )
    assert r.stdout.decode().strip() not in ("", "rc=0")


@requires_internet
def test_network_open_has_egress(runtime: Runtime, scope: Path) -> None:
    doc = spec(scope, sh(f"{CURL} https://www.example.org"), network={"mode": "open"})
    assert run(runtime.binary, doc).stdout.decode() not in ("", "000")


@pytest.fixture
def local_servers(runtime: Runtime) -> Iterator[tuple[str, str]]:
    """Two local destinations (by address: no internet, no DNS), one to list, one not: the
    filter's decisions alone are tested, not the internet."""
    with runtime.local_server() as listed, runtime.local_server() as unlisted:
        yield listed, unlisted


def local_filter(address: str, enforcement: str = "enforce") -> dict[str, Any]:
    return {"mode": "filtered", "allow": [f"{address}:8000"], "enforcement": enforcement}


def fetch(address: str) -> str:
    """Its status through the sandbox's proxy: 200, or the proxy's 403. Retried while the
    server, just started, does not listen yet (the proxy answers 502)."""
    return f"{CURL} --retry 5 --retry-connrefused http://{address}:8000/"


@pytest.mark.rule(
    "network.filtered-fails-closed", "network.enforcement-decides", "network.decisions-are-seen"
)
def test_filtered_enforce(runtime: Runtime, scope: Path, local_servers: tuple[str, str]) -> None:
    listed, unlisted = local_servers
    script = (
        f"echo allowed=$({fetch(listed)});"
        f"echo denied=$({fetch(unlisted)});"
        f"curl -s -m 5 --noproxy '*' -o /dev/null http://{listed}:8000/; echo direct_rc=$?"
    )
    r = run(runtime.binary, spec(scope, sh(script), network=local_filter(listed)), unchained=True)
    out = dict(line.split("=", 1) for line in r.stdout.decode().split())
    assert (out["allowed"], out["denied"]) == ("200", "403"), r.stderr.decode()
    assert out["direct_rc"] != "0"  # only its proxy reaches out
    found = events(r.stderr)
    assert {"decision": "denied", "host": f"{unlisted}:8000"} in found
    assert {"decision": "allowed", "host": f"{listed}:8000"} in found


@pytest.mark.rule("network.a-stopped-filter-ends-its-sandbox", "sandbox.leaves-nothing-behind")
def test_a_filter_that_stops_ends_its_sandbox(runtime: Runtime, scope: Path) -> None:
    """Its filter killed (out of memory, by hand), a filtered sandbox is ended within seconds:
    its launcher says why, last, and exits 67 (A.1); nothing is left of either."""
    filtered = {"mode": "filtered", "allow": [], "enforcement": "enforce"}
    doc = spec(scope, sh("echo started; sleep 600"), network=filtered)
    proc = popen(runtime.binary, doc, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        assert proc.stdout is not None and proc.stderr is not None
        assert proc.stdout.readline() == b"started\n"
        runtime.kill(f"{doc['name']}-proxy")
        code = proc.wait(timeout=60)
        said = [line for line in proc.stderr.read().decode().splitlines()
                if line.startswith("handler-sandbox-")]  # fmt: skip
    finally:
        proc.kill()
    assert code == 67, said
    assert said and said[-1].endswith("its network filter stopped, so the sandbox was ended")
    assert runtime.leftovers(doc["name"]) == []


@pytest.mark.rule("network.enforcement-decides")
def test_filtered_log_only_reports_unlisted(
    runtime: Runtime, scope: Path, local_servers: tuple[str, str]
) -> None:
    """Log only lets everything through, and reports what enforcing would deny (A.3, A.4)."""
    listed, unlisted = local_servers
    net = local_filter(listed, "log-only")
    script = f"{fetch(listed)}; echo; {fetch(unlisted)}"
    r = run(runtime.binary, spec(scope, sh(script), network=net), unchained=True)
    assert r.stdout.decode().split() == ["200", "200"], r.stderr.decode()  # both went through
    found = events(r.stderr)
    assert {"decision": "allowed", "host": f"{listed}:8000"} in found
    assert {"decision": "unlisted", "host": f"{unlisted}:8000"} in found


def test_a_plain_http_answer_passes_as_it_comes(runtime: Runtime, scope: Path) -> None:
    """The filter passes a body on as it arrives, never holding it whole: a large download would
    take its memory (an Apple container filter has 1 GiB, and died of it). Its first line
    reaches the sandbox while the server is still sending the others (3 s)."""
    with runtime.local_server() as server:
        url = f"http://{server}:8000"
        timing = "-w '%{http_code} %{time_starttransfer} %{time_total}'"
        script = f"{CURL} --retry 5 --retry-connrefused {url}/ >/dev/null; curl -s -N -o /dev/null {timing} {url}/drip/6"
        doc = spec(scope, sh(script), network=local_filter(server))
        r = run(runtime.binary, doc, unchained=True)
    status, first, total = r.stdout.decode().split()
    assert status == "200", r.stderr.decode()
    assert float(first) < 1.5 and float(total) >= 2.5, r.stdout.decode()


@pytest.mark.rule("network.an-entry-is-a-host-and-its-port", "network.every-request-is-judged")
@requires_egress
def test_filtered_plain_http_goes_through_the_proxy(runtime: Runtime, scope: Path) -> None:
    """http:// (e.g. a local model server) uses the sandbox's proxy variables like https://, and
    an entry allows its own port only (A.3): ':80' is not ':443', nor the reverse."""
    http_only = {"mode": "filtered", "allow": ["www.example.org:80"], "enforcement": "enforce"}
    probes = [
        f"{CURL} http://www.example.org",  # :80 listed
        f"{CURL} https://www.example.org",  # :443 not listed
        f"{CURL} http://example.com",  # not listed
        f"{CURL} -p http://www.example.org:80",  # tunnel to :80: the entry's port, allowed
    ]
    r = run(runtime.binary, spec(scope, sh("; echo; ".join(probes)), network=http_only))
    allowed, https, other, tunnel = r.stdout.decode().split()
    assert allowed not in ("", "000")  # reached through the proxy
    assert https == "000" and other in ("000", "403")  # refused by the proxy
    assert tunnel not in ("", "000")
    r = run(runtime.binary, spec(scope, sh(f"{CURL} http://www.example.org"), network=ALLOW))
    assert r.stdout.decode() in ("000", "403")  # only :443 listed


@pytest.mark.rule("network.every-request-is-judged")
def test_filtered_plain_http_is_judged_on_a_real_host(
    runtime: Runtime, scope: Path, local_servers: tuple[str, str]
) -> None:
    """A.3 with the proxy as on every host (not chained to a development proxy): each plain
    http:// request is judged by its host and port, a tunnel by its target. (mitmproxy makes a
    forwarded request's target relative before the addon sees it: such a request once went
    through unjudged.)"""
    local_server = local_servers[0]
    net = {"mode": "filtered", "allow": [f"{local_server}:8000"], "enforcement": "enforce"}
    probes = [
        f"{CURL} --retry 5 --retry-connrefused http://{local_server}:8000/",  # listed
        f"{CURL} http://{local_server}:8001/",  # not listed: the proxy answers, not the host
        f"{CURL} -p http://{local_server}:8001/",  # a tunnel to it
    ]
    doc = spec(scope, sh("; echo; ".join(probes)), network=net)
    r = run(runtime.binary, doc, unchained=True)
    listed, other, tunnel = r.stdout.decode().split()
    assert (listed, other, tunnel) == ("200", "403", "000"), r.stderr.decode()
    found = events(r.stderr)
    assert {"decision": "allowed", "host": f"{local_server}:8000"} in found
    assert found.count({"decision": "denied", "host": f"{local_server}:8001"}) == 2


@pytest.mark.rule("network.an-outcome-is-seen", "network.decisions-are-seen")
def test_a_connection_that_fails_is_recorded_with_its_error(
    runtime: Runtime, scope: Path, local_servers: tuple[str, str]
) -> None:
    """A.3: after its decision, each connection's outcome. An allowed host that answers is
    `reached`; one allowed where nothing listens (a model server not started, or listening on
    127.0.0.1 only) is `unreached` with why, as a plain request and a tunnel; a refused one stays
    `denied`, never connected."""
    listed, unlisted = local_servers
    net = {"mode": "filtered", "allow": [f"{listed}:8000", f"{listed}:8001"]}
    probes = [
        fetch(listed),
        f"{CURL} http://{listed}:8001/",  # allowed, nothing listens there
        f"{CURL} -p http://{listed}:8001/",  # the same, a tunnel
        f"{CURL} http://{unlisted}:8000/",  # refused
    ]
    doc = spec(scope, sh("; echo; ".join(probes)), network=net | {"enforcement": "enforce"})
    r = run(runtime.binary, doc, unchained=True)
    assert r.stdout.decode().split() == ["200", "502", "000", "403"], r.stderr.decode()
    found = events(r.stderr)
    assert {"decision": "reached", "host": f"{listed}:8000"} in found
    failed = {"decision": "unreached", "host": f"{listed}:8001", "error": "connection refused"}
    assert found.count(failed) == 2, found
    assert {"decision": "denied", "host": f"{unlisted}:8000"} in found
    assert not [e for e in found if e["host"] == f"{unlisted}:8000" and e["decision"] != "denied"]


BLOCKED = "Blocked by Handler's network filter: ask the user to allow"


@pytest.mark.rule("network.a-refusal-says-why")
def test_a_refused_request_says_it_is_the_filter(
    runtime: Runtime, scope: Path, local_servers: tuple[str, str]
) -> None:
    """A.3: the 403's reason phrase names the filter and the host, for a tunnel (which most
    clients answer with its status line alone) and a plain http:// request; the body says what
    to do. Seen by what the clients print: curl, Python's urllib, pip."""
    listed, unlisted = local_servers
    net = local_filter(listed)
    probes = [
        f"curl -sS -v -m 10 https://{unlisted}:8000/",  # a tunnel: the status line only
        f"curl -sS -m 10 http://{unlisted}:8000/",  # plain: the body
    ]
    r = run(runtime.binary, spec(scope, sh("; ".join(probes)), network=net), unchained=True)
    curl = r.stdout.decode() + r.stderr.decode()
    assert f"< HTTP/1.1 403 {BLOCKED} {unlisted}:8000" in curl, curl
    assert f"Blocked by Handler's network filter: {unlisted}:8000 is not in" in curl
    assert "ask the user to allow it" in curl and "Never try to get around the filter" in curl

    # Python's urllib and pip, as an agent runs them (pip towards the index nobody allowed), in
    # the filter's image: its program is mitmdump, which runs this script as it loads it
    probe = scope / "probe.py"
    probe.write_text(
        "import os, subprocess, sys, urllib.request\n"
        "try:\n"
        f"    urllib.request.urlopen('https://{unlisted}:8000/', timeout=10)\n"
        "except OSError as e:\n"
        "    print(e, flush=True)\n"
        # one retry: pip prints the proxy's answer in its retry warnings (5 by default)
        "pip = ['download', '--no-cache-dir', '--retries', '1', '--timeout', '10', 'requests']\n"
        "subprocess.run([sys.executable, '-m', 'pip', *pip, '-d', '/tmp/p'])\n"
        "sys.stdout.flush()\n"
        "os._exit(0)\n"
    )
    doc = spec(scope, ["-q", "-s", str(probe)], network=net, image=runtime.server_image)
    r = run(runtime.binary, doc, unchained=True)
    printed = r.stdout.decode() + r.stderr.decode()
    assert f"Tunnel connection failed: 403 {BLOCKED} {unlisted}:8000" in printed, printed
    assert f"Tunnel connection failed: 403 {BLOCKED} pypi.org:443" in printed, printed


KEPT_BLOCKED = "Blocked by Handler's network filter on the user's choice: do not ask for"


@pytest.mark.rule("network.a-host-kept-blocked-is-not-asked-for")
@pytest.mark.rule("network.live-changes-apply-at-the-next-request")
def test_a_host_kept_blocked_is_refused_as_the_user_s_choice(
    runtime: Runtime, scope: Path, local_servers: tuple[str, str]
) -> None:
    """A.3, A.4: a host the user keeps blocked is refused with its own text (do not ask for it,
    go on without it), an undecided one with the first (ask the user to allow it); `set-blocked`
    changes the list of a running sandbox, from its next request."""
    listed, unlisted = local_servers
    kept, undecided = f"{unlisted}:8000", f"{unlisted}:8001"
    status = "echo \"$(curl -sS -v -m 10 https://{}/ 2>&1 | grep '< HTTP')\""
    steps = "; ".join(
        f"read x; {status.format(kept)}; {status.format(undecided)}" for _ in range(2)
    )
    doc = spec(scope, sh(steps), network=local_filter(listed) | {"blocked": [kept]})
    proc = popen(
        runtime.binary,
        doc,
        unchained=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )
    assert proc.stdin is not None and proc.stdout is not None
    stdin, stdout = proc.stdin, proc.stdout

    def step() -> tuple[str, str]:
        stdin.write(b"go\n")
        stdin.flush()
        return stdout.readline().decode().strip(), stdout.readline().decode().strip()

    try:
        assert step() == (
            f"< HTTP/1.1 403 {KEPT_BLOCKED} {kept}, go on without it.",
            f"< HTTP/1.1 403 {BLOCKED} {undecided}",
        )
        set_blocked = [runtime.binary, "set-blocked", doc["name"], undecided]
        subprocess.run(set_blocked, check=True, timeout=30)  # in force once it returns (A.4)
        assert step() == (
            f"< HTTP/1.1 403 {BLOCKED} {kept}",  # undecided again: still refused
            f"< HTTP/1.1 403 {KEPT_BLOCKED} {undecided}, go on without it.",
        )
        assert proc.wait(timeout=30) == 0
    finally:
        proc.kill()


@pytest.mark.rule("network.a-watched-request-waits-for-the-answer")
@pytest.mark.rule("network.every-request-is-judged")
def test_a_watched_request_waits_for_the_answer(
    runtime: Runtime, scope: Path, local_servers: tuple[str, str]
) -> None:
    """A.3, A.4: while someone watches (`set-watched NAME TURN`), a request to a host neither
    allowed nor kept blocked waits; allowed meanwhile (`set-allow`), it goes through, a plain
    http:// request as a tunnel. Nobody watching (`set-watched NAME`), it is refused at once."""
    listed, unlisted = local_servers
    tunnel = f"curl -s -m 30 -o /dev/null -w '%{{http_code}}' https://{unlisted}:8001/"
    both = f"{fetch(unlisted)} > /tmp/plain & {tunnel} > /tmp/tunnel & wait"  # held together
    first = f"read x; {both}; echo $(cat /tmp/plain) $(cat /tmp/tunnel)"
    steps = f"{first}; read x; echo $({fetch(unlisted)})"
    doc = spec(scope, sh(steps), network=local_filter(listed))
    proc = popen(
        runtime.binary,
        doc,
        unchained=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert proc.stdin is not None and proc.stdout is not None and proc.stderr is not None
    stdin, stdout, stderr = proc.stdin, proc.stdout, proc.stderr
    lines: list[bytes] = []  # its stderr as it comes: the filter's events, to wait for them
    reader = threading.Thread(target=lambda: lines.extend(iter(stderr.readline, b"")), daemon=True)
    reader.start()
    verb = lambda *args: subprocess.run([runtime.binary, *args], check=True, timeout=30)  # noqa: E731
    try:
        # its filter is found once it started: tried again meanwhile (as handlerd does)
        watch = [runtime.binary, "set-watched", doc["name"], "1"]
        deadline = time.monotonic() + 60
        while subprocess.run(watch, check=False, timeout=30).returncode:
            assert time.monotonic() < deadline, "its filter never started"
            time.sleep(0.2)
        stdin.write(b"go\n")
        stdin.flush()
        # both held (their `held` events), then allowed well within the hold window; under
        # load the two requests may reach the filter late
        deadline = time.monotonic() + 30
        while sum(e["decision"] == "held" for e in events(b"".join(lines[:]))) < 2:
            assert time.monotonic() < deadline, f"not both held: {events(b''.join(lines[:]))}"
            time.sleep(0.1)
        verb("set-allow", doc["name"], f"{listed}:8000", f"{unlisted}:8000", f"{unlisted}:8001")
        plain, tunnel_status = stdout.readline().decode().split()
        assert plain == "200"
        assert tunnel_status != "403"  # through to the server (which speaks no TLS)
        verb("set-allow", doc["name"], f"{listed}:8000")
        verb("set-watched", doc["name"])
        started = time.monotonic()
        stdin.write(b"go\n")
        stdin.flush()
        assert stdout.readline().decode().strip() == "403"
        assert time.monotonic() - started < 5
        assert proc.wait(timeout=30) == 0
    finally:
        proc.kill()
        reader.join(timeout=30)
    found = events(b"".join(lines[:]))
    decisions = [(e["decision"], e["host"]) for e in found if e["decision"] not in OUTCOMES]
    held, answered = decisions[:2], decisions[2:4]
    assert sorted(held) == [("held", f"{unlisted}:8000"), ("held", f"{unlisted}:8001")]
    assert sorted(answered) == [("allowed", f"{unlisted}:8000"), ("allowed", f"{unlisted}:8001")]
    assert decisions[4:] == [("denied", f"{unlisted}:8000")], decisions


@pytest.mark.rule("network.an-entry-is-a-host-and-its-port")
@requires_egress
def test_filtered_wildcard(runtime: Runtime, scope: Path) -> None:
    net = {"mode": "filtered", "allow": ["*.example.org:443"], "enforcement": "enforce"}
    r = run(runtime.binary, spec(scope, sh(f"{CURL} https://www.example.org"), network=net))
    assert r.stdout.decode() not in ("", "000")
    exact = {"mode": "filtered", "allow": ["example.org:443"], "enforcement": "enforce"}
    doc = spec(scope, sh(f"{CURL} https://www.example.org; echo rc=$?"), network=exact)
    assert "rc=0" not in run(runtime.binary, doc).stdout.decode()


def _stepper(proc: subprocess.Popen[bytes]) -> Callable[[], str]:
    assert proc.stdin is not None and proc.stdout is not None
    stdin, stdout = proc.stdin, proc.stdout

    def step() -> str:
        stdin.write(b"go\n")
        stdin.flush()
        line: bytes = stdout.readline()
        return line.decode().strip()

    return step


@pytest.mark.rule("network.live-changes-apply-at-the-next-request")
def test_set_egress_live_switch(
    runtime: Runtime, scope: Path, local_servers: tuple[str, str]
) -> None:
    listed, unlisted = local_servers
    probe = fetch(unlisted)
    doc = spec(
        scope, sh(f"read a; {probe}; echo; read b; {probe}; echo; read c; {probe}; echo"),
        network=local_filter(listed),
    )  # fmt: skip
    proc = popen(
        runtime.binary,
        doc,
        unchained=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )
    step = _stepper(proc)

    def set_egress(mode: str) -> None:  # in force once it returns (A.4)
        subprocess.run([runtime.binary, "set-egress", doc["name"], mode], check=True, timeout=30)

    try:
        assert step() == "403"  # enforce
        set_egress("log-only")
        assert step() == "200"  # log only: everything allowed, still logged
        set_egress("enforce")
        assert step() == "403"  # back to enforce, same running process
        assert proc.wait(timeout=30) == 0
    finally:
        proc.kill()


@pytest.mark.rule("network.live-changes-apply-at-the-next-request")
def test_set_allow_live(runtime: Runtime, scope: Path, local_servers: tuple[str, str]) -> None:
    """`set-allow` replaces a running instance's allow-list, enforcement kept (A.4)."""
    listed, unlisted = local_servers
    steps = "; ".join(f"read x; {fetch(unlisted)}; echo" for _ in range(4))
    base = local_filter(listed)
    doc = spec(scope, sh(steps), network=base)
    proc = popen(
        runtime.binary,
        doc,
        unchained=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )
    step = _stepper(proc)
    set_allow_cmd = [runtime.binary, "set-allow", doc["name"]]

    def set_allow(*entries: str) -> None:  # in force once it returns (A.4)
        subprocess.run([*set_allow_cmd, *entries], check=True, timeout=30)

    try:
        assert step() == "403"  # not listed
        for entry in ("a.com\n.*:443", "example.com"):  # never written into the filter
            bad = subprocess.run([*set_allow_cmd, entry], timeout=30, check=False)
            assert bad.returncode == 65
        set_allow(f"{unlisted}:8001", *base["allow"])
        assert step() == "403"  # its port is not listed
        set_allow(f"{unlisted}:8000", *base["allow"])
        assert step() == "200"  # listed now, same running process
        set_allow(*base["allow"])
        assert step() == "403"  # removed again
        assert proc.wait(timeout=30) == 0
    finally:
        proc.kill()
