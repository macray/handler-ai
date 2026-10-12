"""`handler automation …` against a real handlerd (I.9)."""

import re
from pathlib import Path

from ..cli.test_cli import handler
from ..support.daemon import Daemon
from .test_automations import conversation


def test_the_cli_drives_an_automation(daemon: Daemon, knowledge: Path) -> None:
    assert "env-issues" in handler(daemon, "automation", "examples").stdout
    made = handler(daemon, "automation", "new", "by-cli", "--from", "env-issues")
    assert made.returncode == 0 and "created, off" in made.stdout
    toml = daemon.config_dir / "automations" / "by-cli" / "automation.toml"
    toml.write_text(
        toml.read_text()
        .replace("mistral/mistral-large-latest", "stub/m")
        .replace("handler/env-issues.md", "handler/by-cli.md")
    )
    shown = handler(daemon, "automation", "show", "by-cli").stdout
    assert "May call the models stub/m." in shown and "extract.py" in shown
    assert "Appends what it writes to the notes handler/by-cli.md." in shown
    listed = handler(daemon, "automation", "list").stdout
    assert "by-cli" in listed and "when a session stops" in listed

    agent = daemon.create_ad_hoc("fake", daemon.make_scope())
    conversation(daemon, agent)
    tried = handler(daemon, "automation", "try", "by-cli")  # the session that stopped last
    assert tried.returncode == 0, tried.stderr
    assert "would add" in tried.stdout and "npm: command not found" in tried.stdout
    assert not (knowledge / "handler" / "by-cli.md").exists()
    run_id = tried.stdout.split()[0]
    assert "1 finding(s)" in handler(daemon, "automation", "log", run_id).stdout

    refused = handler(daemon, "automation", "enable", "by-cli")  # asks; no answer: stays off
    assert refused.returncode != 0
    assert handler(daemon, "automation", "enable", "by-cli", "--yes").returncode == 0
    assert "by-cli  on" in handler(daemon, "automation", "list").stdout
    assert handler(daemon, "automation", "disable", "by-cli").stdout.strip() == "by-cli: off"
    assert run_id in handler(daemon, "automation", "runs", "by-cli").stdout
    kept = handler(daemon, "automation", "delete", "by-cli")  # asks; no answer: kept
    assert kept.returncode == 1 and "with every file in it" in kept.stdout
    assert toml.exists()
    deleted = handler(daemon, "automation", "delete", "by-cli", "--yes")
    assert deleted.stdout.strip().endswith("by-cli: deleted") and not toml.parent.exists()
    assert "by-cli" not in handler(daemon, "automation", "list").stdout


def test_the_cli_shows_a_schedule_and_the_inbox(daemon: Daemon) -> None:
    folder = daemon.config_dir / "automations" / "cli-hourly"
    folder.mkdir(parents=True)
    (folder / "automation.toml").write_text(
        'apiVersion = "handler.automation/v1"\nwhen = { every = "2h" }\nrun = "exit 4"\n'
    )
    listed = handler(daemon, "automation", "list").stdout
    assert re.search(r"cli-hourly +off +every 2h +a script", listed), listed
    on = handler(daemon, "automation", "enable", "cli-hourly", "--yes").stdout
    assert "Starts every 2h" in on and "cli-hourly: on, next run " in on
    assert "Next run: " in handler(daemon, "automation", "show", "cli-hourly").stdout
    tried = handler(daemon, "automation", "try", "cli-hourly")  # no session: a scheduled one
    assert tried.returncode == 1 and "exited with 4" in tried.stdout
    assert "inbox" in handler(daemon, "--help").stdout
    assert handler(daemon, "inbox").returncode == 0
    handler(daemon, "automation", "disable", "cli-hourly")
