"""`handler plan …` against a real handlerd (D.27)."""

import pytest

from ..cli.test_cli import handler
from ..support.daemon import Daemon
from .test_plans import PLAN, project, wait_plan


@pytest.mark.rule("plan.started-by-you-only", "plan.what-runs-is-what-you-approved")
def test_the_cli_reads_approves_and_follows_a_plan(daemon: Daemon) -> None:
    folder, _ = project(daemon)
    checked = handler(daemon, "plan", "check", "plans/p.md", cwd=folder)
    assert checked.returncode == 0, checked.stderr
    assert (
        "Plan: two steps" in checked.stdout
        and "Agent: dev · each step at most 3 h" in checked.stdout
    )
    assert "2. The second" in checked.stdout and "problem" not in checked.stdout

    asked = handler(daemon, "plan", "run", "plans/p.md", cwd=folder)  # asks; no answer: not run
    assert asked.returncode != 0 and "Approve and run it?" in asked.stdout
    assert "no plan" in handler(daemon, "plan", "list").stdout

    ran = handler(daemon, "plan", "run", str(folder / "plans" / "p.md"), "--yes")
    assert ran.returncode == 0, ran.stderr
    plan_id = ran.stdout.split("(")[-1].split(")")[0]
    wait_plan(daemon, plan_id, "done")
    listed = handler(daemon, "plan", "list").stdout
    assert plan_id in listed and "done" in listed and "2/2" in listed
    shown = handler(daemon, "plan", "show", plan_id).stdout
    assert "State: done (2/2 steps done)" in shown and "step 2 done" in shown
    assert "its session: handler attach s_" in shown
    cancelled = handler(daemon, "plan", "cancel", plan_id)
    assert cancelled.returncode == 1 and "not running" in cancelled.stderr
    assert handler(daemon, "plan", "delete", plan_id, "--yes").returncode == 0
    assert plan_id not in handler(daemon, "plan", "list").stdout


@pytest.mark.rule("plan.stops-at-the-first-failure")
def test_the_cli_says_why_a_plan_stopped_and_runs_it_again(daemon: Daemon) -> None:
    folder, _ = project(daemon, PLAN.format(first="fake: failed"))
    ran = handler(daemon, "plan", "run", "plans/p.md", "--yes", cwd=folder)
    plan_id = ran.stdout.split("(")[-1].split(")")[0]
    wait_plan(daemon, plan_id, "stopped")
    shown = handler(daemon, "plan", "show", plan_id).stdout
    assert "stopped: step 1 failed: step 1 failed" in shown
    assert f"handler plan run {plan_id} --from 1" in shown
    again = handler(daemon, "plan", "run", plan_id, "--from", "1")
    assert again.returncode == 0 and "running again from step 1" in again.stdout
    wait_plan(daemon, plan_id, "stopped")  # the same step fails again


def test_the_cli_shows_a_plans_problems(daemon: Daemon) -> None:
    folder, _ = project(daemon, PLAN.format(first="").replace("Agent: dev\n", ""))
    checked = handler(daemon, "plan", "check", "plans/p.md", cwd=folder)
    assert checked.returncode == 1 and "problem: no `Agent:` line" in checked.stdout
    outside = handler(daemon, "plan", "check", "/tmp/nowhere.md")
    assert (
        outside.returncode == 1
        and "no agent of yours works in a folder holding it" in outside.stderr
    )


@pytest.mark.rule("plan.what-runs-is-what-you-approved")
def test_the_cli_reads_and_approves_a_draft(daemon: Daemon) -> None:
    _, dev = project(daemon)
    with daemon.http() as c:
        draft = c.post("/v1/plan-drafts", json={"projectId": dev["projectId"]}).json()
    text = daemon.config_dir.parent / "state" / "plan-drafts" / draft["id"] / "draft" / "plan.md"
    text.write_text(PLAN.format(first=""))  # its builder writes
    checked = handler(daemon, "plan", "check", draft["id"])
    assert checked.returncode == 0, checked.stderr
    assert "Plan: two steps   (plan.md)" in checked.stdout
    ran = handler(daemon, "plan", "run", draft["id"], "--yes")
    assert ran.returncode == 0, ran.stderr
    plan_id = ran.stdout.split("(")[-1].split(")")[0]
    wait_plan(daemon, plan_id, "done")
    assert ", a draft · approved" in handler(daemon, "plan", "show", plan_id).stdout


@pytest.mark.rule("plan.a-refused-host-is-reported")
def test_the_cli_shows_the_hosts_refused_to_a_step_and_in_the_inbox(daemon: Daemon) -> None:
    folder, _ = project(daemon, PLAN.format(first="fake: blocked pypi.org:443 2"))
    ran = handler(daemon, "plan", "run", "plans/p.md", "--yes", cwd=folder)
    plan_id = ran.stdout.split("(")[-1].split(")")[0]
    wait_plan(daemon, plan_id, "done")
    shown = handler(daemon, "plan", "show", plan_id).stdout
    assert "hosts refused: pypi.org:443 (2 times)" in shown
    assert "the agent said: I could not reach pypi.org, so I used the local copy." in shown
    inbox = handler(daemon, "inbox").stdout
    assert "hosts refused, to allow or keep blocked" in inbox
    assert "Step 1 completed: The first: pypi.org:443 (2 times)" in inbox


@pytest.mark.rule("plan.a-refused-host-is-reported")
def test_the_cli_allows_a_host_refused_to_a_step_and_runs_it_again(daemon: Daemon) -> None:
    folder, agent = project(daemon, PLAN.format(first="fake: failed fake: blocked pypi.org:443 1"))
    ran = handler(daemon, "plan", "run", "plans/p.md", "--yes", cwd=folder)
    plan_id = ran.stdout.split("(")[-1].split(")")[0]
    wait_plan(daemon, plan_id, "stopped")
    shown = handler(daemon, "plan", "show", plan_id).stdout
    assert "step 1 failed: pypi.org:443 was blocked by the network filter" in shown
    assert f"handler plan run {plan_id} --from 1 --allow pypi.org:443" in shown
    again = handler(daemon, "plan", "run", plan_id, "--from", "1", "--allow", "pypi.org:443")
    assert again.returncode == 0, again.stderr
    with daemon.http() as c:
        assert c.get(f"/v1/agents/{agent['id']}").json()["allow"] == ["pypi.org:443"]
    wait_plan(daemon, plan_id, "stopped")
