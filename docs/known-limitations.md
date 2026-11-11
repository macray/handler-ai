# Known limitations

## Linux and WSL 2; macOS experimental

Handler runs on Linux (rootless Podman, or Docker), and on Windows inside WSL 2
([install on Windows](windows.md)). On a Mac it is experimental: with Apple's `container` (macOS
26, Apple silicon; the default), agents that run containers themselves, privileged agents and
windows on your screen are not available; with Docker Desktop or OrbStack, windows on your
screen, apps and automations whose scripts call models are not (a socket cannot cross Docker's
virtual machine).

With Apple's `container`:

- **Windows on your screen:** the one way to show Linux windows on a Mac (cocoa-way) also gives
  every window what you copy on your Mac, at any time: Handler does not offer it.
- **A folder in iCloud Drive, or in your Desktop, Documents or Downloads folder** (an agent's
  project or a folder it gets): the first time an agent starts with it, macOS asks whether
  `container-runtime-linux` (Apple container's) may access it, and the agent waits for your
  answer. If it was refused, the agent does not start and says so: allow
  `container-runtime-linux` in System Settings → Privacy & Security → Files & Folders (or Full
  Disk Access), or keep your projects elsewhere (e.g. `~/code`), which macOS does not ask about.
- **A file replaced on the Mac by renaming another over it** (how many editors save, and how git
  writes its own files) is missing for the agent for about two thirds of a second: a command it
  runs at that moment may fail with "No such file or directory", and works when run again.
  Apple's `container` does this; Docker Desktop and Linux do not.

With Docker as the runtime (new, less tested than Podman):

- **It needs Docker's buildx plugin**: Handler builds its images with BuildKit (`docker buildx`;
  on Arch, the `docker-buildx` package).
- **On Linux, a rootful Docker Engine**: an agent escaping its sandbox would be root on your
  computer (its check says so), and agents cannot be *Privileged*. A rootless Docker is refused:
  what agents wrote would not be yours.
- **Docker Desktop, OrbStack, Colima**: each sandbox stays in Docker's virtual machine; windows on
  your screen, apps and automations whose scripts call models do not run there (a socket cannot
  cross that virtual machine).

On WSL 2:

- Project folders on a Windows drive (`/mnt/c/…`) are slow: keep them in the Linux file system.
- *Windows on my screen* (WSLg) is not verified yet.
- A ChatGPT or Mistral login cannot open its terminal window: run `handler account login <name>`
  in the distribution's terminal (the web UI says so).
- Linux stops a while after its last terminal closes, and Handler with it, unless WSL is told not
  to ([keep Linux running](windows.md#2-keep-linux-running-when-its-window-closes)).
- Notifications do not reach Windows: the Inbox page and a paired phone have them.

## A file you give an app

An app given one file (not a folder) works on that very file: what it writes is in your file at
once, and what you change in it, the app sees. But some editors save by writing a new file and
putting it in the old one's place (TextEdit, JetBrains' "safe write"): the app then keeps
reading the version it started with, until it starts again (*Restart* on its page; it also stops by itself after 10 minutes unused). The app cannot replace the file, nor add files beside it. On a Mac
(Apple's `container` or Docker Desktop), the file must be on the same disk as your home folder.

## Stand-ins: Claude Code tokens and API keys only

Only two kinds of secrets are known to stay out of the sandbox, the agent getting a stand-in its
proxy swaps for the real value ([what the sandbox protects](security.md#secrets)): a Claude Code
account's token and a provider's API key. The others can be read by the agent, which could send
them to an allowed host (keep allow-lists short):

- **A ChatGPT or Mistral account:** the harness's real login file (Codex's `auth.json`, Vibe's
  `.env`) is in the sandbox.
- **Tools' secrets** (a Shopify Theme Access password, say): those a tool gives as they are
  (its tool signs with them, or does not speak HTTP) are in the sandbox; the others get a
  stand-in, but the swap is not yet checked with each tool's program, so count them as readable.
  Settings → Expert → Secrets says which secret an agent can read.

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
