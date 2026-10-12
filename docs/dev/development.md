# Development

Working on Handler itself: where to start, running a checkout, releases, checking a host, and what
still needs a real host. The rules for changing the code (boundaries, contracts, conventions) are in
[`CLAUDE.md`](../../CLAUDE.md); where each block lives: [`code-map.md`](code-map.md).

## Start here

- [`code-map.md`](code-map.md): where each block lives, how the boundaries are enforced, which
  test suite answers which question.
- [`architecture.md`](architecture.md): the design and why.
- [`model.md`](model.md): every concept and its rules (the domain model).
- [`design/`](design/index.md): the design of each feature, and what is not built yet.
- [`contracts.md`](contracts.md): the normative contracts (sections A–H, cited in code and
  commits).
- `packages/contracts` (`handler_contracts`): pydantic models of every contract; JSON Schemas are
  generated from them into `schemas/`.

## From a checkout

```bash
uv sync
scripts/build-web-ui.sh         # the web UI, into handler_control/web-ui/ (bun, or the toolbox image)
uv run handler setup            # handlerd as a user service running this checkout, images built
./scripts/ci.sh                 # schemas up to date, ruff, ty, web apps, gateway, tests
uv run python -m handler_contracts.schemas   # regenerate schemas/ after changing contracts
```

To use the checkout's `handler` everywhere: `ln -s "$PWD/.venv/bin/handler" ~/.local/bin/handler`; for a
pinned copy, `uv tool install ./packages/cli`.

## Releases

```bash
scripts/build-wheel.sh          # the wheel users install, into dist/
scripts/smoke-install.sh        # that wheel installed by install.sh in a bare container, checked
scripts/build-docs-site.py      # the documentation website, into docs-site/site
scripts/build-docs-site.py serve   # the same, previewed on http://localhost:8000
```

The public repository holds one commit per release, exported from the maintainer's working
repository: its message is the version's `CHANGELOG.md` entry, its tag `v<version>`, and gitleaks
checks the tree first (test values that look like secrets: `.gitleaksignore`). Pull requests there
are closed with a note pointing to the issues (`.github/workflows/pull-requests.yml`,
`CONTRIBUTING.md`).

A tag `v<version>` (handlerd's `__version__`) runs `.github/workflows/release.yml`: the checks,
the wheel and its smoke test, then the upload to PyPI (Trusted Publishing: no token, only that
workflow in the public repository, once the maintainer approves it), then a GitHub release holding
the wheel and `install.sh`. A version is never uploaded by hand: PyPI takes each one once. Users
then install with `uv tool install handler-ai` (or `pipx install handler-ai`) and `handler setup`,
and update with `uv tool upgrade handler-ai`; `install.sh` is for people without uv: it installs
uv, then the same. The tool's commands: `handler`, `handlerd`, `handler-harness`,
`handler-sandbox-podman`, and `handler-ai` (`handler` under the package's name, for `uvx
handler-ai`). `handler setup` builds the toolbox (about 2.5 GB, once) then
every harness image on it. The user's toolbox is `~/.config/handler-ai/toolbox/` (Settings → Images →
toolbox → Edit its Containerfile), their addons go in `~/.config/handler-ai/addons/`, their skills in
the Skills page: none of it needs this repository.

Harnesses and tools are not version-pinned: handlerd rebuilds their images weekly (Settings → Images
→ Automatic updates: weekly, daily or off, or Update now; also after a Handler upgrade), and each
new image is checked before agents switch to it: a broken release keeps the image they have.
`handler image rebuild claude-code` rebuilds one now.

The documentation website is `README.md` and `docs/` built with Zensical
(`zensical.toml`: its navigation, the public repository's URL). A push to `main` of the
public repository publishes it on GitHub Pages (`.github/workflows/docs.yml`). A link to a file
that is not a page points at that file on GitHub; a link to a path that does not exist stops the
build, as `scripts/ci.sh` checks.

## To validate on the host

What a feature does is in the [user docs](../user/getting-started.md) and its design note
(`design/`); what changed in a release, in `CHANGELOG.md`. What follows
is what the test suite cannot prove here (it runs with the fake sandbox and agent, as root in a
dev container, without real accounts) and still needs a run on a real host:

- **The machine**: `handler setup` (or `handler-sandbox-podman check`, contract A.8) says what it
  lacks.
- **Sandboxes**: `uv run pytest tests/sandbox`, as your user (keep-id, same-path mounts, proxy
  egress, confinement levels; `HANDLER_TEST_OFFLINE=1` skips the tests needing the internet).
- **Secrets through the network filter**: a real turn of each harness with its token or key
  swapped in by the sandbox's proxy.
- **Harness terminal** (`handler terminal`): `uv run pytest tests/sandbox -k tty`, then
  `systemctl --user restart handler-ai` under a running `handler terminal`.
- **Automations**: `uv run pytest tests/automations/test_podman.py` (toolbox built), then
  `handler automation new env-issues --from env-issues` on one of your providers and `handler
  automation try env-issues`; an hourly automation running an agent with an interface on a
  provider, its result in the Inbox page and on a phone. The e2e test
  (`test_an_agent_scheduled_from_its_settings`) needs the Playwright image.
- **Addons**: the Shopify addon against a real store (`tests/addons/test_shopify.py`, opt-in).
- **Browser** and **mini apps**: the lists at the end of [`design/browser.md`](design/browser.md)
  and [`design/miniapps.md`](design/miniapps.md) (real push services, iOS, Firefox, GNOME
  shortcuts, pi's MCP servers).

## Known gaps

- The phone does not show project contexts yet.
- Not built yet, by feature: the last section of each design note (addons, browser, mini apps,
  remote control) and the open part of [`design/services.md`](design/services.md).
