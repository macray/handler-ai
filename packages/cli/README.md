# cli — `handler`

**Implements:** a client of contracts C (ACP endpoint) and D (Control API).
**Depends on:** `handler_contracts` only (+ httpx, websockets). **Never touches podman**: everything goes
through `handlerd`, so the CLI, the web UI and editors get the same policy and the same agents.
**Used by:** you, editors (`handler acp`). Nothing on a timer: an automation runs at a time inside handlerd (contracts §I).

Verbs for working with an agent, nouns for what you manage (`handler -h`; for users:
[`docs/cli/index.md`](../../docs/cli/index.md), one page per command):

```
handler run [AGENT|ACCOUNT|PROVIDER] [-p REQUEST] [agent options]   # a session, in this terminal
handler attach [SESSION]                     # back to a session (a stopped one is resumed, F.4)
handler terminal AGENT|ACCOUNT|PROVIDER [-- ARGS]   # the harness's own terminal program (D.16)
handler acp AGENT|ACCOUNT|PROVIDER [FOLDER]  # ACP on stdio → handlerd → sandboxed agent (for Zed)
handler session list | show | stop | share   # sessions (F)
handler agent list | show | rm | network     # agents (D.1, D.8), live egress switch (A.4)
handler project list | show                  # projects (D.8)
handler account list | add | token | login | import | rm   # accounts and their login (D.9)
handler provider list | templates | add | rm # providers from a template (D.12)
handler secret list | set | rm               # the secret store (D.14): values written, never read back
handler tool list | add | rm                 # tools (G.5)
handler connection list · handler notes list
handler image list | rebuild TARGET          # images: build, check, switch; log streamed (D.4)
handler app … · handler automation … · handler inbox
handler setup [--no-build] [--yes]           # after installing: service, host check, images
handler daemon status | install [--dry-run] | uninstall | log [-f]
handler ui [--print]
```

| File | Role |
|---|---|
| `cli.py` | the top-level help and parser, `terminal`, `acp`, `connection list`, `notes list`, `ui`; the other nouns' modules are in `NOUNS` |
| `client.py` | discovery (`$HANDLER_URL`, token file) and HTTP calls with readable errors |
| `session_commands.py`, `terminal.py`, `session_bridge.py` | `handler run`, `attach`, `session …`; the terminal client; a session as a stdio ACP agent |
| `terminal_client.py` | `handler terminal`: this terminal relayed to a harness's own terminal program (D.16) |
| `bridge.py` | `handler acp` outside projects: stdio NDJSON ↔ the agent's ACP WebSocket |
| `agent_commands.py`, `project_commands.py` | `handler agent …`, `handler project …` |
| `account_commands.py`, `provider_commands.py`, `secret_commands.py` | `handler account …` (D.9), `handler provider …` (D.12), `handler secret …` (D.14) |
| `tool_commands.py` | `handler tool …` (G.5) |
| `image_commands.py` | `handler image …` (D.4) |
| `app_commands.py`, `app_window.py` | `handler app …` (H) |
| `automation_commands.py`, `inbox_commands.py` | `handler automation …` (I), `handler inbox` (I.9) |
| `setup.py`, `daemon_commands.py` | `handler setup`: the service, the host check (`GET /v1/runtime`), the first image build; `handler daemon …`: the systemd user unit for `handlerd` |

Tests: `tests/cli/` (against a real `handlerd`).
