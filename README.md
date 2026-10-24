<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="branding/speech-case-dark.svg">
    <img src="branding/speech-case-light.svg" alt="Handler" width="96">
  </picture>
</p>

<h1 align="center">Handler</h1>

<p align="center"><strong>Handler</strong>: every agent needs one.</p>

<p align="center">Run coding agents in containers on your Linux machine.<br>Each agent sees only its project folder and reaches only the hosts you allow.</p>

Handler runs Claude Code, Codex, Mistral Vibe and pi in rootless Podman containers. A daemon
keeps the sessions running, and you use them from a web UI, the terminal, your editor (over
[ACP](https://agentclientprotocol.com), the Agent Client Protocol) or your phone. Small apps
run the same way, each with its own agent: install one, or have an agent write it for you.

<p align="center"><img src="docs/user/screenshots/demo.gif" alt="Starting a session in the web UI: the agent reaches a blocked host, which is then allowed in one click" width="720"></p>

> **Status: alpha.** Linux only.

| Harness | Status |
|---|---|
| Claude Code | well tested - used daily |
| Mistral Vibe | well tested - used daily |
| Codex | used once |
| [pi](https://www.npmjs.com/package/@earendil-works/pi-coding-agent) | used once |

## What it does

- **One container per session.** The project folder is mounted read-write at the same path. Your
  home, `~/.ssh`, `~/.aws` and your other projects are not mounted.
- **A network filter per agent.** Choose *none*, *filtered* (only the hosts you allow) or *open*.
  *Learn hosts* lets everything through for a while and lists what would have been blocked.
  Changes apply while the agent works.
- **API keys stay outside.** For a Claude Code token or a provider's API key, the agent only gets
  a stand-in. The network filter puts the real value into requests to that key's own hosts. Other
  secrets can be read by the agent (see [Limitations](#limitations)).
- **Sessions survive the browser tab.** `handlerd` keeps each session running. Attach to it from
  the web UI, the terminal (`handler attach`), Zed (`handler acp`) or a phone.
- **Any model access.** An API key, OpenRouter, a local llama.cpp or Ollama, or your own Claude,
  ChatGPT or Mistral subscription for your own interactive use.
- **Work and personal kept apart.** Tag projects, accounts and providers with an area (Work,
  Personal, a client). A work account then never runs on a personal project, and the other way
  round.
- **Apps that work for you, Ask and Chat.** Small apps, each in its own sandbox with its agent
  set up for it: Handler's own (Planner: your tasks and calendar in a markdown file), one from a source you
  trust, or one the App creator writes with you. Say what you want in Ask, typed or spoken
  ("tomorrow I call the bank at 10"), and Handler picks which app does it. Chat is for talking
  about anything, with no folder.
- **Sources and Discover.** A source is a git repository that offers apps, agents and addons:
  Handler's own, or one you add. Each item says what it may touch before you install it.
- **Optional extras:** addons (a Playwright browser, the Shopify CLI), skills, automations (on a
  schedule or when a session ends), agents files (a project's agents, to set up in another
  project), and phone access through an end-to-end encrypted gateway that you host.

## How it compares

Other tools sandbox coding agents too. Here is where Handler differs, as of October 2026. Check
each project's own docs for the details.

| | Handler | Claude Code's `/sandbox`, Codex's sandbox | Docker Sandboxes (`sbx`) | A devcontainer or VM you set up |
|---|---|---|---|---|
| What is isolated | the whole agent program | the commands it runs (the agent itself runs on your machine) | the whole agent program | the whole agent program |
| Isolation | rootless container (shares your kernel) | OS sandbox (bubblewrap, Landlock, Seatbelt) | microVM (its own kernel): stronger | as you set it up |
| Harnesses | Claude Code, Codex, Vibe, pi | one each | several | any |
| Network | per-agent allow-list, changed live, *Learn hosts* | allow-list | deny by default, allow-list | as you set it up |
| API keys | stand-in in the sandbox | in the agent's environment | injected by a proxy | in the environment |
| Sessions | kept by a daemon, from browser, terminal, editor, phone | the harness's own | the harness's own | the harness's own |
| Platforms | Linux | Linux, macOS (Windows partly) | Linux, macOS, Windows | any |

Pick Handler if you are on Linux, use more than one harness, and want one place to see and
control what every agent reaches. Pick a microVM if you need the stronger isolation.

## Install

**You need:** Linux with rootless Podman, `passt` and a systemd user session. Plan for about 3 GB
of disk: the images are built on your machine. The first `handler setup` downloads and builds them,
which can take from a few minutes to half an hour, depending on your connection.

```bash
uv tool install handler-ai   # or: pipx install handler-ai
handler setup   # starts handlerd as a user service, checks this machine, builds the images
handler ui      # opens the web UI
```

Without [uv](https://docs.astral.sh/uv/), `install.sh` installs it, then Handler with it, in
`~/.local/bin`. It changes nothing else; read it first if you prefer: it is attached to each
[release](https://github.com/macray/handler-ai/releases).

```bash
curl -fsSL https://github.com/macray/handler-ai/releases/latest/download/install.sh | sh
```

To update: `uv tool upgrade handler-ai`. `handler setup` says what your machine is missing and can be run
again at any time.
To build from a checkout instead: [development](docs/dev/development.md).

## First session

1. **Connect a model.** In the web UI, go to Settings → Model access → *Connect a model*:
   - **An API key**: Anthropic, OpenAI, OpenRouter, or a local llama.cpp or Ollama.
   - **Claude Pro or Max**: run `claude setup-token` yourself (Anthropic's own sign-in) and paste
     the token it prints. Handler never signs in for you. A subscription is used only for sessions
     you start and follow; automations need an API key.
   - **ChatGPT or Mistral**: Handler opens the harness's own login in a terminal window.
2. **Create a project.** Click *New project* and pick a folder. Choose how its first agent starts:
   *Locked down* (no network, asks before acting), *Guarded* (allowed hosts only; the default) or
   *Open* (any host).
3. **Ask.** Type a request and press Enter. The session keeps running after you close the tab.

Step by step: [getting started](docs/user/getting-started.md).

## From the terminal

The current folder decides which project's agent runs:

```bash
cd ~/code/my-app
handler run                                    # the project's default agent
handler run reviewer -p "review the last commit"   # the agent named reviewer
handler session list && handler attach s_…     # back to a session, running or stopped
```

To keep typing `claude` as you do today, but inside a container and on the account you choose,
put a shell function in `~/.bashrc`. It works for Claude Code and Mistral Vibe:

```bash
claude() { handler terminal claude-perso -- "$@"; }
```

More: [`handler terminal`](docs/user/cli/terminal.md), [every command](docs/user/cli/index.md).

## Screenshots

<table>
  <tr>
    <td width="50%"><a href="docs/user/screenshots/projects.png"><img src="docs/user/screenshots/projects.png" alt="Projects list"></a><br>Projects, by area (Work, Personal), as the menu lists them.</td>
    <td width="50%"><a href="docs/user/screenshots/project.png"><img src="docs/user/screenshots/project.png" alt="A project's page"></a><br>A project and its agents: what the chosen one runs on, is given and may do. Accounts and providers not for Work are not offered.</td>
  </tr>
  <tr>
    <td><a href="docs/user/screenshots/session.png"><img src="docs/user/screenshots/session.png" alt="A session"></a><br>A session: the agent's steps and answers, its mode and model.</td>
    <td><a href="docs/user/screenshots/session-network.png"><img src="docs/user/screenshots/session-network.png" alt="A session's sandbox and network panel"></a><br>Its sandbox and network panel: a blocked host, allowed in one click while the agent works.</td>
  </tr>
  <tr>
    <td><a href="docs/user/screenshots/agent-settings.png"><img src="docs/user/screenshots/agent-settings.png" alt="An agent's settings"></a><br>An agent's settings: its safety preset and the hosts it may reach.</td>
    <td><a href="docs/user/screenshots/model-access.png"><img src="docs/user/screenshots/model-access.png" alt="Model access"></a><br>Model access: accounts (subscriptions) and providers (API keys), each for an area.</td>
  </tr>
  <tr>
    <td><a href="docs/user/screenshots/apps.png"><img src="docs/user/screenshots/apps.png" alt="Apps"></a><br>Apps: Chat, always there; Planner to start with, or one the App creator writes with you.</td>
    <td><a href="docs/user/screenshots/discover.png"><img src="docs/user/screenshots/discover.png" alt="Discover"></a><br>Discover: what the sources offer, each item saying what it may touch.</td>
  </tr>
  <tr>
    <td colspan="2" align="center">
      <a href="docs/user/screenshots/phone-pairing.jpg"><img src="docs/user/screenshots/phone-pairing.jpg" alt="Pairing a phone" width="220"></a>
      <a href="docs/user/screenshots/phone-home.jpg"><img src="docs/user/screenshots/phone-home.jpg" alt="The phone's home page: the sessions you share" width="220"></a>
      <a href="docs/user/screenshots/phone-session.jpg"><img src="docs/user/screenshots/phone-session.jpg" alt="A session on a phone" width="220"></a>
      <br>On a phone, through the gateway you host: pairing it, the sessions you share, a session.
    </td>
  </tr>
</table>

## How it works

```
 web UI · handler CLI · editor (handler acp) · phone
              │  HTTP + WebSocket (ACP)
              ▼
          handlerd ── projects, agents, sessions, apps; checks every message to and from the agent
              │
              ▼
   ┌──────────────── rootless Podman ─────────────────┐
   │  agent container            network filter       │
   │  Claude Code / Codex / …  ──► allowed hosts only │
   │  project folder (rw), nothing else               │
   └──────────────────────────────────────────────────┘
```

| Word | Meaning |
|---|---|
| **Model access** | An **account** (a subscription) or a **provider** (an API key, a local server). |
| **Project** | A folder and its agents. |
| **Area** | What a project is for (Work, Personal, a client). Each account and provider says which areas it may be used for. |
| **Agent** | A role on a project: its model, instructions, network, permissions and tools. |
| **Session** | One conversation with an agent, in its own container, kept by the daemon. |
| **App** | A small web app and its agent, each in its own sandbox: you open it, ask it, or it runs by itself. |
| **Source** | A git repository that offers apps, agents and addons to install. |

More: [concepts](docs/user/concepts.md).

## Limitations

- Linux only.
- Containers share your kernel. That is weaker isolation than a virtual machine.
- Only Claude Code tokens and provider API keys are replaced by stand-ins. A ChatGPT or Mistral
  login file (Codex's `auth.json`, Vibe's `.env`) and addons' secrets can be read inside the
  container, and a manipulated agent could send them to an allowed host. Keep allow-lists short.
- An agent can change or delete anything in its project folder. Use git.
- Phone access needs a gateway that you host, behind HTTPS.
- The rest: [known limitations](docs/user/known-limitations.md), and
  [what the sandbox protects and what it does not](docs/user/security.md).

## Documentation

- [Documentation web site](https://macray.github.io/handler-ai/)
- [Changelog](CHANGELOG.md)

## Feedback

[Open an issue](https://github.com/macray/handler-ai/issues/new/choose) to tell us what you tried,
where it failed, or about a bug. Pull requests are not merged: please describe the problem
instead ([`CONTRIBUTING.md`](CONTRIBUTING.md)). For a security problem, see
[`SECURITY.md`](SECURITY.md).

## License

Apache 2.0, see [`LICENSE`](LICENSE).
