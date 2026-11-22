#!/usr/bin/env bash
# Local CI: everything must pass before a milestone is considered done.
#
#   scripts/ci.sh            every check and every test, on the default Python and on 3.12
#   scripts/ci.sh TEST...    the checks and the unit tests, then those tests only (pytest paths or
#                            ids): a step while working, never the CI
#   scripts/ci.sh --fast     the checks and the unit tests alone (tiers 1 and 2)
#
# Three tiers, the fastest first, each stopping the run when it fails: 1. the checks (seconds),
# 2. the unit tests, the web apps and the docs, 3. every other test on both Pythons at once, with
# the wheel. A tier's steps run in parallel, each into its log, shown when it fails.
#
# A test that fails runs again alone (scripts/ci_pytest.py): if it passes then, it is FLAKY, the
# run passes, and the flake ledger keeps it. Once a day, the property tests also search with many
# more examples than the CI's fixed ones (Hypothesis's "explore" profile, conftest.py): a bug
# found there is said, not blamed on the change at hand.
#
# The flake ledger, the search's examples and a lock are kept in the repository's .git folder,
# shared by its worktrees and by the agents working on it here (HANDLER_CI_STATE to change it):
# the lock makes a second run's tests wait for the first's, as two at once overload the machine
# and make tests fail that nothing is wrong with.
#
# Virtual envs: UV_PROJECT_ENVIRONMENT (default .venv), HANDLER_VENV_PY312 (default .venv-py312)
# and HANDLER_GATEWAY_VENV (the gateway's, default remote-gateway/.venv). Use separate locations
# when the checkout is shared between machines/containers.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

export HANDLER_CI_STATE="${HANDLER_CI_STATE:-$(git rev-parse --path-format=absolute \
    --git-common-dir)/handler-ci}"
state="$HANDLER_CI_STATE"
mkdir -p "$state"
logs="$(mktemp -d)"
began=$SECONDS  # each job's pid and start time: files next to its log (macOS's bash 3.2 has no maps)

say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }

# start NAME COMMAND...: runs it in the background, into its log
start() {
    local name=$1
    shift
    echo $SECONDS >"$logs/$name.start"
    "$@" >"$logs/$name.log" 2>&1 &
    echo $! >"$logs/$name.pid"
}

# finish NAME...: waits for them; a failed one shows its log. Fails when one failed.
finish() {
    local name took failed=0
    for name in "$@"; do
        if wait "$(cat "$logs/$name.pid")"; then
            took=$((SECONDS - $(cat "$logs/$name.start")))
            printf '  \033[32m✓\033[0m %s (%ds)\n' "$name" "$took"
            # what a passing step still has to say: flaky tests, a bug found by the search
            sed -n '/FLAKY (/,$p; /FOUND (/,$p' "$logs/$name.log"
        else
            took=$((SECONDS - $(cat "$logs/$name.start")))
            printf '  \033[31m✗ %s\033[0m (%ds), its log:\n' "$name" "$took"
            tail -n 80 "$logs/$name.log" | sed 's/^/    /'
            failed=1
        fi
    done
    return $failed
}

stop() {
    printf '\n\033[31mCI FAILED\033[0m at %s (%ds); every log: %s\n' "$1" $((SECONDS - began)) "$logs"
    exit 1
}

# heavy: waits for another run's tests to end (flock: Linux; elsewhere, no wait)
heavy() {
    command -v flock >/dev/null || return 0
    exec 9>"$state/tests.lock"
    flock -n 9 || { echo "  waiting for another CI run's tests to end…"; flock 9; }
}

# one worker per CPU; a file whose tests share a fixture (a module's handlerd, its browser) stays
# on one worker, any other file's tests spread (conftest.py)
parallel=(-n auto --dist loadgroup)
# the two Pythons' runs at once: half the CPUs each
cpus="$(getconf _NPROCESSORS_ONLN)"
half=(-n "$(((cpus + 1) / 2))" --dist loadgroup)
py312=(env UV_PROJECT_ENVIRONMENT="${HANDLER_VENV_PY312:-.venv-py312}" uv run --locked --python 3.12)

