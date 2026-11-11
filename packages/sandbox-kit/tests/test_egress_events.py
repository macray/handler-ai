"""Egress decisions and events: what the proxy's addon decides for a target, judged against the
settings in force when the request comes, and how its events reach stderr.

Spec: contract A.3 "Network semantics" and A.4 "Toggling network filtering"."""

import asyncio
import io
import json
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from handler_contracts import CONTAINER_HOST
from handler_sandbox_kit import egress
from handler_sandbox_kit.egress.proxy import addon


def recorded_events(directory: Path) -> list[dict[str, str]]:
    lines = (directory / egress.EVENTS_FILE).read_text().splitlines()
    return [json.loads(line) for line in lines]


# --- Allow-list matching (A.3 "Network semantics") ------------------------------------------------

ALLOW = ["api.anthropic.com:443", "*.example.com:443", "llm.local:80"]


@pytest.mark.rule("network.an-entry-is-a-host-and-its-port")
@pytest.mark.parametrize(
    ("target", "allowed"),
    [
        pytest.param("api.anthropic.com:443", True, id="exact-host-and-port"),
        pytest.param("API.Anthropic.com:443", True, id="host-case-ignored"),
        pytest.param("a.b.example.com:443", True, id="wildcard-matches-nested-subdomain"),
        pytest.param("llm.local:80", True, id="port-80-entry"),
        pytest.param("api.anthropic.com:80", False, id="same-host-other-port"),
        pytest.param("api.anthropic.com:4430", False, id="port-prefix-is-not-a-match"),
        pytest.param("example.com:443", False, id="wildcard-excludes-bare-domain"),
        pytest.param("evilexample.com:443", False, id="wildcard-needs-a-dot-before-its-domain"),
        pytest.param("evil-api.anthropic.com:443", False, id="lookalike-name"),
        pytest.param("api.anthropic.com.evil.com:443", False, id="listed-name-as-prefix"),
        pytest.param("apixanthropic.com:443", False, id="dot-is-literal-not-regex"),
    ],
)
def test_an_entry_allows_exactly_its_host_on_its_port(target: str, allowed: bool) -> None:
    """`host:port` allows that host on that port only; `*.domain:port` its subdomains only.
    If this fails: the filter lets out a destination nobody listed, or blocks a listed one."""
    assert addon.listed(target, ALLOW) is allowed


@pytest.mark.rule("network.filtered-fails-closed")
def test_an_empty_allow_list_allows_nothing() -> None:
    """No entry, no destination.
    If this fails: a filtered sandbox with no entries has open egress."""
    assert not addon.listed("anything:443", [])


# --- Decisions: enforce, log-only (A.3, A.4 "Toggling network filtering") -------------------------


@pytest.mark.rule("network.enforcement-decides")
@pytest.mark.parametrize(
    ("target", "enforcement", "decision"),
    [
        pytest.param("api.anthropic.com:443", "enforce", "allowed", id="enforce-listed"),
        pytest.param("example.com:443", "enforce", "denied", id="enforce-unlisted"),
        pytest.param("api.anthropic.com:443", "log-only", "allowed", id="log-only-listed"),
        pytest.param("example.com:443", "log-only", "unlisted", id="log-only-unlisted"),
    ],
)
def test_decision_for_each_enforcement_mode(target: str, enforcement: str, decision: str) -> None:
    """`enforce` denies what is not listed; `log-only` lets it through, reported `unlisted` (how
    one discovers the hosts a harness needs).
    If this fails: enforce lets unlisted hosts out, or log-only hides what enforce would deny."""
    assert addon.decide(target, ["api.anthropic.com:443"], enforcement) == decision


# --- Live settings: set-egress, set-allow (A.4 "Toggling network filtering") ----------------------


@pytest.mark.rule("network.filtered-fails-closed")
def test_the_proxy_denies_everything_before_reading_any_settings(tmp_path: Path) -> None:
    """Fail-closed by construction: no settings file yet means enforce, nothing allowed.
    If this fails: a proxy that starts before its settings are written lets everything out."""
    assert not addon.Egress(tmp_path).judge("api.anthropic.com:443")


@pytest.mark.rule("network.live-changes-apply-at-the-next-request")
def test_set_egress_log_only_applies_to_the_next_request(tmp_path: Path) -> None:
    """Switching to log-only takes effect at the next request, without a restart.
    If this fails: discovering a harness's hosts needs restarting the agent."""
    state, proxy = egress.EgressState(tmp_path), addon.Egress(tmp_path)
    state.write(["api.anthropic.com:443"], [], "enforce")
    assert not proxy.judge("example.com:443")
    state.write(["api.anthropic.com:443"], [], "log-only")
    assert proxy.judge("example.com:443")


