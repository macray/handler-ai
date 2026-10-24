# Automations: writing one

An **automation** is *when this happens, run that*. **When**: a session stops, or a time comes
(every hour, every weekday at 08:30). **That**, one of:

- **your script**, in a sandbox with no network: it may ask one of your models, and what it writes
  is added to a knowledge note once it succeeded. Example (the one Handler ships, `env-issues`): when
  a session stops, read what was said since the last time, ask a model which tools, permissions,
  hosts or files the agent lacked, and add the findings to `handler/env-issues.md` in your knowledge
  folder. A finding that comes back often is the one to fix.
- **one of your agents** (an agent with a form and a result): every hour, review this project's
  code. Its result comes to your **inbox**.
- **a route of one of your apps**: every weekday at 08:30, the coach app reads your agenda and
  notifies you.

Nothing here needs the Handler source code. Every key and rule, for reference:
[contracts](../dev/contracts.md) §I.

## Schedule one of your agents (the web UI)

**Schedule** (in the menu) → **New automation**, or from the agent's settings: at the top, *How will you use
it?* → *Job*, then **Save and run it on a schedule…** (under *How it is started*, which also lists the automations
that run it): the agent is saved and the form opens for it. Choose when (every
morning, weekdays at 08:30, every hour, or your own; or when a session stops), the agent (one that
runs unattended, below) and what it is given, and a name. The page says what it will do before
you save: what starts it, where the agent works, its network and model, its warnings (an
account's terms) and its problems. **Create and turn on**, or **Create, off** to try it first.

The agent runs on its **default model**, the first in its settings (the one new sessions start
with too): to run it on an API key while you chat on your subscription, put the provider first.

It is saved as `~/.config/handler-ai/automations/<name>/automation.toml`: a file like any other here,
for you to read and edit. **Change** on its page opens it in the same form again (saving there
replaces what you wrote in the file by hand, comments too); one that is on stays on. Where your
agents are listed, the ones an automation runs show when, and their next run. A route of one of your apps is made the same way. A script starts from
an example:

## Start from the example

```bash
handler automation examples                    # what handler ships
handler automation new env-issues --from env-issues
```

or the web UI: **Schedule** → *A script, from an example*. It is copied to
`~/.config/handler-ai/automations/env-issues/`, **off**. Then:

1. Edit `automation.toml` in your editor: the model it calls (`services.llm`, one of your
   providers' models, below), the note it adds to (`append.to`, a markdown note of your knowledge
   root whose folder exists), and `only` if it is for some projects or agents.
2. Try it on a session that stopped: `handler automation try env-issues` (the last one) or
   `--session <id>`; on its page, **Try**. A try runs it on the whole conversation and adds
   nothing: it shows what it would add.
3. Turn it on: `handler automation enable env-issues`, or **Turn on** on its page. You are shown what
   it does and asked to confirm. Only the sessions that stop from then on are read.

## What is in the folder

```
~/.config/handler-ai/automations/<name>/
  automation.toml        when it runs, what runs, the models it may call, the notes it adds to
  extract.py, prompt.md, …   whatever your script uses
```

```toml
apiVersion = "handler.automation/v1"
description = "What my agents lacked in their environment"
when = "session.stopped"                # or a time: below
only = { project = ["my-app"] }         # optional: projects, agents (by name); absent: any
run = "python3 extract.py"              # a command line, run with sh in this folder
timeoutSec = 600                        # optional, at most 3600
services = { llm = ["mistral/mistral-large-latest"] }   # "provider/model"

[[append]]
from = "note.md"                        # a file the run writes in $HANDLER_OUTPUT
to = "handler/env-issues.md"            # a note of your knowledge root
```

The folder is the truth: Handler reads it every time, and writes it only when you make one (an example
copied, the web UI's form); never an agent. The automation's page
and `handler automation show <name>` show its files, what it may do and its problems (a model that is
not one of your providers', a note whose folder does not exist, an agent it runs that was
deleted). One with problems never runs.

**Agents and projects by name, then for good.** You name the agent it runs, and those of `only`,
by name. The first time Handler reads a name, it remembers which agent (or project) it is: rename
it later and the automation still runs (or watches) the same one; the file keeps the name you
wrote. Delete it, and the automation says so and stops until you choose another. Edit the file to
name another agent, and Handler reads that name again.

**On and off.** Its page (and `handler automation show`) says what it does in sentences: what starts
it, what runs and what it may reach, where results go. Turning it on is your approval; while it
is on, your edits of its files apply at its next run. Only you turn one on (the web UI, `handler`):
never an agent, never anything in a sandbox, and no agent can write its files (Handler never gives a
sandbox its own config folder).

## At a time

```toml
when = { every = "1h" }                          # "30m", "2h": at least 5 minutes
when = { at = "08:30" }                          # every day, your local time
when = { at = "08:30", days = ["mon", "fri"] }   # those days only
```

Handler runs it itself (no cron, no systemd timer): while Handler runs. It does not run when you turn it
on, but at its next time (its page says when). After the computer was off or asleep over several
times, only the **latest** runs, once, and the run says how many it missed ("3 missed before it").
`every` keeps its rhythm whatever a run's length. A scripted one gets only `event.json` in
`$HANDLER_INPUT` (`{type: "schedule", slot, missed}`). **Try now** (or `handler automation try <name>`)
runs it at once.

## Running one of your agents

```toml
when = { every = "1h" }
[run]
agent = "reviewer"                      # its name
project = "my-app"                      # its project; absent: an agent outside projects
input = { fields = { focus = "security" } }   # its form, as its interface says
```

The agent must be a **job** (a form and a result: in its settings, *Job*; a *Brief* has no
result and needs you, so an automation cannot run it; its
editor always keeps the two result fields below): it then runs on its
own, never asks you, in its own sandbox with its own settings: its folder (read-write: it may
change files there, for example a `decisions.md` it reads again next time), its network, its
model. Its result must say how it went and in one sentence what it found, in two required fields
the inbox shows:

```json
{
  "type": "object",
  "required": ["status", "summary"],
  "properties": {
    "status": { "enum": ["ok", "attention", "failed"] },
    "summary": { "type": "string" },
    "issues": { "type": "array", "items": { "type": "string" } }
  }
}
```

Everything else in the result is kept with the message and shown on the run's page. A run with no
valid result (it timed out, crashed, gave none) comes to the inbox as failed. Each run is a
session of the agent, started by the automation: open it from the run to see what it did.

**One run at a time.** While the agent is already running (another automation's run, one you
started), this one waits for it, then runs; after 30 minutes of waiting it fails, and your inbox
says so.

**Its results open an app.** When you act on what the agent says in one of your apps (a planner
app for a calendar agent), name it: each result in your inbox gets a button that opens it, on the
computer and on your phone. In the form: *Its results open*.

```toml
app = "planner"                         # before [run]
```

**Its model.** An agent runs here on its model. A subscription (an account) is meant for
your own, ordinary use; whether a vendor lets an agent run on it unattended is said on the
accounts screen, per vendor, after Handler read their terms:

- **allowed**: it runs;
- **check your plan's terms**: it runs, with a warning: read the terms, an API key (a provider)
  is recommended;
- **refused**: it does not run (today: a Claude subscription, which Handler uses for interactive
  sessions only): give the agent a provider (an API key) first.

## Calling one of your apps

```toml
when = { at = "08:30", days = ["mon", "tue", "wed", "thu", "fri"] }
run = { app = "coach", call = "POST /api/cron/morning" }
```

Handler starts the app if needed and calls that route as you (the header `X-HANDLER-Automation` has the
automation's name); an error answer is a failed run. What the app notifies comes to your inbox.

## Your inbox

What Handler tells you, newest first: your apps' notifications, your agents' results (run by an
automation, or by one of your apps on your request), and the runs that failed (not a script's try:
you watched it). A message tied to an app has a button that opens it. The **Inbox** page in the
web UI (the menu counts its unread messages), `handler inbox`, your paired phone; a message for you is also shown on your desktop and pushed, content-free, to
your phone. A script that succeeded says nothing: its result is in its note.

## What a script gets

It runs in your toolbox image (the one your agents use: `python3`, `jq`, … are there), in a copy
of its folder (read-only), as you, with **no network** and no secret.

| Variable | What |
|---|---|
| `HANDLER_INPUT` | read-only. On a stopped session: `event.json` (the session, its agent and project, how it stopped, the events read), `session.json` (the session and its agent's sandbox settings), `events.ndjson` (the log's events read), `transcript.md` (the same, for reading). At a time: `event.json` only (the time, the times missed) |
| `HANDLER_OUTPUT` | where it writes; the `from` files of `[[append]]` are read from here |
| `HANDLER_TRY` | `1` in a try, else `0` |
| `HANDLER_RUN` | the run's id |
| `HANDLER_SERVICES` | the socket `handler-llm` talks to (only when it lists models) |

The first run on a session reads its whole conversation; later ones read what came after (a
session resumed then stopped again is read in parts, each part once). `transcript.md` has the
person's prompts, the agent's messages and thoughts, each tool call with its input and output (cut
to their first 2 000 and last 1 000 characters), permission answers, turn ends; secret values of
Handler's store are replaced by `«redacted»`.

The conversation holds text written by others (web pages, files, tool output): treat it as data,
and tell the model to (the example's `prompt.md` does).

## Calling a model: `handler-llm`

```bash
handler-llm --model mistral/mistral-large-latest --prompt prompt.md [--system system.md] \
        [--schema findings.schema.json] < "$HANDLER_INPUT/transcript.md" > answer.json
```

- Standard input is the text the prompt is about. Without `--schema` it prints the answer's text;
  with it, one JSON value valid against that JSON Schema (Handler asks the model once more when its
  answer does not match). Exit 1 with the reason on stderr when the call fails or the answer is
  still not valid.
- The model is one of `services.llm`, on one of your **providers** (an API key or a local server,
  Settings → Model access): Handler calls it for the script, the key never enters the sandbox. A
  script runs on its own: it never uses a subscription (an account).
- Limits: 120 s per call, one call at a time, 50 calls per run, 256 KiB of prompt and input per
  call. A long conversation is the script's to cut in parts (the example's `chunks`).
- Each call (model, tokens, time, never its text) is in the run's `services.ndjson`; a run's
  totals are on its page.

## What is added to the note

Once the run succeeded (not in a try), each `from` file that exists is added to the end of its
note, after a line saying where it came from:

```
<!-- handler automation env-issues · run a_3f… · session s_9c… · 2026-10-06T10:42:00+00:00 -->
- 2026-10-06 · my-app/Dev · missing-tool · npm: command not found when running the tests · session s_9c…
```

The note is created when missing. Nothing else is written: a script that fails, times out or is
cancelled adds nothing. What a model wrote ends up in notes your agents may read later: the
comment says where it came from.

## Runs and debugging

- `handler automation runs <name>`, or its page: each run's state, what it was for (the session and
  events it read, or its time and the times missed), the agent's run, its model calls and
  tokens, what it added; `handler automation log <run>` (or **Log**) is its
  output (stdout and stderr). A session's page shows the runs on it (**Automations**).
- A run's folder keeps everything: `~/.local/state/handler-ai/automations/<name>/runs/<run>/`
  (`definition/` what ran, `input/`, `output/`, `run.log`, `services.ndjson`, `run.json`); the
  last 50 runs are kept, none older than 30 days.
- One run at a time for all automations (an agent's run too: the page says what a waiting run is
  behind); at most 100 runs per automation per day (more wait until the next day).
  `handler automation cancel <run>` stops one.
- **Delete** on its page, or `handler automation delete <name>` (both say what goes and ask first):
  its folder with every file in it, its runs and their logs; a run in progress is cancelled.
  What it told your inbox stays. A new one of the same name starts with no runs.
- A session stopped by deleting it, or by Handler restarting, starts nothing (the part before a
  restart is read with the next stop). Agents with an interface (runs) start nothing.
- "toolbox not built": `handler image rebuild toolbox`.
