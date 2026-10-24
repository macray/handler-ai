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

**The model alone.** An agent with no program: each turn is one call to the model, on a
provider, in seconds. It has no files, no tools and no sandbox, so there is nothing it could do
on its own: it reads what it is sent (the conversation, its form, its knowledge's notes) and
answers. Good for a quick chat, a draft from a form, or a job that judges or extracts something.
Chosen in the agent's settings, *Who works*.

**Area.** What a project is for (Work, Personal, a client). Accounts and providers say which
areas they are made for, so a work account never runs on a personal project.

## Projects, agents, sessions

**Project.** A folder you work on, with your agents: its agents, what runs by itself on them,
and the apps given its folder (they live in Apps). The web UI's home
page lists them all; the menu lists those you pin, under their area's name (a new project is
pinned, the pin on its row takes it off the menu and puts it back). A dot beside a project in the
menu says what its sessions do: one waiting for you, working, or running.

**Agent.** Who works on a project, for one goal ("Dev", "Review"): its model, what it may do
(network, permissions, sandbox) and what it gets (addons, skills, knowledge folders). Its page
says all three, each leading to its settings. Another model is not another agent: pick it when
you start a session.

**Check.** A run of a job whose answer was right, kept to run again later: *Keep as a check* on
the run's page, then *Run all* in the job's Checks (or `handler agent checks ID --run`). It
passes when the same answer comes back: a verdict, a choice, a number; free text is shown, never
compared. Checks run only when you ask; after you change the agent, its page says they were not
run since.

**Improve until they pass.** On a job's Checks: say what to improve, and the *prompt writer* (an
agent on the model alone you set up once; change its instructions to change how it writes)
rewrites the job's instructions, attempt after attempt, each judged by the checks, until they
all pass or the attempts or minutes you allowed are spent. Nothing changes until you keep an
attempt; the first one is the instructions as they were, to go back.

**Agent outside projects.** An agent of no project: one you talk to about anything, with no
folder (in *Chat*), one you make for a folder that is no project's (your notes, a weekly report),
one Handler or an app uses, or one made by `handler run`, `handler acp` or `handler terminal` in
a folder that is no project's (the same command in the same folder gives the same agent, called
by its folder). Those not in Chat are under *Other folders*, in the menu after your pinned
projects, a page that reads as a project's.

**Chat.** Handler's own app, always there, first under *Apps* in the menu: talk about anything,
with no folder of yours (each conversation starts with an empty one). Its page lists who you
talk to (Claude for anything, a writing partner with its own instructions, a local model), each
an agent with a name, how it behaves and its model; *Someone new* adds one. When Ask finds no
app that does what you said, *Start a chat about it* opens Chat with your words in its box.

**Session.** One conversation with an agent. Handler holds it, so it keeps running when you
close the tab, and the web UI, a terminal and your phone all see the same one. Stopped after 30
minutes without anyone, it resumes when you come back.

**Chat, brief, job.** How you use an agent, chosen in its settings. A *chat*: you talk with it.
A *brief*: you fill in a form to start, then work on it together. A *job*: you fill in a form, it
works alone and gives back a result (a **run**). A brief's or a job's instructions can use what
the form was filled in with: *Insert from the form* under them puts a field there,
`{{audience}}`. Every agent shows how it is used: *Chat*, *Brief* or *Job*.

**Helpers.** Agents Handler's own features use: the App creator (writes and changes your apps),
Ask's router, the prompt writer (*Improve until they pass*), the skill creator and the skill
reviewer. Each is set up the first time its feature needs it (you choose its model), then is
yours to change like any agent: Settings → Helpers.

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

**Agents file.** Some or all of a project's agents as one file, to set them up in another
project, here or on another computer, or to give to someone: *Export agents* on a project's page.
It holds their instructions, form, skills and checks, never what is yours (the accounts or
providers they run on, the folder, which addon configuration or knowledge folder you gave them,
their conversations). *Add agents from a file* on another project opens one page: where, what
each agent needs from you (its model…), and what it will be allowed to do. The agents made are
yours: nothing follows the file afterwards. [`handler project
export-agents`](cli/project.md).

**Inbox.** What Handler tells you: your agents' results, your apps' notifications, failed runs. A
message tied to one of your apps opens it.

**App.** A small web app an agent writes for you and you deploy, used from your desktop or
your phone. It says what it needs in its own words (a folder, an agent, a key) and you give it
those when you install it. It may work on an agent's folder and run that agent when you ask it to
(a planner app and the agent it brings). Handler offers some (Planner), installed from the
Apps page. [Apps](apps.md).

**Source.** A git repository Handler reads to offer apps, agents and addons: Handler's own, and
any you add in Settings → Sources (you trust it: Handler does not check what is in it). What a
source offers is installed where you use it, through its usual install page. [Sources](sources.md).

**Ask.** Say what you want in your words; Handler picks which of your apps does it (one of what
you can ask them), runs it and answers. [Ask](ask.md).

**Remote device** and **person.** A phone paired with Handler through your gateway; it belongs to
you (sessions and apps) or to a family member (only the apps shared with them).
[Your phone](phone.md).

## Words that are easy to mix up

| Words | Difference |
|---|---|
| agent / account / provider / harness | The agent is who works, for one goal; it runs a harness (the program) on an account (your subscription) or a provider (an API, a local model). |
| addon / configuration / binding | An addon is the package; a configuration is one set of its settings and secrets, what you give an agent; in files and on the command line it is called a binding. |
| agent / agent outside projects / an app's agent | All are agents; one outside projects belongs to no project: someone you talk to in *Chat* (no folder), one made on the *Other folders* page, for Handler, or by the command line in a folder that is no project's. An app's agent is one of that app's parts: on its page only, started by it. |
| source / agents file / app file | A source offers things to install from a git repository, read again over time; an agents file or an app file is one export, given once. What comes from either is installed the same way. |
| agents file / project | A project is a folder and the agents working in it; an agents file is some of those agents written to set them up again in another project, without your folder, accounts or configurations. |
| session / run | A session is a conversation (a brief's starts from its form); a run is a job's session, started from a form, unattended, with a result. |
| run / automation run | A run is one of an agent with an interface; an automation's run is what the automation ran once (its script, an agent's run, an app's route). |
| session / harness terminal | A session is held by Handler and shown everywhere; `handler terminal` is the harness's own terminal UI in the agent's sandbox, for as long as the terminal is open. |

Where each of these is kept: [where things are kept](configuration.md).