@pytest.mark.rule("network.live-changes-apply-at-the-next-request")
def test_set_egress_back_to_enforce_denies_unlisted_hosts_at_the_next_request(
    tmp_path: Path,
) -> None:
    """Ending log-only takes effect at the next request, without a restart.
    If this fails: a running agent keeps reaching unlisted hosts after enforcing is switched on."""
    state, proxy = egress.EgressState(tmp_path), addon.Egress(tmp_path)
    state.write(["api.anthropic.com:443"], [], "log-only")
    assert proxy.judge("example.com:443")
    state.write(["api.anthropic.com:443"], [], "enforce")
    assert not proxy.judge("example.com:443")


@pytest.mark.rule("network.live-changes-apply-at-the-next-request")
def test_set_allow_removing_a_host_denies_it_at_the_next_request(tmp_path: Path) -> None:
    """set-allow replaces the list: a host no longer on it is denied without a restart.
    If this fails: revoking a host leaves it reachable by running agents."""
    state, proxy = egress.EgressState(tmp_path), addon.Egress(tmp_path)
    state.write(["api.anthropic.com:443"], [], "enforce")
    assert proxy.judge("api.anthropic.com:443")
    state.write(["example.com:443"], [], "enforce")
    assert proxy.judge("example.com:443")
    assert not proxy.judge("api.anthropic.com:443")


@pytest.mark.rule("network.a-live-change-returns-once-in-force")
def test_new_settings_are_acknowledged_only_once_the_proxy_used_them(tmp_path: Path) -> None:
    """set-egress and set-allow return once the proxy says the new settings are in force.
    If this fails: the verb reports success while the old settings still apply."""
    state, proxy = egress.EgressState(tmp_path), addon.Egress(tmp_path)
    first = state.write(["api.anthropic.com:443"], [], "enforce")
    proxy.judge("api.anthropic.com:443")
    assert state.wait_applied(first, timeout=0)
    later = state.write(["example.com:443"], [], "enforce")
    assert later == first + 1
    assert not state.wait_applied(later, timeout=0)  # written, not yet read by the proxy
    proxy.judge("example.com:443")
    assert state.wait_applied(later, timeout=0)


@pytest.mark.rule("network.unreadable-settings-keep-the-last")
@pytest.mark.parametrize("damage", ["missing", "half-written"])
def test_unreadable_settings_keep_those_read_last(tmp_path: Path, damage: str) -> None:
    """A settings file the proxy cannot read leaves the settings it read last in force. It
    happens: a shared folder may lose the file a moment while it is replaced (Apple container's),
    or show it half written.
    If this fails: during a set-allow on Apple container, the proxy denies listed hosts or
    errors, for a moment."""
    state, proxy = egress.EgressState(tmp_path), addon.Egress(tmp_path)
    state.write(["example.com:443"], [], "enforce")
    proxy.judge("example.com:443")
    settings = tmp_path / egress.SETTINGS_FILE
    if damage == "missing":
        settings.unlink()
    else:
        settings.write_text("{")
    assert proxy.judge("example.com:443")
    assert not proxy.judge("api.anthropic.com:443")


# --- Held while someone watches (A.3 "Network semantics", A.4 set-watched) -----------------------


def admitted_after(proxy: addon.Egress, target: str, answer: Callable[[], object] | None) -> bool:
    """Whether a request for `target` goes through, `answer` given 0.2 s after it came."""

    async def run() -> bool:
        request = asyncio.ensure_future(proxy.admit(target))
        await asyncio.sleep(0.2)
        if answer is not None:
            answer()
        return await request

    return asyncio.run(run())


@pytest.mark.rule("network.a-watched-request-waits-for-the-answer")
def test_a_held_request_goes_through_once_the_host_is_allowed(tmp_path: Path) -> None:
    """While someone watches, the first request to an undecided host waits; allowed meanwhile,
    it goes through.
    If this fails: the person allows a host the agent asked for, and its request still failed."""
    state, proxy = egress.EgressState(tmp_path), addon.Egress(tmp_path)
    state.write([], [], "enforce", watched="7")
    allow = lambda: state.write(["pypi.org:443"], [], "enforce", watched="7")  # noqa: E731
    assert admitted_after(proxy, "pypi.org:443", allow)
    assert recorded_events(tmp_path) == [
        {"decision": "held", "host": "pypi.org:443", "wait": addon.HOLD},
        {"decision": "allowed", "host": "pypi.org:443"},
    ]


