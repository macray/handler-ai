# Handler and Docker Sandboxes (`sbx`)

[Docker Sandboxes](https://docs.docker.com/ai/sandboxes/) (`sbx`) runs a coding agent in a
virtual machine of its own. Handler runs it in a container on Linux, and in a virtual machine of
its own on a Mac. Both keep your API keys out of the box and filter what the agent reaches on the
network; they differ in how strong the box is on Linux, in how you set up an agent, and in where
you work with it.

The facts on `sbx` come from Docker's documentation, read on 2026-11-23.

## In short

- **Pick `sbx`** for the strongest box on Linux and Windows (a virtual machine for every agent),
  for git clones and worktrees per task, and for the agents Handler does not run (Copilot, Cursor,
  Kiro, OpenCode and others).
- **Pick Handler** to keep several agents per project, each with its own program, account,
  model, instructions, skills and tools, set up in a form and changed in one field; to keep
  sessions running while you come and go from the terminal, the web UI or your editor; and for a
  tool that is open source, with no account to create.

## Side by side

| | Docker Sandboxes (`sbx`) | Handler |
|---|---|---|
| **The box** | A virtual machine for every agent, with its own kernel and its own Docker engine | A container for every session, as your user (never root), with a read-only system: rootless Podman on Linux and WSL 2. On a Mac, a virtual machine of its own (Apple's `container`) |
| **Strength on Linux** | Stronger: a virtual machine. Needs KVM, and your user in the `kvm` group | A container shares your computer's kernel: weaker than a virtual machine, but no KVM needed. Docker is possible too, as root (an escape would be root on your computer), so Podman is safer |
| **What the agent sees** | Its folder, at the same path as on your computer, plus extra folders you name (read-only with `:ro`). Or a clone of the repository, a git worktree, or no folder at all | Its project folder, at the same path; its skills and notes folders, read-only unless you let it write notes. Nothing else of your computer is in the box. No clones or worktrees |
| **What stays between runs** | The whole sandbox, with what the agent installed, until you remove it (`sbx rm`) | The box is removed when the session ends; package caches (`~/.npm`, `~/.cargo`…) are kept, per project or shared. Tools you want every time go in the toolbox image |
| **Containers inside** | Each sandbox has its own Docker engine | With the **nested** level (an agent setting); **strict**, the default, cannot |
| **Network** | One policy for every sandbox, chosen on first run (Open, Balanced, Locked Down), plus rules per sandbox. A blocked request waits for you: `sbx policy approval`. A log of what was reached and blocked | Per agent: no network, filtered (the default) or open, with its own allowed and blocked sites. An unknown site is held 8 seconds while you watch the session, with **Allow** or **Keep blocked**. "Learn the sites it needs" lets the agent through and lists what it used |
| **Your keys** | Stored with `sbx secret set`; the box sees a stand-in, and the proxy puts the real key in on the way out | The same for API keys, the Claude token and tool secrets tied to their sites. Not yet for the Codex and Mistral Vibe logins, which the agent can read |
| **Leaving and coming back** | `sbx run -d` keeps a sandbox running; `sbx run --name` comes back to it | Handler's background service holds the session: close the terminal or the tab, then come back from `handler attach`, the web UI or your editor. A session nobody uses stops after 30 minutes, and `handler attach` resumes it |
| **Agent programs** | Claude Code, Codex, Copilot, Cursor, Devin, Docker Agent, Droid, Kiro, OpenCode | Claude Code, Codex, Mistral Vibe, pi |
| **Signing in to a model** | An API key as a secret, or the program's own login inside the box (`/login` in Claude Code) | An account (Claude, ChatGPT or Mistral subscription) or a provider (API keys, local models), chosen per agent |
| **Platforms** | macOS 14+ on Apple silicon, Windows 11, Ubuntu 24.04+. Also cloud sandboxes (paid) | Linux; macOS on Apple silicon and Windows through WSL 2 are experimental |
| **Cost, licence, account** | Free for local use; a Docker account is required; usage data sent unless you turn it off. Organisation policies are paid | Open source (Apache-2.0); no account |

## Setting up an agent

This is where the two differ most.

**In Handler**, an agent is a thing you keep, inside a project. A project can hold several: a
reviewer on Claude with your Work account, a cheap helper on a local model, a writer with your
notes. Each agent has, in one settings page (or `handler agent` on the command line):

- the program, the account or provider, and the model;
- its instructions, its skills, its tools (with their connections, MCP servers among them) and
  its notes folders;
- its network, its sites, how much it may do without asking, and how contained it is. Every
  setting that loosens the box is shown in amber, and asks you to confirm.

Changing the program or the account is one field: the rest of the agent stays. Projects carry an
area (Work, Personal, a client), and accounts say which areas they are for: a work account never
runs on a personal project. A project's agents leave as a file (`handler project export-agents`) and
come back on another computer (`import-agents`); a source can offer ready-made agents; a skill is
checked before an agent gets it (programs, hidden characters, the sites it names).

**In `sbx`**, you set up a sandbox, not an agent you keep. You pick the agent program when you
create it, then add what it needs:

- **Kits:** a folder with a `spec.yaml` that sets the image, setup commands, instructions,
  network rules, which secrets it may use, and files to put in the box. Mixins add to an
  existing kit. Kits can be signed and shared through a registry: strong for a team that wants
  the same box everywhere.
- **Skills:** a store on your computer shared with new sandboxes (`sbx skills add`, or imported
  from an agent program you already use). Your own `~/.claude` settings are not brought in.
- **MCP servers:** a catalog through Docker's gateway, enabled per sandbox (`sbx mcp enable`), or
  found by the agent itself during the session.
- **Templates:** a sandbox saved as an image, to start the next from it.

All of it is written in files and commands; the `sbx` dashboard shows the sandboxes, their
resources and network rules. Changing the kits means making the sandbox again.

In short: `sbx` makes a box you can describe, sign and share exactly; Handler makes an agent you
keep, and changes in a form.
