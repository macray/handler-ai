# CLAUDE.md

This file guides coding agents (Claude Code; Codex and others read it as `AGENTS.md`) working in
this repository.

## What this is

Handler runs AI agent harnesses (Claude Code, Codex, Mistral Vibe, pi) in
rootless Podman sandboxes and drives them over ACP (Agent Client Protocol) from a web UI, the `handler`
CLI, editors (`handler acp`), a scheduler, or a paired phone. Single user, local machine.

Read first: the README of the package you work in (what it implements, what it may import) and
its tests (what it promises); the concepts as users see them: `docs/concepts.md`. Code and
commits cite the contracts by letter and section (`contract D.8`, `A.3`: A sandbox, B harness,
C ACP endpoint and policy, D Control API, E accounts and providers, F sessions, G addons, H apps,
I automations), each one's models in `packages/contracts`.

## Commands

The checkout may be shared between the host and sandboxes/containers: `.venv` points at the host's
Python, and a plain `uv run` elsewhere recreates it and breaks the host's venv. Outside the host,
set `UV_PROJECT_ENVIRONMENT` to a separate location (also `HANDLER_VENV_PY312`, `HANDLER_GATEWAY_VENV` for
`ci.sh`). In a Handler sandbox, uv's own folders may be read-only: `UV_TOOL_DIR`,
`UV_TOOL_BIN_DIR` and `UV_PYTHON_INSTALL_DIR` under `/tmp` too (the docs site, Python 3.12).

```bash
uv sync
./scripts/ci.sh                               # full local CI: schemas, ruff, ty, web apps, gateway, pytest on default Python and 3.12
uv run ruff check . && uv run ruff format --check .
uv run ty check                               # type check (warnings are errors)
uv run pytest -n auto --dist loadfile         # every test, in parallel (as ci.sh)
uv run pytest tests/control/test_api.py::test_name   # single test
uv run pytest packages/control-plane/tests    # one package's unit tests
HANDLER_TEST_OFFLINE=1 uv run pytest tests/sandbox  # skip network-dependent tests
uv run python -m handler_contracts.schemas    # regenerate schemas/ after changing contracts (ci checks with --check)
scripts/build-web-ui.sh [--quick]             # bun workspace: gen types from schemas, svelte-check, vitest, build
(cd packages/web-ui && bun run test)          # web UI unit tests only
(cd remote-gateway && uv run pytest)          # independent project, own lockfile/venv
handler image rebuild toolbox                 # (handlerd running) toolbox image then the harness images already built
scripts/build-wheel.sh                        # the `handler-ai` wheel users install (packaging/), web UI inside
scripts/smoke-install.sh                      # that wheel via scripts/install.sh in a bare container
scripts/build-docs-site.py [serve]            # documentation website (Zensical), stops on a broken link
```

Many conformance/e2e tests need built images or real credentials and skip otherwise; credential
tests are opt-in via `HANDLER_TEST_CLAUDE_CONFIG_DIR` (+ `_JSON`), `HANDLER_TEST_MISTRAL_API_KEY`,
`HANDLER_TEST_OPENAI_API_KEY`, `HANDLER_TEST_SHOPIFY_STORE` + `HANDLER_TEST_SHOPIFY_THEME_TOKEN`. The tests
read a made-up source (`tests/fixtures/source/`) as the official one; those of Handler's real registry items
are opt-in via `HANDLER_TEST_REGISTRY` (a checkout of a registry; Planner and shopify are in the
private one only, and their tests skip on a registry without them). When running
as root (dev container with nested rootful podman), `tests/support/dev_env.py` drops keep-id and runs
sandboxes as uid 1000 with scopes under `/var/tmp/handler-tests`.

