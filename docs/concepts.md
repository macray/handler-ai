# Concepts

The words you meet in Handler, a few lines each, with the page to read next.

```
 model access ─────────────┐  an account (your subscription) or a provider (an API, a local model)
                           ▼
 project ──► agents ──► sessions ◄── you: the web UI, a terminal, an editor, your phone
 a folder    one goal     one conversation each, in a sandbox
             each, with
             its settings
```

## Model access

**Account.** A subscription an agent program signs in with: Claude Pro or Max, a ChatGPT subscription, a
Mistral account. For your own use only. Settings → Model access.

**Provider.** Where model calls go when it is not a subscription: an API with its key (Anthropic,
OpenAI, OpenRouter) or a model on your machine or network (llama.cpp, Ollama).

**Harness.** The agent program that runs: Claude Code, Codex, Mistral Vibe or pi. An account
brings its own; on a provider you choose one.

**The model alone.** An agent with no program: each turn is one call to the model, on a
provider, in seconds. It has no files, no tools and no sandbox, so there is nothing it could do
on its own: it reads what it is sent (the conversation, its form, its notes) and
answers. Good for a quick chat, a draft from a form, or a job that judges or extracts something.
Chosen in the agent's settings, *Who works*.

**Area.** What a project is for (Work, Personal, a client). Accounts and providers say which
areas they are made for, so a work account never runs on a personal project.

## Projects, agents, sessions

**Project.** A folder you work on, with your agents: its agents, what runs by itself on them,
and the apps given its folder (they live in Apps). *New project* makes the project alone; its
page then offers an agent to work with you, or sets one up (and a project whose last agent you
removed stays, with none). The web UI's Projects page lists them all, by name, each with when it was
last used; one waiting for you shows *Open session*, which goes straight to the waiting session
(Handler opens there the first time, then where you left off). The menu's **Pinned** holds the
projects and apps you pin, mixed, in your order: the pin on a row or on a page puts one there,
drag to reorder, × to unpin. Only your first project is pinned by itself. A dot beside a pinned
project says what its sessions do: one waiting for you, working, or running; its colour is its
area's.

**Agent.** Who works on a project, for one goal ("Assistant", "Review"): its model, what it may do
(network, permissions, sandbox) and what it gets (tools, skills, notes folders). Its page
says all three, each leading to its settings. Another model is not another agent: pick it when
you start a session.

**Check.** A run of a job whose answer was right, kept to run again later: *Keep as a check* on
the run's page, then *Run all* in the job's Checks (or `handler agent checks ID --run`). It
passes when the same answer comes back: a verdict, a choice, a number; free text is shown, never
compared. Checks run only when you ask; after you change the agent, its page says they were not
run since.

**Improve until they pass.** On a job's Checks: say what to improve, and the *prompt writer* (an
agent on the model alone, turned on by its card the first time; change its instructions on its
page in Settings → Helpers to change how it writes)
rewrites the job's instructions, attempt after attempt, each judged by the checks, until they
all pass or the attempts or minutes you allowed are spent. Nothing changes until you keep an
attempt; the first one is the instructions as they were, to go back.

**Agent outside projects.** An agent of no project: one you talk to about anything, with no
folder (in *Chat*), one you make for a folder that is no project's (your notes, a weekly report),
one Handler or an app uses, or one made by `handler run`, `handler acp` or `handler terminal` in
a folder that is no project's (the same command in the same folder gives the same agent, called
by its folder). Those not in Chat are under *Agents outside projects*, at the foot of the Projects page, a
page that reads as a project's.

**Chat.** Handler's own app, always there, in the menu once a model is connected (until then
`http://127.0.0.1:7430/#/chat` opens it): talk about anything,
with no folder of yours (each conversation starts with an empty one). Its **Talk** tab lists who
you talk to (the Assistant for anything, a writing partner with its own instructions, a local
model), each an agent with a name, how it behaves and its model; *Someone new* adds one. Its
**Ask** tab is [Ask](ask.md), apart from the chat: what you say goes to one of your apps. When
Ask finds no app that does what you said, *Start a chat about it* opens Talk with your words in
its box.

