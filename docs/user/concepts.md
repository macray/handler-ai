# Concepts

The words you meet in Handler, a few lines each, with the page to read next. Contributors: every
rule behind them is in the [domain model](../dev/model.md).

```
 model access ─────────────┐  an account (your subscription) or a provider (an API, a local model)
                           ▼
 project ──► agents ──► sessions ◄── you: the web UI, a terminal, an editor, your phone
 a folder    one goal     one conversation each, in a sandbox
             each, with
             its settings
```

## Model access

**Account.** A subscription an agent program signs in with: Claude Pro or Max, a ChatGPT plan, a
Mistral account. For your own use only. Settings → Model access.

**Provider.** Where model calls go when it is not a subscription: an API with its key (Anthropic,
OpenAI, OpenRouter) or a model on your machine or network (llama.cpp, Ollama).

**Harness.** The agent program that runs: Claude Code, Codex, Mistral Vibe or pi. An account
brings its own; on a provider you choose one.

**Context.** What a project is for (Work, Personal, a client). Accounts and providers say which
contexts they are made for, so a work account never runs on a personal project.

## Projects, agents, sessions

**Project.** A code folder and the agents you work on it with. The web UI's home page lists
them.

**Agent.** Who works on a project, for one goal ("Dev", "Review"): its models, what it may do
(network, permissions, sandbox) and what it gets (addons, skills, knowledge folders). Another
model is not another agent: pick it when you start a session.

**Agent outside projects.** One made by `handler run`, `handler acp` or `handler terminal` in a
folder that is no project's: the same command in the same folder gives the same agent.

**Session.** One conversation with an agent. Handler holds it, so it keeps running when you
close the tab, and the web UI, a terminal and your phone all see the same one. Stopped after 30
minutes without anyone, it resumes when you come back.

**Agent with an interface, and its runs.** An agent you start from a form instead of a chat: it
works unattended and gives back a result. Handler ships two: the skill reviewer and the skill
creator.

## Safety

**Sandbox.** Where an agent runs: a container that sees its folder and what you give it,
nothing else of your computer. What it protects and what it does not: [security](security.md).

**Safety preset.** *Locked down* (no network, asks first), *Guarded* (only its allowed hosts,
never asks: the default) or *Open*. A starting point copied into the agent, then yours to change.

**Network.** No network, *Filtered* (only the allowed hosts; the session's network panel shows
what was blocked and allows it in one click) or *Open*.

**Permissions.** Whether the agent asks before acting: *Ask first*, *Auto edits*, *Auto-approve*.

**Work folders.** The folders agents may work in at all (Settings → Folders, `~/code` by default).

**Secret.** A token or a key. Agents never hold it: Handler adds it to their requests, towards
the hosts it is for only.

## What an agent can get

**Addon** and its **configurations.** An addon teaches agents one kind of system (a Shopify
store, a browser): programs, skills, the hosts they need. A configuration is one set of its
settings and secrets (one store, one token), and what you give an agent. [Addons](addons.md),
[a browser](browser.md).

**Skill.** Instructions an agent reads when they apply: the Skills page, given by a project to
all its agents or picked by one.

**Knowledge folder.** Your notes, given read-only to the agents that need them.
[Knowledge folders](knowledge.md).

**Toolbox.** The tools every agent works with (compilers, runtimes, `git`…). Add one in
Settings → Images → toolbox.

## Around your agents

**Automation.** *When this happens, run that*: when a session stops or at a time, your script,
one of your agents or one of your apps. [Automations](automations.md).

**Inbox.** What Handler tells you: your agents' results, your apps' notifications, failed runs.

**Mini app.** A small web app an agent writes for you and you deploy, used from your desktop or
your phone. [Mini apps](mini-apps.md).

**Remote device** and **person.** A phone paired with Handler through your gateway; it belongs to
you (sessions and apps) or to a family member (only the apps shared with them).
[Your phone](phone.md).

## Words that are easy to mix up

| Words | Difference |
|---|---|
| agent / account / provider / harness | The agent is who works, for one goal; it runs a harness (the program) on an account (your subscription) or a provider (an API, a local model). |
| addon / configuration / binding | An addon is the package; a configuration is one set of its settings and secrets, what you give an agent; in files and on the command line it is called a binding. |
| agent / agent outside projects | Both are an agent; one outside projects is made by the command line in a folder that is no project's. |
| session / run | A session is a conversation; a run is a session of an agent with an interface, started from a form, unattended, with a result. |
| run / automation run | A run is one of an agent with an interface; an automation's run is what the automation ran once (its script, an agent's run, an app's route). |
| session / harness terminal | A session is held by Handler and shown everywhere; `handler terminal` is the harness's own terminal UI in the agent's sandbox, for as long as the terminal is open. |

Where each of these is kept: [where things are kept](configuration.md).
