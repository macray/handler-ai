"""Egress decisions and events (A.3): what the proxy's addon decides for a target, judged against
the settings in force when the request comes (A.4), and how its events reach stderr."""

import io
import json
from pathlib import Path

from handler_sandbox_podman import egress
from handler_sandbox_podman.proxy import addon


def test_listed_matches_as_entries_say() -> None:
    allow = ["api.anthropic.com:443", "*.example.com:443", "llm.local:80"]
    assert addon.listed("api.anthropic.com:443", allow)
    assert addon.listed("API.Anthropic.com:443", allow)  # hosts compared without case
    assert addon.listed("a.b.example.com:443", allow)
    assert addon.listed("llm.local:80", allow)
    assert not addon.listed("api.anthropic.com:80", allow)  # its own port only
    assert not addon.listed("api.anthropic.com:4430", allow)
    assert not addon.listed("example.com:443", allow)  # a wildcard needs a subdomain
    assert not addon.listed("evil-api.anthropic.com:443", allow)
    assert not addon.listed("apixanthropic.com:443", allow)  # a dot is a dot
    assert not addon.listed("anything:443", [])


def test_decisions() -> None:
    allow = ["api.anthropic.com:443"]
    assert addon.decide("api.anthropic.com:443", allow, "enforce") == "allowed"
    assert addon.decide("example.com:443", allow, "enforce") == "denied"
    assert addon.decide("api.anthropic.com:443", allow, "log-only") == "allowed"
    assert addon.decide("example.com:443", allow, "log-only") == "unlisted"


def test_judge_follows_live_settings_and_records_events(tmp_path: Path) -> None:
    state = egress.EgressState(tmp_path)
    state.write(["api.anthropic.com:443"], "enforce")
    proxy = addon.Egress(tmp_path)
    assert proxy.judge("api.anthropic.com:443")
    assert not proxy.judge("example.com:443")
    state.write(["api.anthropic.com:443"], "log-only")  # set-egress
    assert proxy.judge("example.com:443")
    state.write(["example.com:443"], "enforce")  # set-allow
    assert proxy.judge("example.com:443")
    assert not proxy.judge("api.anthropic.com:443")
    lines = (tmp_path / egress.EVENTS_FILE).read_text().splitlines()
    assert [json.loads(line) for line in lines] == [
        {"decision": "allowed", "host": "api.anthropic.com:443"},
        {"decision": "denied", "host": "example.com:443"},
        {"decision": "unlisted", "host": "example.com:443"},
        {"decision": "allowed", "host": "example.com:443"},
        {"decision": "denied", "host": "api.anthropic.com:443"},
    ]


def test_watcher_reports_whole_lines_only(tmp_path: Path) -> None:
    events = tmp_path / egress.EVENTS_FILE
    events.write_text('{"decision": "denied", "host": "a.com:443"}\n{"decision": "all')
    out = io.StringIO()
    watcher = egress.EventWatcher(events, out)
    watcher.stop()  # one full read, then it returns
    watcher.run()
    assert out.getvalue() == 'handler-egress {"decision": "denied", "host": "a.com:443"}\n'
