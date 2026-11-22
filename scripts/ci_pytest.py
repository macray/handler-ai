"""One pytest run of the local CI (scripts/ci.sh), which tells a flaky test from a broken one.

    python scripts/ci_pytest.py NAME [PYTEST_ARGS...]

Runs pytest with PYTEST_ARGS. When tests fail, and not too many (a broken change fails many),
it runs those again, alone and one after the other:

- each one that passes then is FLAKY: it failed under the parallel run, not on its own. The run
  passes (no need to start the whole CI again), says so loudly, and adds a line to the flake
  ledger with the error it gave; a test seen there before is named with its count: fix it.
- each one that fails again is a failure: the run fails.

The ledger is one file for the repository's checkouts on this machine (its worktrees, the agents
working on it): `$HANDLER_CI_STATE/flaky.tsv` (default: `handler-ci/` in its .git folder),
tab-separated: when, the run's NAME, the test, its error's first line, the commit.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

RERUN_AT_MOST = 15  # more failures than this: the change broke something, no test is flaky
RED, YELLOW, BOLD, RESET = "\033[31m", "\033[33m", "\033[1m", "\033[0m"


def state_dir() -> Path:
    if path := os.environ.get("HANDLER_CI_STATE"):
        return Path(path)
    git = ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"]
    return Path(subprocess.run(git, capture_output=True, text=True, check=True).stdout.strip()) / (
        "handler-ci"
    )


def pytest(args: list[str], out: Path) -> int:
    """pytest, its cache (what failed) and its JUnit report (why) in `out`."""
    command = [sys.executable, "-m", "pytest", *args, "-o", f"cache_dir={out}"]
    return subprocess.run([*command, f"--junitxml={out / 'junit.xml'}"], check=False).returncode


def failures(out: Path) -> dict[str, str]:
    """The failed tests' ids (pytest's, from its cache), each with its error's first line."""
    cache = out / "v/cache/lastfailed"
    # `--dist loadgroup` names a grouped test `path::name@group`: pytest selects it without
    ids = [i.split("@")[0] for i in json.loads(cache.read_text())] if cache.exists() else []
    errors: dict[tuple[str, str], str] = {}
    if (out / "junit.xml").exists():
        for case in ET.parse(out / "junit.xml").iter("testcase"):
            problem = case.find("failure")
            if problem is None:
                problem = case.find("error")
            if problem is not None:
                lines = (problem.get("message") or problem.text or "").strip().splitlines()
                errors[case.get("classname") or "", case.get("name") or ""] = (
                    lines[0][:200] if lines else ""
                )
    found = {}
    for test in ids:
        path, _, rest = test.partition("::")
        *classes, function = rest.split("::")
        module = ".".join([path.removesuffix(".py").replace("/", "."), *classes])
        found[test] = errors.get((module, function), "")
    return found


def commit() -> str:
    run = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=False
    )
    return run.stdout.strip() or "?"


def record(name: str, flaky: dict[str, str]) -> dict[str, int]:
    """Writes the flaky tests to the ledger; returns how often each one is there now."""
    ledger = state_dir() / "flaky.tsv"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    when, at = time.strftime("%Y-%m-%d %H:%M"), commit()
    with ledger.open("a") as f:
        for test, error in flaky.items():
            f.write("\t".join([when, name, test, error.replace("\t", " "), at]) + "\n")
    seen: dict[str, int] = {}
    for line in ledger.read_text().splitlines():
        test = line.split("\t")[2]
        if test in flaky:
            seen[test] = seen.get(test, 0) + 1
    return seen


def main(name: str, args: list[str]) -> int:
    with tempfile.TemporaryDirectory() as tmp:
        first, again = Path(tmp) / "first", Path(tmp) / "again"
        if pytest(args, first) == 0:
            return 0
        failed = failures(first)
        if not failed or len(failed) > RERUN_AT_MOST:
            return 1  # no test to run again (an error before them), or too many: broken
        print(f"\n{BOLD}== {name}: {len(failed)} failed, each one again, alone{RESET}", flush=True)
        if pytest(["-p", "no:xdist", "-q", *failed], again) in (0, 1):
            still = failures(again)
        else:
            still = failed  # it could not run them (interrupted, an internal error)
    flaky = {test: error for test, error in failed.items() if test not in still}
    if flaky:
        seen = record(name, flaky)
        print(f"\n{YELLOW}{BOLD}FLAKY ({name}): failed in the parallel run, passed alone{RESET}")
        for test, error in flaky.items():
            times = f" — {seen[test]} times in the ledger: fix it" if seen[test] > 1 else ""
            print(f"{YELLOW}  {test}{times}\n      {error}{RESET}")
        print(f"  (ledger: {state_dir() / 'flaky.tsv'})")
    if still:
        print(f"\n{RED}{BOLD}FAILED ({name}), alone too:{RESET}")
        for test in still:
            print(f"{RED}  {test}{RESET}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2:]))