The full suite takes ~25 s on 24 cores. A test may take 120 s (pyproject's `timeout`; those
pulling or building images, running real harnesses or a browser: `dev_env.IMAGE_TIMEOUT`); a
"Timeout" failure prints the stack where it hung. Inside a Handler sandbox (an agent's: only an HTTP
proxy out, nested podman, no harness images) ~80 tests skip, expectedly: those needing built
images, and the few needing a direct connection (`requires_internet`). The egress-filter tests
(`requires_egress`) run there: the conformance tests chain the sandboxes' proxies to the agent's
own (`HANDLER_SANDBOX_DEV_UPSTREAM_PROXY`, never on a real host). A skip there is the environment; a
failure is not.

What the sandbox tests can prove depends on where they run (`tests/support/place.py`); the end of
a run that includes `tests/sandbox` prints "where the sandbox tests ran": the place, and what each
runtime was tested for. On macOS, the Mac's runtimes (Apple container, Docker Desktop, OrbStack);
on a Linux host, Podman and Docker when installed, strict, nested and privileged; in a Linux
container (a Handler sandbox), Podman or Docker, strict and nested, never privileged. A skip of
what that summary does not list is the place. To prove one runtime: `HANDLER_TEST_STRICT=1
HANDLER_TEST_RUNTIMES=podman uv run pytest tests/sandbox`, which fails, instead of skipping,
when that runtime or a confinement it declares cannot run where it should (as CI does,
`.github/workflows/tests.yml`; macOS CI runs no sandbox: its runners have no nested
virtualization).

Changing a contract model means also: regenerating `schemas/`, then the TypeScript types with
`bun run gen:types` (repo root: `packages/web-ui/src/lib/contracts.gen.ts` from `handler.control.v1.*`,
`packages/remote-client/src/lib/remote.gen.ts` from `handler.remote.v1.*`; commit them, CI fails on
diff).

## Architecture

Blocks with hard boundaries that exchange **data, not imports**. Import rules are enforced by
`tests/architecture/test_boundaries.py` (a new `packages/*/src/handler_*` package must be added there,
and every package needs a README; inside the control plane, a module imports only from its layer
or lower ones, and a new module gets a layer in `CONTROL_LAYERS`, see its README):

- `packages/contracts` (`handler_contracts`): pydantic models of every contract — the only shared
  library. JSON Schemas in `schemas/` are generated from it; TypeScript types are generated from those.
