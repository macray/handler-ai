#!/usr/bin/env bash
# Local CI: everything must pass before a milestone is considered done.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
# Virtual envs: UV_PROJECT_ENVIRONMENT (default .venv), HANDLER_VENV_PY312 (default .venv-py312) and
# HANDLER_GATEWAY_VENV (the gateway's, default remote-gateway/.venv).
# Use separate locations when the checkout is shared between machines/containers.

step() { printf '\n\033[1m== %s\033[0m\n' "$*"; }

step "sync (locked)"
uv sync --locked

step "schemas up to date"
uv run python -m handler_contracts.schemas --check

step "lint + format"
uv run ruff check .
uv run ruff format --check .

step "typecheck (Linux, then macOS: its own code paths)"
uv run ty check
uv run ty check --python-platform darwin

step "shell scripts parse"
for f in scripts/*.sh; do bash -n "$f"; done

step "web apps (web UI, remote client): types from schemas, svelte-check, vitest, build"
scripts/build-web-ui.sh
git diff --exit-code -- packages/web-ui/src/lib/contracts.gen.ts \
    packages/remote-client/src/lib/remote.gen.ts \
    || { echo "generated types out of date: commit the regenerated files" >&2; exit 1; }

step "documentation website (scripts/build-docs-site.py): builds, no broken link"
scripts/build-docs-site.py

step "the handler-ai wheel (packaging/): builds, holds the web UI"
uv build --wheel packaging --out-dir "$(mktemp -d)" >/dev/null

step "remote gateway (independent project, its own virtualenv)"
(cd remote-gateway && UV_PROJECT_ENVIRONMENT="${HANDLER_GATEWAY_VENV:-.venv}" uv run --locked pytest)

# one worker per CPU; a test file stays on one worker (its module daemon and browser)
PYTEST_PARALLEL=(-n auto --dist loadfile)

step "unit + conformance tests (default Python)"
uv run pytest "${PYTEST_PARALLEL[@]}"

step "unit + conformance tests (Python 3.12, minimum supported)"
UV_PROJECT_ENVIRONMENT="${HANDLER_VENV_PY312:-.venv-py312}" uv run --locked --python 3.12 pytest "${PYTEST_PARALLEL[@]}"

printf '\n\033[32mCI OK\033[0m\n'
