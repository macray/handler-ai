# harness-adapters — `handler_harness`, `handler-harness`

**Implements:** contract B (harness adapter): loading descriptors, the pure `render`, image
names, build recipes and version files (B.6). Never runs anything: images are built and queried
by the runtime (the sandbox's `image` verbs, A.7, run by handlerd).
**Depends on:** `handler_contracts`.
**Used by:** the control plane (imports the pure `render`), humans (`handler-harness` CLI).
**Data it reads:** its own, shipped read-only ([`data/`](src/handler_harness/data): `harnesses/<name>/`,
the built-in `tools/<name>/`, the default `toolbox/`, `handler-sandbox-env`), and the user's
(`~/.config/handler-ai/toolbox/`, seeded from the default by handlerd, and `~/.config/handler-ai/tools/`).

```
handler-harness list                            # harnesses and their image (built by handlerd: `handler image rebuild toolbox`)
handler-harness render NAME SCOPE --account F|--provider F  # dry run: what an agent becomes for a harness
```

| File | Role |
|---|---|
| `catalog.py` | where harnesses live, loading and validating `harness.toml` |
| `render.py` | AgentSpec → HarnessLaunch (pure, B1–B5) — **the harness-specific translation**; `harness_hosts`: the hosts it needs, each with what requires it (the launch's egress, shown to clients as an agent's required hosts) |
| `toolbox.py` | the toolbox's parts (B.7): Handler's base per distro (`data/toolbox/distros/`), the system packages (built-in `data/toolbox/system-packages/`, the user's `~/.config/handler-ai/system-packages/`), their layer order, the generated Containerfile and its build context (pure: files in, files out) |
| `images.py` | image names and tags (`:latest`), the `Recipe` of each build (context, `TOOLBOX_IMAGE`, cache and pull choices; D.4, G.4), where an image records its version (B.6, G.1) |
| `cli.py` | command line |

Unit tests: `tests/test_render.py` (golden fixture `tests/fixtures/claude-perso.launch.json`),
`tests/test_toolbox.py` (golden fixture `tests/fixtures/toolbox.Containerfile`).
Conformance: `tests/harness/` (real images, real ACP sessions).
