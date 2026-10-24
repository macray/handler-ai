# CLAUDE.md

This file guides coding agents (Claude Code; Codex and others read it as `AGENTS.md`) working in
this repository.

## What this is

Handler runs AI agent harnesses (Claude Code, Codex, Mistral Vibe, pi) in
rootless Podman sandboxes and drives them over ACP (Agent Client Protocol) from a web UI, the `handler`
CLI, editors (`handler acp`), a scheduler, or a paired phone. Single user, local machine.

Read first: `docs/dev/code-map.md` (where each block lives, "where to look for…" table, which test
suite answers which question). Normative specs: `docs/dev/contracts.md` (sections A–H are referenced
throughout code and commits, e.g. "D.8", "§E"). Every concept and its rules: `docs/dev/model.md`
(as users see them, shorter: `docs/user/concepts.md`).

## Commands

The checkout may be shared between the host and sandboxes/containers: `.venv` points at the host's
Python, and a plain `uv run` elsewhere recreates it and breaks the host's venv. Outside the host,
set `UV_PROJECT_ENVIRONMENT` to a separate location (also `HANDLER_VENV_PY312`, `HANDLER_GATEWAY_VENV` for
`ci.sh`).

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
handler image rebuild toolbox                 # (handlerd running) toolbox image then every harness image
scripts/build-wheel.sh                        # the `handler-ai` wheel users install (packaging/), web UI inside
scripts/smoke-install.sh                      # that wheel via scripts/install.sh in a bare container
scripts/build-docs-site.py [serve]            # documentation website (Zensical), stops on a broken link
```

Many conformance/e2e tests need built images or real credentials and skip otherwise; credential
tests are opt-in via `HANDLER_TEST_CLAUDE_CONFIG_DIR` (+ `_JSON`), `HANDLER_TEST_MISTRAL_API_KEY`,
`HANDLER_TEST_OPENAI_API_KEY`, `HANDLER_TEST_SHOPIFY_STORE` + `HANDLER_TEST_SHOPIFY_THEME_TOKEN`. The tests
read a made-up source (`tests/fixtures/source/`) as the official one; those of Handler's real registry items
(Planner, shopify) are opt-in via `HANDLER_TEST_REGISTRY` (a checkout of the registry). When running
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

Changing a contract model means also: regenerating `schemas/`, then the TypeScript types with
`bun run gen:types` (repo root: `packages/web-ui/src/lib/contracts.gen.ts` from `handler.control.v1.*`,
`packages/remote-client/src/lib/remote.gen.ts` from `handler.remote.v1.*`; commit them, CI fails on
diff), and updating `docs/dev/contracts.md` (and `docs/dev/design/remote.md` for the device channel).

## Architecture

Blocks with hard boundaries that exchange **data, not imports**. Import rules are enforced by
`tests/architecture/test_boundaries.py` (a new `packages/*/src/handler_*` package must be added there,
and every package needs a README; inside the control plane, a module imports only from its layer
or lower ones, and a new module gets a layer in `CONTROL_LAYERS`, see its README):

- `packages/contracts` (`handler_contracts`): pydantic models of every contract — the only shared
  library. JSON Schemas in `schemas/` are generated from it; TypeScript types are generated from those.
- `packages/sandbox-podman` (contract A): reached **only as an executable** (`handler-sandbox-podman`,
  `SandboxSpec` on fd 3, stdio = the agent's ACP stream; `image …` verbs for images, A.7), never
  imported; the only block that calls podman. Container isolation,
  confinement levels and the egress allow-list proxy live here.
- `packages/harness-adapters` (`handler_harness`, contract B): pure `render(descriptor, AgentSpec…) → HarnessLaunch`,
  plus `handler-harness` CLI. Harness-specific knowledge lives only here and in data dirs
  `handler_harness/data/`: `harnesses/<name>/` (`harness.toml` + Containerfile), the built-in
  `addons/<name>/` (`app-builder`), the `catalog/` of installable addons (G.5: shopify, playwright),
  the default `toolbox/` (copied to the user's `~/.config/handler-ai/toolbox/` on
  handlerd's first start: the shared base image; the user's addons are in `~/.config/handler-ai/addons/`).
  Per-harness provider config writers: `handler_harness/providers.py`.
- `packages/control-plane` (`handler_control`, daemon `handlerd`): the only block composing others. Control
  API (HTTP, contract D, `api/`: one module per contract section, routes only translate HTTP; the
  rules an agent or a project must pass before it is saved: `save_rules.py`), ACP WebSocket endpoint
  with the P1–P8 policy pipeline (`policy.py`, `relay.py`),
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
phones use. Configuration is TOML in `~/.config/handler-ai/`: `accounts/`, `providers/`, `bindings/`
(addon × credentials), `skills/`, `folders.toml`; examples in `examples/`. Agents and projects
are daemon state (`~/.local/state/handler-ai/agents.json`, `projects.json`).

## Design principles

- Hard rule: no sandbox ever reaches Handler's own files (the token, `secrets.json`, accounts,
  providers, bindings, automations, agents and projects state), read or write, whatever the
  feature: only a subfolder made for it (`docs/dev/contracts.md` §2, invariant 6). A feature that
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

- Frontend tasks (web UI, phone client, acp-view, CLI output and help, `docs/user/`): read
  `docs/dev/ui-ux.md` first and follow it, including what it says about the vendors' terms.
- Docs live in `docs/`, split by reader: `docs/user/` for people using Handler (no source code
  needed; the words of the UI and the CLI, `docs/dev/ui-ux.md`), `docs/dev/` for contributors and
  agents (`docs/dev/design/`: why each feature is built the way it is, and what is not built).
- Docs are kept in sync with code: `docs/dev/code-map.md` for new blocks/locations,
  `docs/dev/contracts.md` for behavior/format changes, `docs/dev/development.md` for what still
  needs a real host, `docs/user/` for what users see (`README.md` is the front page: update it
  when what Handler does or how it is installed changes).
- Python ≥ 3.12 (CI also runs 3.12), ruff line length 100.
- A bug found but not fixed now (unrelated to the task at hand, or left for any other reason) is
  written down, never left only in a conversation: what goes wrong, where, how to reproduce it.
- Commit messages explain the change in prose and cite contract sections / phases.