- `packages/sandbox-podman` (contract A): reached **only as an executable** (`handler-sandbox-podman`,
  `SandboxSpec` on fd 3, stdio = the agent's ACP stream; `image …` verbs for images, A.7), never
  imported; the only block that calls podman. Container isolation and
  confinement levels live here; the egress allow-list proxy (the network filter) in
  `packages/sandbox-kit` (`handler_sandbox_kit`), shared by sandbox runtimes only, by import.
- `packages/harness-adapters` (`handler_harness`, contract B): pure `render(descriptor, AgentSpec…) → HarnessLaunch`,
  plus `handler-harness` CLI. Harness-specific knowledge lives only here and in data dirs
  `handler_harness/data/`: `harnesses/<name>/` (`harness.toml` + Containerfile), the built-in
  `tools/<name>/` (`app-builder`; tools are `addons` in the code), the default `toolbox/` (copied
  to the user's `~/.config/handler-ai/toolbox/` on handlerd's first start: the shared base image;
  the user's tools are in `~/.config/handler-ai/tools/`, those Handler offers in its sources, G.5).
  Per-harness provider config writers: `handler_harness/providers.py`.
- `packages/control-plane` (`handler_control`, daemon `handlerd`): the only block composing others. Control
  API (HTTP, contract D, `api/`: one module per contract section, routes only translate HTTP; the
  rules an agent or a project must pass before it is saved: `save_rules.py`), ACP WebSocket endpoint
  with the P1–P9 policy pipeline (`policy.py`, `relay.py`),
  `compose.py` combines the render output + the agent's sandbox settings + its addons into a
  `SandboxSpec`.
  Also sessions, projects, apps, remote control, builds.
- `packages/cli` (`handler_cli`): a pure client of handlerd over HTTP/WebSocket; may import only contracts.
- `packages/web-ui` (Svelte 5 + TS, shadcn-svelte, Tailwind), `packages/remote-client` (phone),
  both using `packages/acp-view` for session rendering; one bun workspace at the repo root.
- `remote-gateway/`: independent project with its own `pyproject.toml`/`uv.lock`; it must not
  import handler.

Key runtime model: an **agent** = harness on an account or provider × scope (host folder, mounted
rw at the **same absolute path**) × its settings. A **project** groups a folder and its agents; an
**ad-hoc agent** has no project (made by `handler run`/`acp`/`terminal` outside projects). Plain agent
ACP connections get one ephemeral sandbox each; daemon-held **sessions** (contract F) own a sandbox
that outlives WebSocket attachments and are what the web UI, `handler run/start/attach`, runs and
phones use. Configuration is TOML in `~/.config/handler-ai/`: `accounts/`, `providers/`, `connections/`
(tool × credentials; `bindings` in the code), `skills/`, `folders.toml`; examples in `examples/`. Agents and projects
are daemon state (`~/.local/state/handler-ai/agents.json`, `projects.json`).

## Design principles

- Hard rule: no sandbox ever reaches Handler's own files (the token, `secrets.json`, accounts,
  providers, bindings, automations, agents and projects state), read or write, whatever the
  feature: only a subfolder made for it. A feature that
  seems to need it (an agent drafting an automation, say) goes through the Control API on the
  owner's request instead.

- Clear boundaries: each concept and block has one responsibility, stated in one sentence; when a
  thing seems to belong to two places, the model is wrong, fix the model.
- KISS: build what is needed now and no more. No speculative options, layers or extension points.
- Handler has users: a change to the format of what they keep (`~/.config/handler-ai/`, Handler's
  state and data) comes with a migration, and only there. One module in
  `packages/control-plane/src/handler_control/migrations/` (`m<NNNN>_<what>.py`, appended to
  `MIGRATIONS`) rewrites the old format into the new one; handlerd runs it once, at start, before
  anything reads those files. Everywhere else the code knows the current format only: no
  compatibility shims, no fallbacks reading both, no "this moved" errors. The release's
  `CHANGELOG.md` entry says what changed for the user. Contracts with no stored data (the Control
  API, the CLI's flags) change without migrations, in the same release as all their clients.
- "models" and "boundaries" should help to build a "mental model" of the application or a part of the application. This
  mental model must be clear and easy to understand
- Everything the application can do is visible: no option kept in the code but hidden from the UI
  (or reachable only by hand-editing a file), no defensive code for cases that cannot happen. A
  hidden capability gets forgotten and clutters the code. If an option is not used, remove it
  completely (contract, code, UI, docs); if it is kept, show it (with a warning when it weakens the
  sandbox).

## Conventions

- Frontend tasks (web UI, phone client, acp-view, CLI output and help, `docs/`): the words
  are the person's, the same in the UI, the CLI and the docs; never the code's shorthand.
- Vendors' terms: Handler runs the vendors' own harnesses on the person's own subscriptions. The
  sign-in is the vendor's (Handler shows the command, never runs a token sign-in nor reads its
  output); an account is for the person's own use; an agent that runs unattended (a job, an
  automation, a plan's steps) is recommended an API key, and a Claude subscription is for sessions
  the person starts and follows, or a plan they approved to run; Handler's own names and logos
  never use a vendor's name.
- Docs in `docs/` are for people using Handler: no source code needed, the words of the UI
  and the CLI. They are kept in sync with what users see (`README.md` is the front page: update it
  when what Handler does or how it is installed changes).
- Python ≥ 3.12 (CI also runs 3.12), ruff line length 100.
- A bug found but not fixed now (unrelated to the task at hand, or left for any other reason) is
  written down, never left only in a conversation: what goes wrong, where, how to reproduce it.
- Commit messages explain the change in prose and cite the contract sections it changes.
