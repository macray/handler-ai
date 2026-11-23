# Handler and bubblewrap

[bubblewrap](https://github.com/containers/bubblewrap) (`bwrap`) is the small Linux tool Flatpak
uses to start a program in a sandbox, without root. Some people wrap their coding agent in it
with a script of their own. In its own words, it is "a tool for constructing sandbox
environments", "not a complete, ready-made sandbox with a specific security policy": what it
protects depends entirely on the arguments you give it. Handler is the ready-made box: it decides
what goes in, filters the network and keeps your keys outside.

The facts on bubblewrap come from its project page, read on 2026-11-23.

## In short

- **Pick bubblewrap** when you know exactly what to mount and are happy writing and keeping the
  script: it starts at once, needs no service, no image and nothing but Linux, and the agent keeps
  using the tools of your computer.
- **Pick Handler** when you want the box without writing it: the right folders in, the network
  filtered site by site, your keys out of reach, and the same for Claude Code, Codex, Mistral Vibe
  and pi.

## Side by side

| | bubblewrap | Handler |
|---|---|---|
| **What it is** | A command to build a sandbox, one argument at a time. No policy of its own | A sandbox already built, per agent, with its settings in one page |
| **The box** | Linux namespaces, without root. Shares your computer's kernel | The same kind on Linux and WSL 2 (rootless Podman), at the strict level with every privilege dropped, a read-only system and Podman's syscall filter. On a Mac, a virtual machine of its own |
| **What it can read and write** | Only what you mount, read-only or not. Agents usually need much of the system (`/usr`, their own settings, your tools), so the script tends to grow | Its project folder, its skills and its notes folders, at the same paths. Nothing else of your computer |
| **Network** | All or nothing: the computer's network, or none at all. An agent needs its model's site, so in practice: all | Per agent: no network, filtered (the default) or open, with allowed and blocked sites, an unknown site held while you watch (**Allow** or **Keep blocked**), and "Learn the sites it needs" |
| **Your keys** | Whatever you pass in (an environment variable, a mounted file) is readable by the agent and anything it runs | A stand-in in the box; the real API key, Claude token or tool secret is added on the way out, to its own sites only. Not yet for the Codex and Mistral Vibe logins |
| **Mistakes to avoid** | Yours to know: `--new-session` against a known escape through the terminal, never mounting a socket (D-Bus, Docker) that can run commands outside, a syscall filter if you want one | Decided once, in Handler, and tested. Settings that loosen the box are shown in amber |
| **Containers inside** | Hard: a program's own sandbox (a browser's, Docker) may not start | With the **nested** level |
| **Your tools** | The agent uses your computer's, mounted in | The toolbox image; you add packages with `handler toolbox add` |
| **Leaving and coming back** | The agent lives as long as its terminal | Handler's background service holds the session: come back from `handler attach`, the web UI or your editor |
| **Start-up** | Instant: nothing to install but `bwrap`, no image | A container runtime and images built once (`handler setup`) |
| **Platforms, licence** | Linux only; LGPL-2.1 | Linux; macOS on Apple silicon and Windows through WSL 2 are experimental; Apache-2.0 |

## Setting up an agent

**With bubblewrap**, the setup is your script: one per agent, or one with arguments. To change the
program, the account or what it may reach, you edit the script. The agent's own setup (its
instructions, skills, MCP servers) is the program's, from your home folder, if you mount it.

**In Handler**, an agent is a thing you keep, inside a project, with its box around it: its
program, account or provider, model, instructions, skills, tools (MCP servers among them), notes
folders, network and level of containment, in one settings page (or `handler agent` on the command
line). Changing the program or the account is one field. A project's agents leave as a file and
come back on another computer (`handler project export-agents`, `import-agents`).

In short: bubblewrap gives you the walls and leaves the plan to you; Handler is the plan, built
and kept for each agent.
