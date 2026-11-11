# What the sandbox protects

Handler assumes an agent may be wrong or manipulated (a web page, an issue or a file it reads can
tell it what to do), and limits what it can reach rather than trusting what it decides. This page
says what those limits are, and what they leave open.

## What an agent can reach

- **Its folder, read-write.** The project's folder is mounted at the same path as on your
  computer. It must be inside one of your work folders (Settings → Folders), and Handler's own
  folders are always refused.
- **What you give it, read-only:** its notes folders, its skills, its tools' programs.
- **Nothing else of your computer.** Not your home, not your SSH keys, not your other projects.
  Each agent runs in its own container, as your user (never root), with no extra privileges
  and a read-only system: rootless Podman on Linux by default, a virtual machine of its own with
  Apple's `container` on a Mac. When a session ends, the container is removed. With Docker as the
  runtime on Linux, Docker's engine runs as root: an agent escaping its container would be root
  on your computer, so Podman is safer.
- **Not Handler itself.** No sandbox ever reads or writes Handler's files: its token, its secret
  store, your accounts, providers, agents, projects and automations. An agent cannot change its
  own settings, turn on an automation or deploy an app: only you can, from the web UI or the CLI.
- **Not your computer through the editor or the web UI.** Handler removes, from what a session
  says to the agent, the ability to read your files or run commands outside the sandbox, whatever
  the client.

## Network

Each agent has a network mode: **No network**, **Only these sites** (its allowed hosts, through a
proxy of its own; anything else is blocked, and the session's network panel shows it) or **Any
site**. A new agent starts with only the sites it needs (its model's and its tools'). Its
settings show the mode as a meter, more bars being safer, Any site one amber bar. A blocked
request is answered "Blocked by Handler's network filter: ask the user to allow pypi.org:443"
(with the host it asked for), and a filtered agent is told from its start never to try to get
around the filter.

The hosts an agent needs for its model and its tools are allowed for you, shown "required by
…" in its settings (locked, with why); the others are yours to add, one by one (*Add a site*) or
by letting it learn them (*Learn the sites it needs*). A host you do not want the
agent to have, you can keep blocked: it stays refused, and the agent is told "Blocked by
Handler's network filter on the user's choice: do not ask for pypi.org:443, go on without it."
The network panel lists the hosts kept blocked, each with *Allow* and *Remove* (then it is
undecided again, and the agent may ask for it). Its recent connections say what became of each
request: ✓ reached (the host answered), ✗ "could not connect" with why ("connection refused":
nothing listens there), ⛔ blocked, or kept blocked.

When the filter blocks a host you have not decided on, the session shows it where you look: a
card in the conversation, "Handler's network filter blocked pypi.org:443 (3 times)", with *Allow
for this agent* and *Keep blocked*. One card per host and turn; your answer is saved to the agent
and applies to its running sandbox at once. Kept blocked, the card becomes one grey line and that
host never gets a card again. The session's network button shows how many blocked hosts wait for
your answer. On the phone the card shows, but you answer it on your computer.

While you have the session open on your computer, the agent's first request to such a host waits
up to 8 seconds for your answer instead of being refused at once: the card says "The agent is
waiting · 8 s" and counts down. Allowed in time, the request goes through; otherwise it is
refused as before. Nothing goes through unless you allow it, and a host you keep blocked never
waits. When you answer after the agent was refused, Handler tells the agent, as a message of its
own in the conversation: "Handler: pypi.org:443 is now allowed. Go on." (or that you keep it
blocked). If the agent has finished, it goes on at once; if it is still working, the card says
"The agent will be told when it finishes", and it is told then.

When nobody is there (the session is not open on your computer), the hosts blocked in a turn come
to your inbox once it ends, in one message: "pypi.org:443 was blocked by the network filter while
you were away", with *Allow* and *Keep blocked*. Your answer is saved and told to the agent the
same way. A plan's step or an automation's run says it in its own result instead: a run that
failed because of a blocked host says so ("pypi.org:443 was blocked by the network filter"),
whatever the agent guessed; one that completed says "Completed, with 2 hosts refused", how many
times each, what the agent did instead, and that the result may differ from what you would get
with these hosts. Both offer *Allow and run again* (from that step, for a plan) and *Keep
blocked*. A host you keep blocked is never listed.

## Secrets

A Claude Code account's token and a provider's API key never reach the agent: it gets a
stand-in, and its proxy puts the real value in its requests to the hosts that secret is for (your
model's API). A stand-in going anywhere else is blocked and shown in the network panel, and a
response that contains the value gets the stand-in back. Other secrets (a ChatGPT or Mistral
login, a tool's secrets) can be readable by the agent: see
[known limitations](known-limitations.md#stand-ins-claude-code-tokens-and-api-keys-only).
Settings → Expert → Secrets lists every secret: first those that need you (a value not set, one
an agent can read, with that agent and why), then those in use, with where each is sent.

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
  allow-lists short; *Any site* removes this limit altogether.
- **A secret can still be used.** The agent cannot send it elsewhere, but it can call the
  secret's hosts with it. Give agents accounts with only the rights they need (a development
  store, a token limited to themes).
- **Other secrets can be in the sandbox.** A ChatGPT or Mistral login and a tool's secrets
  can be readable by the agent, which could send them to an allowed host
  ([known limitations](known-limitations.md#stand-ins-claude-code-tokens-and-api-keys-only)).
- **Settings that weaken the sandbox** are confirmed when you save them and flagged on the agent:
  the sandbox *Runs containers*, or is *Privileged* (last resort: about as safe as no sandbox);
  *Any site*; learning the sites (every site let through); never asking before acting, for an
  agent that asked; *Windows on my screen* (the agent can open windows that look like other
  programs', and read what you copy). Each one on is an amber chip on the agent.
- **Shared caches** (a project choosing the global caches) let what one project's agent writes
  there reach another's.
- **The container is not a virtual machine.** On Linux (and WSL 2), agents share your computer's
  kernel; a kernel flaw could let one out. With Apple's `container`, each sandbox is a virtual
  machine of its own; with Docker Desktop or OrbStack, sandboxes share Docker's virtual machine.
- **What an agent says is not checked.** Review what it changed (a session's Files) before you
  commit, deploy or run it.

Other limits: [known limitations](known-limitations.md). Found a security problem? See
[`SECURITY.md`](../SECURITY.md).
