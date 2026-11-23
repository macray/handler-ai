# Handler and Claude Code's `/sandbox`

Claude Code has a [sandbox of its own](https://code.claude.com/docs/en/sandboxing), turned on with
`/sandbox`: it limits the shell commands Claude runs, with the operating system's own tools
(bubblewrap on Linux and WSL 2, Seatbelt on a Mac). Handler puts the whole program in a box:
Claude Code itself, its file tools, its MCP servers and its hooks, as well as the commands it
runs. Both filter the network through a proxy on your computer.

The facts on Claude Code come from Anthropic's documentation, read on 2026-11-23.

## In short

- **Pick `/sandbox`** when you work with Claude Code alone, want nothing to install beyond
  bubblewrap, and want the agent to keep using your own tools and settings: it is one setting
  away, and fewer prompts come with it.
- **Pick Handler** when the agent must not reach the rest of your computer at all: in Claude
  Code, reading and editing files, MCP servers and hooks run outside its sandbox, and its commands
  can read most of your computer unless you list what to hide. Handler also runs Codex, Mistral
  Vibe and pi the same way, and keeps each agent's setup in one place.

## Side by side

| | Claude Code `/sandbox` | Handler |
|---|---|---|
| **What is in the box** | Shell commands and what they start. Reading and editing files, web fetches, MCP servers, hooks and the status line run with your full access, under Claude Code's permission rules | Everything the agent runs: the program itself, its file tools, its MCP servers, its hooks and its commands |
| **The box** | The operating system's own: bubblewrap on Linux and WSL 2, Seatbelt on a Mac. Not on Windows itself | A container on Linux and WSL 2 (rootless Podman), a virtual machine of its own on a Mac (Apple's `container`) |
| **Turned on** | Off until you turn it on (`/sandbox`, or `sandbox.enabled`) | Always: there is no agent outside a box |
| **Getting out of it** | A command that fails may be retried outside the sandbox, after your approval (off with `allowUnsandboxedCommands: false`). Commands you list in `excludedCommands` run with your full access | No way out from inside. Loosening is an agent setting you change (the **nested** or **privileged** level, an open network), shown in amber |
| **What it can read** | Most of your computer, `~/.ssh` and `~/.aws` included, unless you deny them (`denyRead`, `blockReadsOutsideWorkingDirectories`) | Its project folder, its skills and its notes folders. Nothing else of your computer is in the box |
| **What it can write** | The working folder, a temporary folder and folders you add; Claude's settings, `.git/hooks` and shell startup files are protected | Its project folder, and notes folders you let it write. Never Handler's own files |
| **Network** | Allowed sites start empty; a new site asks you (allow once, or always), or is refused with `strictAllowlist`. Applies to commands only: a web fetch follows the permission rules | Per agent: no network, filtered (the default) or open, with its allowed and blocked sites. An unknown site is held 8 seconds while you watch, with **Allow** or **Keep blocked**; "Learn the sites it needs" lists what it used. Applies to everything in the box |
| **Your keys** | Commands inherit Claude Code's environment, secrets included, and can read your credential files, unless you deny or mask them one by one (masking needs the experimental `tlsTerminate`) | The box never holds your API keys, the Claude token or tool secrets tied to their sites: a stand-in, the real value added on the way out. Not yet for the Codex and Mistral Vibe logins |
| **Containers inside** | Docker does not work in the sandbox; the usual answer is to exclude `docker` commands, which then run with your full access | With the **nested** level, containers run inside the box |
| **Your tools** | The agent uses what is installed on your computer | The agent uses the toolbox image: you add packages to it (`handler toolbox add`) |
| **Agent programs** | Claude Code | Claude Code, Codex, Mistral Vibe, pi |
| **Platforms** | macOS, Linux, WSL 2 | Linux; macOS on Apple silicon and Windows through WSL 2 are experimental |
| **Cost, licence** | Part of Claude Code; its sandbox library (`@anthropic-ai/sandbox-runtime`) is open source | Open source (Apache-2.0); you bring an account or API key for the model |

## Setting up an agent

**In Claude Code**, the setup is Claude Code's own, and it is rich: `CLAUDE.md`, skills,
subagents, MCP servers, hooks and settings, per user and per project. The sandbox is one more
part of those settings (`sandbox.*` in `settings.json`). Your user settings apply to every
project: an MCP server or a hook you add for one project runs, outside the sandbox, in all of
them. And all of it is for Claude Code only.

**In Handler**, an agent is a thing you keep, inside a project, with its box around it. A project
can hold several agents, each with its own program, account or provider, model, instructions,
skills, tools (MCP servers among them) and notes folders, and its own network and level of
containment, in one settings page (or `handler agent` on the command line). Changing the program
from Claude Code to Codex is one field: the rest of the agent stays. Projects carry an area (Work,
Personal, a client), so a work account never runs on a personal project. A project's agents leave
as a file and come back on another computer (`handler project export-agents`, `import-agents`).

In short: `/sandbox` hardens the commands of the Claude Code you already use; Handler puts each
agent, whatever its program, in a box of its own with everything it needs.

## Asking less often

Claude Code's sandbox lets commands run without asking, because they stay inside it. Handler goes
further: the whole agent is in the box, so turning off **Asks before acting** costs less than on
your own computer. What the agent can damage is its project folder, which git keeps, and the sites
you allowed.
