# What the sandbox protects

Handler assumes an agent may be wrong or manipulated (a web page, an issue or a file it reads can
tell it what to do), and limits what it can reach rather than trusting what it decides. This page
says what those limits are, and what they leave open.

## What an agent can reach

- **Its folder, read-write.** The project's folder is mounted at the same path as on your
  computer. It must be inside one of your work folders (Settings → Folders), and Handler's own
  folders are always refused.
- **What you give it, read-only:** its knowledge folders, its skills, its addons' programs.
- **Nothing else of your computer.** Not your home, not your SSH keys, not your other projects.
  Each agent runs in its own rootless Podman container, as your user (never root), with no
  extra privileges and a read-only system. When a session ends, the container is removed.
- **Not Handler itself.** No sandbox ever reads or writes Handler's files: its token, its secret
  store, your accounts, providers, agents, projects and automations. An agent cannot change its
  own settings, turn on an automation or deploy an app: only you can, from the web UI or the CLI.
- **Not your computer through the editor or the web UI.** Handler removes, from what a session
  says to the agent, the ability to read your files or run commands outside the sandbox, whatever
  the client.

## Network

Each agent has a network mode: **none**, **filtered** (only its allowed hosts, through a proxy of
its own; anything else is blocked, and the session's network panel shows it) or **open**. The
safety presets set it: *Locked down* (none), *Guarded* (filtered, the default), *Open*.

The hosts an agent needs for its model and its addons are allowed for you, shown "required by
…"; the others are yours to add, one by one or with *Learn hosts*.

## Secrets

A Claude Code account's token and a provider's API key never reach the agent: it gets a
stand-in, and its proxy puts the real value in its requests to the hosts that secret is for (your
model's API). A stand-in going anywhere else is blocked and shown in the network panel, and a
response that contains the value gets the stand-in back. Other secrets (a ChatGPT or Mistral
login, an addon's secrets) can be readable by the agent: see
[known limitations](known-limitations.md#stand-ins-claude-code-tokens-and-api-keys-only).
Settings → Secrets lists every secret and whether any agent can read it.

## Your phone and the gateway

Handler never opens a port. It polls the gateway you host, and everything between your phone and
your computer is end-to-end encrypted: the gateway can neither read it nor forge it. A family
member's phone reaches only the apps you share with that person, never a session. Details:
[your phone](phone.md#security).

## Apps

Each app has its own web address, apart from Handler's web UI and from the other apps, runs in its
own container with no network and none of your files unless its `app.toml` asks (shown before
you deploy), and gets its secrets from you, never from the agent that wrote it. Only you deploy.

## What it does not protect

- **The folder is the blast radius.** An agent can delete or rewrite anything in its folder. Keep
  folders small and use git.
- **Allowed hosts can receive what the agent reads.** A filtered network stops data going to an
  unknown host, not to an allowed one (an API that stores what it is sent, a code host). Keep
  allow-lists short; *Open* removes this limit altogether.
- **A secret can still be used.** The agent cannot send it elsewhere, but it can call the
  secret's hosts with it. Give agents accounts with only the rights they need (a development
  store, a token limited to themes).
- **Other secrets can be in the sandbox.** A ChatGPT or Mistral login and an addon's secrets
  can be readable by the agent, which could send them to an allowed host
  ([known limitations](known-limitations.md#stand-ins-claude-code-tokens-and-api-keys-only)).
- **Settings that weaken the sandbox** are confirmed when you save them and flagged on the agent:
  the sandbox *Runs containers*, or is *Privileged* (last resort: about as safe as no sandbox);
  an *Open* network; *Auto-approve* (it never asks); *Show windows on my screen and paste
  images* (the agent can open windows that look like other programs').
- **Shared caches** (a project choosing the global caches) let what one project's agent writes
  there reach another's.
- **The container is not a virtual machine.** Agents share your computer's kernel; a kernel flaw
  could let one out.
- **What an agent says is not checked.** Review what it changed (a session's Files) before you
  commit, deploy or run it.

Other limits: [known limitations](known-limitations.md). Found a security problem? See
[`SECURITY.md`](../../SECURITY.md).