**Session.** One conversation with an agent. Handler holds it, so it keeps running when you
close the tab, and the web UI, a terminal and your phone all see the same one. Stopped after 30
minutes without anyone, it resumes when you come back.

**Talk, brief, job.** How you use an agent, chosen in its settings. *Talk*: you talk with it.
A *brief*: you fill in a form to start, then work on it together. A *job*: you fill in a form, it
works alone and gives back a result (a **run**). A brief's or a job's instructions can use what
the form was filled in with: *Insert from the form* under them puts a field there,
`{{audience}}`. Every agent shows how it is used: *Talk*, *Brief* or *Job*.

**Helpers.** Agents Handler's own features use: the plan builder (*Plans*: writes plans with
you, seeing the project read-only), Ask's router (*Ask*), the prompt writer (*Improve until they
pass*), the App creator (*Make your own apps*), the skill creator (*Write skills with an agent*)
and the skill reviewer (*Review skills*). Each is set up the first time its feature needs it, by
the same card there: who works and what it can do, then **Turn on**. Settings → Helpers lists them
by the feature they serve; a helper's page changes who works and its instructions (*Back to
Handler's* restores them), and shows locked, *set by Plans*, what its feature holds it to.

## Safety

**Sandbox.** Where an agent runs: a container that sees its folder and what you give it,
nothing else of your computer. What it protects and what it does not: [security](security.md).

**Can do.** What an agent may do, in its settings, one row each: its network, then *Asks before
acting*, *Runs containers*, *Windows on my screen* and *Privileged*. A new agent starts with only
the sites it needs and never asks. A setting that weakens the sandbox shows amber, on the agent's
chips too, and saving it is confirmed.