say "1. checks"
uv sync --locked --quiet
start "schemas up to date" uv run python -m handler_contracts.schemas --check
start "lint" uv run ruff check .
start "format" uv run ruff format --check .
start "types (Linux)" uv run ty check
start "types (macOS: its own code paths)" uv run ty check --python-platform darwin
start "shell scripts parse" bash -c 'for f in scripts/*.sh; do bash -n "$f"; done'
finish "schemas up to date" lint format "types (Linux)" "types (macOS: its own code paths)" \
    "shell scripts parse" || stop "the checks"

say "2. unit tests, web apps, docs"
start "unit tests" uv run python scripts/ci_pytest.py "unit tests" "${parallel[@]}" \
    packages tests/architecture
start "remote gateway" bash -c 'cd remote-gateway &&
    UV_PROJECT_ENVIRONMENT="${HANDLER_GATEWAY_VENV:-.venv}" uv run --locked pytest'
start "web apps" bash -c 'scripts/build-web-ui.sh && git diff --exit-code -- \
    packages/web-ui/src/lib/contracts.gen.ts packages/remote-client/src/lib/remote.gen.ts ||
    { echo "generated types out of date: commit the regenerated files" >&2; exit 1; }'
start "documentation website (builds, no broken link)" uv run python scripts/build-docs-site.py
finish "unit tests" "remote gateway" "web apps" "documentation website (builds, no broken link)" ||
    stop "the unit tests, web apps or docs"

if [ "${1:-}" = --fast ]; then
    printf '\n\033[33mPARTIAL: the checks and unit tests passed; not the CI\033[0m (%ds)\n' \
        $((SECONDS - began))
    exit 0
fi
if [ $# -gt 0 ]; then
    say "the tests asked for"
    heavy
    start "tests asked for" uv run python scripts/ci_pytest.py "tests asked for" "${parallel[@]}" "$@"
    finish "tests asked for" || stop "the tests asked for"
    printf '\n\033[33mPARTIAL: the tests asked for passed; not the CI\033[0m (%ds)\n' $((SECONDS - began))
    exit 0
fi

say "3. every test, both Pythons"
heavy
start "tests (default Python)" uv run python scripts/ci_pytest.py "default Python" "${half[@]}" \
    tests --ignore=tests/architecture
start "tests (Python 3.12, minimum supported)" "${py312[@]}" python scripts/ci_pytest.py \
    "Python 3.12" "${half[@]}"
start "the handler-ai wheel (holds the web UI)" uv build --wheel packaging --out-dir "$logs/wheel"
explore=()
if [ -z "$(find "$state/explored" -mmin -1440 2>/dev/null)" ]; then
    explore=("property tests' daily search")
    # at most 4 minutes, beside the tests: it never makes the CI longer than they are
    # macOS has no `timeout`: perl's alarm instead (its end: 142, SIGALRM, as timeout's 124)
    start "${explore[0]}" bash -c 'limit() { if command -v timeout >/dev/null; then timeout "$@"
        else perl -e "alarm shift; exec @ARGV" "$@"; fi; }
        out="$(limit 240 nice uv run pytest -n 4 --dist load \
        -m property --timeout=0 2>&1)"; case $? in
        0 | 124 | 142) ;;
        *) echo "FOUND (the daily search): a bug already there, not this change: write it in
    the bugs to fix. Its example is kept: the next search tries it first. What failed, on which
    input:"; grep -E "^(FAILED|E +[a-z_]+=)" <<<"$out" ;;
    esac'
    touch "$state/explored"
fi
finish "tests (default Python)" "tests (Python 3.12, minimum supported)" \
    "the handler-ai wheel (holds the web UI)" ${explore[@]+"${explore[@]}"} || stop "the tests"
# (`${explore[@]+…}`: macOS's bash 3.2 takes an empty array for an unset one under `set -u`)

printf '\n\033[32mCI OK\033[0m (%ds)\n' $((SECONDS - began))
