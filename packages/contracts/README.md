# contracts — `handler_contracts`

**Implements:** the data definitions of every contract (A–H) — [`docs/dev/contracts.md`](../../docs/dev/contracts.md).
**Depends on:** pydantic only.
**Used by:** every other package. It is the only shared library.

| File | Contract |
|---|---|
| `common.py` | shared building blocks (paths, egress entries, secret references, mounts) |
| `account.py`, `provider.py` | E — Account, Provider |
| `agent_spec.py` | E — what an agent runs as: `AgentSpec` (harness + account or provider, resolved) |
| `harness.py` | B — HarnessDescriptor, HarnessLaunch |
| `sandbox.py` | A — SandboxSpec, exit codes |
| `acp_endpoint.py` | C — wire constants (subprotocol, policy error codes) |
| `control.py` | D — Control API resources, with sessions (F), remote control (D.7) and mini apps (H) |
| `terminal.py` | D.16 — the terminal WebSocket's messages |
| `remote.py` | D.7 — what a paired device and Handler say inside the envelopes (control channel, app channels) |
| `addon.py` | G — AddonManifest, Binding |
| `miniapp.py` | H — MiniAppManifest |
| `schemas.py` | generates `schemas/*.schema.json` (language-neutral form, used by the TypeScript UI) |

After changing a model: `uv run python -m handler_contracts.schemas` (CI fails on drift).