@pytest.mark.rule("network.a-watched-request-waits-for-the-answer")
@pytest.mark.rule("network.filtered-fails-closed")
def test_a_held_request_is_refused_when_the_window_ends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No answer within the window: refused, then refused at once for the rest of the turn; a
    new turn holds it again.
    If this fails: a held request goes through unallowed, or the agent waits at every retry."""
    monkeypatch.setattr(addon, "HOLD", 0.5)
    state, proxy = egress.EgressState(tmp_path), addon.Egress(tmp_path)
    state.write([], [], "enforce", watched="7")
    assert not admitted_after(proxy, "pypi.org:443", None)
    assert not admitted_after(proxy, "pypi.org:443", None)
    state.write([], [], "enforce", watched="8")
    assert not admitted_after(proxy, "pypi.org:443", None)
    decisions = [e["decision"] for e in recorded_events(tmp_path)]
    assert decisions == ["held", "denied", "denied", "held", "denied"]


@pytest.mark.rule("network.a-watched-request-waits-for-the-answer")
@pytest.mark.parametrize("why", ["nobody watches", "kept blocked"])
def test_a_request_is_refused_at_once_when_nobody_watches_or_the_host_is_kept_blocked(
    tmp_path: Path, why: str
) -> None:
    """Nobody to answer, or an answer already given: no wait.
    If this fails: an unattended agent loses seconds at every refused request, or waits for a
    host the person already refused."""
    state, proxy = egress.EgressState(tmp_path), addon.Egress(tmp_path)
    if why == "nobody watches":
        state.write([], [], "enforce")
    else:
        state.write([], ["pypi.org:443"], "enforce", watched="7")
    started = time.monotonic()
    assert not admitted_after(proxy, "pypi.org:443", None)
    assert time.monotonic() - started < 0.5
    assert recorded_events(tmp_path) == [{"decision": "denied", "host": "pypi.org:443"}]


@pytest.mark.rule("network.a-watched-request-waits-for-the-answer")
def test_requests_to_a_host_being_held_wait_with_it(tmp_path: Path) -> None:
    """A second request while the host is held waits with the first: one wait, one card.
    If this fails: a client's parallel connections each wait in turn, past its timeout."""
    state, proxy = egress.EgressState(tmp_path), addon.Egress(tmp_path)
    state.write([], [], "enforce", watched="7")

    async def run() -> list[bool]:
        requests = [asyncio.ensure_future(proxy.admit("pypi.org:443")) for _ in range(2)]
        await asyncio.sleep(0.2)
        state.write(["pypi.org:443"], [], "enforce", watched="7")
        return list(await asyncio.gather(*requests))

    assert asyncio.run(run()) == [True, True]
    held = [e for e in recorded_events(tmp_path) if e["decision"] == "held"]
    assert len(held) == 1


# --- Events: denials observable (A.3 "Network semantics") -----------------------------------------


@pytest.mark.rule("network.decisions-are-seen")
def test_every_judgement_is_recorded_as_an_event(tmp_path: Path) -> None:
    """A denied request MUST be observable; `unlisted` is what log-only reports.
    If this fails: denials go unseen, or log-only discovers nothing."""
    state, proxy = egress.EgressState(tmp_path), addon.Egress(tmp_path)
    state.write(["api.anthropic.com:443"], [], "enforce")
    proxy.judge("api.anthropic.com:443")
    proxy.judge("example.com:443")
    state.write(["api.anthropic.com:443"], [], "log-only")
    proxy.judge("example.com:443")
    assert recorded_events(tmp_path) == [
        {"decision": "allowed", "host": "api.anthropic.com:443"},
        {"decision": "denied", "host": "example.com:443"},
        {"decision": "unlisted", "host": "example.com:443"},
    ]


@pytest.mark.rule("secrets.an-open-sandbox-gets-a-filter-for-them")
def test_an_open_sandbox_s_proxy_lets_everything_through_and_records_nothing(
    tmp_path: Path,
) -> None:
    """An `open` sandbox with secrets gets a proxy for its injections only: it filters nothing
    and reports nothing else.
    If this fails: an open sandbox with secrets is filtered, or its events list every host."""
    egress.EgressState(tmp_path).write([], [], "open")
    proxy = addon.Egress(tmp_path)
    assert proxy.judge("example.com:443")
    assert not (tmp_path / egress.EVENTS_FILE).exists()


class Server:
    """What mitmproxy's server connection hooks give (`data.server`)."""

    def __init__(self, address: tuple[str, int], error: str | None = None) -> None:
        self.id, self.address, self.error = f"{address}", address, error


class Data:
    def __init__(self, server: Server) -> None:
        self.server = server


def connect(proxy: addon.Egress, address: tuple[str, int], error: str | None = None) -> None:
    """One connection to `address`, its outcome given by mitmproxy: connected, or `error`."""
    data = Data(Server(address))
    proxy.server_connect(data)
    data.server.error = error
    if error is None:
        proxy.server_connected(data)
    else:
        proxy.server_connect_error(data)


