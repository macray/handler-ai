# Known limitations

## Linux only

Handler runs on Linux (rootless Podman). Other systems are not supported.

## Stand-ins: Claude Code tokens and API keys only

Only two kinds of secrets are known to stay out of the sandbox, the agent getting a stand-in its
proxy swaps for the real value ([what the sandbox protects](security.md#secrets)): a Claude Code
account's token and a provider's API key. The others can be read by the agent, which could send
them to an allowed host (keep allow-lists short):

- **A ChatGPT or Mistral account:** the harness's real login file (Codex's `auth.json`, Vibe's
  `.env`) is in the sandbox.
- **Addons' secrets** (a Shopify Theme Access password, say): those an addon gives as they are
  (its tool signs with them, or does not speak HTTP) are in the sandbox; the others get a
  stand-in, but the swap is not yet checked with each addon's tool, so count them as readable.
  Settings → Secrets says which secret an agent can read.

## Mistral Vibe's own terminal: no agent instructions

`handler terminal` gives Claude Code the agent's instructions (added to its system prompt), but
Vibe's terminal has no way to take them. An agent with instructions on Vibe is refused there
rather than started without them: use `handler run`, the web UI or an editor, which send them with
the first request.

## Claude Code: no Remote Control

Claude Code's Remote Control (`/remote-control`, controlling the session from claude.ai/code or the
Claude mobile app) cannot be turned on in a Handler sandbox, whatever the network setting (even
`--network open`). Claude Code (checked in 2.1.284) refuses it for two reasons, both coming from
the harness descriptor (`packages/harness-adapters/src/handler_harness/data/harnesses/claude-code/harness.toml`):

1. **Inference-only token.** An account logs in with `claude setup-token`, and its token reaches
   the sandbox as `CLAUDE_CODE_OAUTH_TOKEN` (`[login]`). Claude Code answers: "Remote Control
   requires a full-scope login token. Long-lived tokens (from `claude setup-token` or
   CLAUDE_CODE_OAUTH_TOKEN) are limited to inference-only for security reasons." A full-scope
   login (`/login`, `claude auth login`) leaves a refresh token in `~/.claude/.credentials.json`,
   which several sandboxes sharing one account could invalidate for each other.
2. **No feature flags.** `[env]` sets `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC = "1"` (privacy),
   which also turns off GrowthBook feature flags. Remote Control depends on the server-side flag
   `tengu_ccr_bridge`, so Claude Code answers: "Remote Control requires feature-flag evaluation,
   which is disabled because CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC is set."
   (`DISABLE_TELEMETRY` and `DO_NOT_TRACK` would block it the same way.)

Claude Code checks the token first, so removing only the second cause changes nothing. To see
the checks in a sandbox: `claude doctor` in `handler terminal` (its "Remote Control" section).

Lifting it would need both: a login that gives each agent its own full-scope credentials (e.g. in
its `config_dir` state slot instead of a shared account token), and the privacy setting made an
agent setting shown in the UI (on by default, with a warning that turning it off sends telemetry)
or reduced to `DISABLE_ERROR_REPORTING` + `DISABLE_AUTOUPDATER`.