**Network.** *No network*, *Only these sites* (those its model and its tools need, and yours; a
site it is blocked from shows as a card in
the session, *Allow for this agent* or *Keep blocked*: while you watch, the agent waits a few
seconds for your answer, and an answer given later is told to it; when nobody was there, your
inbox tells you, and a plan's step or an automation's run names the hosts it was refused; the
session's network panel shows what was blocked) or *Any site*. A meter of three bars stands for
it, more bars being safer: *No network* three, *Only these sites* two, *Any site* one, in amber.
*Learn the sites it needs* lets every site through for a while and lists them, for you to
choose. A filtered agent is told so when it
starts: when it needs a blocked host it asks you to allow it, naming the host, and ends its
turn; when it can do without, it goes on and says at the end what it did instead. A host you
keep blocked (*Kept blocked*, in the network panel and the agent's settings) is refused the same
way, and the agent is told not to ask for it again. A host is allowed or kept blocked, never
both.

**Permissions.** Whether the agent asks before acting: *Ask first*, *Auto edits*, *Auto-approve*.

**Work folders.** The folders agents may work in at all (Settings → Folders, `~/code` by default).

**Secret.** A token or a key. Agents never hold it: Handler adds it to their requests, towards
the hosts it is for only.

## What an agent can get

**Tool** and its **connections.** A tool teaches agents one kind of system (a Shopify
store, a browser, apps): programs, skills, the hosts they need, what they keep between sessions,
and what they need from the toolbox. You give it to an agent, or to every agent of a project: by
its name, or, when it asks for settings and secrets, through a connection, one set of them
(one store, one token). [Tools](tools.md),
[a browser](browser.md).

**Skill.** Instructions an agent reads when they apply: Library → Skills, given by a project to
all its agents or picked by one.

**Notes folder.** Your notes, given read-only to the agents that need them.
[Notes folders](notes.md).

**Toolbox.** The system every agent works in, the same for all: Handler's base (`git`, Python,
Node, the usual tools), the system packages you turn on (podman, a browser, compilers) and your
own lines. Installing a tool, or saving an agent, that needs something it lacks says which
system package it adds there, once you agree. Settings → Expert → Sandboxes → Under the hood,
[`handler toolbox`](cli/toolbox.md).

## Around your agents

**Automation.** *When this happens, run that*: when a session stops or at a time, your script,
one of your agents or one of your apps. [Automations](automations.md).

**Plan.** Long work in steps, written with the plan builder (or by an agent in its folder), which
you approve once: Handler runs the steps one after another, each a new session of an agent of the
project, and stops at the first step not done. [Plans](plans.md).

**Agents file.** Some or all of a project's agents as one file, to set them up in another
project, here or on another computer, or to give to someone: *Export agents* in a project's ⋯.
It holds their instructions, form, skills and checks, never what is yours (the accounts or
providers they run on, the folder, which connection or notes folder you gave them,
their conversations). *From a file* in **Library → Agents → Get more** (or another project's ⋯ →
*Get agents…*) opens one page: where, what
each agent needs from you (its model…), and what it will be allowed to do. The agents made are
yours: nothing follows the file afterwards. [`handler project
export-agents`](cli/project.md).

**The bell.** At the top of the menu, what needs you in every project and app: a session asking
you something (answered right in its list), a run or a plan that failed. It is quiet, shows a
green dot while something runs, and turns amber with the count when something waits; the browser
tab says the count too (`(2) Handler`). It never makes a sound nor a notification.

**Inbox.** What Handler tells you: your agents' results, your apps' notifications, failed runs;
reached from the foot of the bell's list. A message tied to one of your apps opens it.

**Library.** Where you get and manage what you and your agents use, a shelf each: for you, Apps
and Agents (every agent you have, by project, each saying where it came from); for your agents, Tools (tools, and your connections to them), Skills, Notes (notes folders)
and Automations, each with *Yours* and *Get more* (what the sources offer, Handler's examples).
It is in the menu once you have a project.

**App.** A small web app an agent writes for you and you deploy, used from your desktop or
your phone. It says what it needs in its own words (a folder, an agent, a key) and you give it
those when you install it. It may work on an agent's folder and run that agent when you ask it to
(a notes app and the agent it brings). Handler offers some (Notes, Tracker), installed from
Library → Apps → Get more; you open them from Apps. [Apps](apps.md).

**Source.** A git repository Handler reads to offer apps, agents and tools: Handler's own, and
any you add in Settings → Expert → Sources (you trust it: Handler does not check what is in it). What a
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
| tool / connection | A tool is the package, given to an agent by its name; a connection is one set of its settings and secrets (one store, one token), given with it when it asks for some (`--tool github=github-agent`). |
| tool / system package | A tool is for the agents you give it to, run from a folder of its own; a system package is installed in the toolbox, for every agent (a browser, a compiler a tool needs). |
| agent / agent outside projects / an app's agent | All are agents; one outside projects belongs to no project: someone you talk to in *Chat* (no folder), one made on the *Agents outside projects* page, for Handler, or by the command line in a folder that is no project's. An app's agent is one of that app's parts: on its page only, started by it. |
| source / agents file / app file | A source offers things to install from a git repository, read again over time; an agents file or an app file is one export, given once. What comes from either is installed the same way. |
| agents file / project | A project is a folder and the agents working in it; an agents file is some of those agents written to set them up again in another project, without your folder, accounts or connections. |
| plan / subscription | A plan is steps written with the plan builder (or an agent) and Handler runs; what you pay a vendor for (Claude Pro or Max) is your subscription. |
| session / run | A session is a conversation (a brief's starts from its form); a run is a job's session, started from a form, unattended, with a result. |
| run / automation run | A run is one of an agent with an interface; an automation's run is what the automation ran once (its script, an agent's run, an app's route). |
| session / harness terminal | A session is held by Handler and shown everywhere; `handler terminal` is the harness's own terminal UI in the agent's sandbox, for as long as the terminal is open. |

Where each of these is kept: [where things are kept](configuration.md).