@pytest.mark.rule("network.an-outcome-is-seen")
def test_each_connection_s_outcome_is_recorded_with_its_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After a request's decision, how its connection went: `reached`, or `unreached` with why,
    in a few words; on the name the agent asked for, also where the runtime gave the host's
    address.
    If this fails: a host that never answered shows as reached, or its error is lost."""
    egress.EgressState(tmp_path).write([f"{ALIAS}:3000", "a.org:443"], [], "enforce")
    monkeypatch.setenv(addon.HOST_ADDRESS_ENV, HOST_IP)
    proxy = addon.Egress(tmp_path)
    connect(proxy, ("a.org", 443))
    connect(proxy, (ALIAS, 3000), f"[Errno 111] Connect call failed ('{HOST_IP}', 3000)")
    connect(proxy, ("b.org", 443), "[Errno -2] Name or service not known")
    connect(proxy, ("c.org", 443), "TLS handshake broke")
    assert recorded_events(tmp_path) == [
        {"decision": "reached", "host": "a.org:443"},
        {"decision": "unreached", "host": f"{ALIAS}:3000", "error": "connection refused"},
        {"decision": "unreached", "host": "b.org:443", "error": "host not found"},
        {"decision": "unreached", "host": "c.org:443", "error": "TLS handshake broke"},
    ]


@pytest.mark.rule("network.an-outcome-is-seen")
@pytest.mark.parametrize(
    ("chained", "enforcement"),
    [pytest.param(True, "enforce", id="chained"), pytest.param(False, "open", id="open")],
)
def test_no_outcome_is_recorded_chained_or_open(
    tmp_path: Path, chained: bool, enforcement: egress.Filtering
) -> None:
    """Chained to a development proxy every connection is to that proxy, not the host; an open
    sandbox's proxy reports nothing.
    If this fails: the panel says a host was reached when only the development proxy was."""
    egress.EgressState(tmp_path).write([], [], enforcement)
    proxy = addon.Egress(tmp_path)
    proxy.chained = chained
    connect(proxy, ("a.org", 443))
    connect(proxy, ("b.org", 443), "[Errno 111] Connect call failed")
    assert not (tmp_path / egress.EVENTS_FILE).exists()


@pytest.mark.rule("network.decisions-are-seen")
def test_the_watcher_reports_whole_event_lines_only(tmp_path: Path) -> None:
    """Events reach stderr prefixed `handler-egress`; a line still being written waits.
    If this fails: the control plane reads half an event (broken JSON) or none."""
    events = tmp_path / egress.EVENTS_FILE
    events.write_text('{"decision": "denied", "host": "a.com:443"}\n{"decision": "all')
    out = io.StringIO()
    watcher = egress.EventWatcher(events, out)
    watcher.stop()  # one full read, then it returns
    watcher.run()
    assert out.getvalue() == 'handler-egress {"decision": "denied", "host": "a.com:443"}\n'


# --- The host's services: host.containers.internal (A.3 "Network semantics") ----------------------

ALIAS = CONTAINER_HOST
HOST_IP = "192.168.64.1"  # where Apple container's default network has the host


@pytest.mark.rule("network.the-computer-is-reachable-by-name")
def test_the_addon_s_copy_of_the_host_name_matches_the_contract() -> None:
    """The addon runs in the proxy's image, without handler_contracts: it keeps its own copy of
    the name sandboxes reach the host by.
    If this fails: the two have drifted, and the filter no longer recognises that name."""
    assert addon.HOST_ALIAS == CONTAINER_HOST


@pytest.mark.rule("network.the-computer-is-reachable-by-name")
@pytest.mark.parametrize(
    ("address", "host_ip", "connects_to"),
    [
        pytest.param((ALIAS, 3000), HOST_IP, (HOST_IP, 3000), id="alias-goes-to-the-host-s-ip"),
        pytest.param(("HOST.containers.internal", 80), HOST_IP, (HOST_IP, 80), id="alias-case"),
        pytest.param(("example.org", 443), HOST_IP, ("example.org", 443), id="other-host-kept"),
        pytest.param((ALIAS, 3000), None, (ALIAS, 3000), id="no-ip-given-alias-kept"),
    ],
)
def test_the_host_alias_connects_to_the_address_the_runtime_gave(
    address: tuple[str, int], host_ip: str | None, connects_to: tuple[str, int]
) -> None:
    """On a runtime whose network does not resolve host.containers.internal (Apple container),
    the filter connects to the address the runtime gave it; the decision stays on the name.
    If this fails: sandboxes cannot reach the host's services through the filter."""
    assert addon.host_address(address, host_ip) == connects_to
