---
name: app-builder
description: Write or change a Handler app — a small personal web app (Svelte UI + Bun backend + SQLite) that the person deploys to Handler and opens with one click or from their phone. Use when asked to build a small tool, dashboard, tracker, calculator or form "as an app", or to change a folder that has an app.toml.
---

# Apps

An app is a folder that Handler installs and runs for the person: a **Svelte UI** (built to static
files), a **Bun backend** (TypeScript) and a **SQLite** database. One language, one runtime
(Bun, installed here as `bun`), no other stack. The `template/` folder next to this file is a
complete, working app (short notes): start from it.

You write and test the app. **You never deploy it**: the person does, from Handler's Apps page (or
`handler app deploy`), after you are done.

## Layout

```
app.toml                 the manifest (handler.app/v1): name, version, description, needs
server/main.ts           backend entry: serves on the socket handler gives (HANDLER_APP_SOCKET)
server/routes.ts         the routes, all under /api/; GET /api/health must answer 200
server/db.ts             SQLite + migrations (runs migrations/NNN_*.sql not applied yet)
server/handler.ts        what the backend may ask handler: notify(), runAgent(), getRun(), files()
server/migrations/       001_init.sql, 002_….sql — never edit one that was deployed: add one
server/*_test.ts         tests (bun:test): handler runs them before every deploy, a failure stops it
server/package.json      its scripts (dev, test, check) and its type checker, for you only
ui/src/                  Svelte 5 UI; ui/src/api.ts is the only way to call the backend
ui/dist/                 the built UI (`bun run build` in ui/): what handler serves
agent/                   only when it needs an agent: that agent's definition (below)
```

Handler installs `app.toml`, the whole `server/` directory but its `node_modules/`, `ui/dist/` and
the definitions of the agents it needs. Nothing else.

**What it needs, in its own words.** The app's folder holds nothing of the person's: no path of
theirs, no name of one of their agents. It says what it needs (`[needs.files.<name>]`,
`[needs.agents.<name>]`, a secret's name) and the person gives each one when they install it: a
folder, an agent, a value. The code uses the need's name (`files().tasks`, `runAgent(req,
"planner")`). So the same folder installs on anyone's computer, with nothing to edit first.

## Steps

1. `cp -r <this skill's folder>/template <app folder>` (unless the folder is already an app).
2. In `app.toml`: `name` (it becomes the address `http://<name>.localhost:7430/`),
   `description`, `version`. Every name in it (the app's, its needs', its actions') is lowercase
   letters, digits and `-`, starting with a letter, 30 at most: `add-task`, never `add_task`.
3. Backend: routes in `server/routes.ts`, tables in a new migration, tests next to them.
4. UI: components in `ui/src/`, every backend call through `api()` from `ui/src/api.ts`.
5. Check, in this order, and fix until all pass (`bun install` first, in each of `server/` and
   `ui/`: it downloads typescript, vite and svelte from npm):
   - `cd server && bun test`
   - `cd server && bun run check` (the types: Bun runs TypeScript without checking it)
   - `cd ui && bun run build`
6. Preview if you can: `cd server && bun run dev` (backend on 127.0.0.1:8787) and
   `cd ui && bun run dev` (UI on 127.0.0.1:5173, forwards /api to the backend). With a browser
   tool, open http://127.0.0.1:5173 at phone width (390 × 844) too: the app is also used on
   phones.
7. For a change to an app already deployed: raise `version` in `app.toml` (e.g. 0.1.0 → 0.2.0),
   add migrations rather than changing old ones, rebuild the UI.
8. Tell the person it is ready: "`handler app add` in this folder (Handler keeps its own copy of
   the code): its install page says what it needs, give it that, then Install", or, for an app
   they already have, the same `handler app add`, then **Deploy** on its page (a new need is
   asked for then). Working on a draft Handler keeps (the App creator's sessions): **Use it**
   instead. Say what changed and whether data changes (migrations).

## Rules (Handler enforces most of them)

- **Backend runtime:** Bun, offline, in a sandbox. It may read its code and read/write only
  `HANDLER_APP_DATA` (the data folder: `app.db` and any files). No network unless `app.toml` lists
  hosts in `[needs] egress = ["host:443"]` — and the person sees that when deploying. It is
  stopped when unused and started on the next request: keep no state in memory that matters.
- **No npm dependencies in the backend** (`devDependencies` only, for you: the type checker):
  `bun:sqlite`, `Bun.serve`, `node:fs`, `fetch` and the Web APIs cover what an app needs. Handler
  installs `server/` without its `node_modules/` and never downloads anything when it runs the
  app: an `import` of a package fails there. A small library you really need is copied as source
  into `server/` (with its license).
- **UI:** it may only talk to its own backend (`api()`); Handler's Content-Security-Policy blocks
  every other host, inline scripts and frames. No external fonts, CDNs or analytics. Bundle what
  you need.
- **Phones:** the same app is used from phones, where it runs in a frame with **no network and
  no storage**: `api()` still works (Handler carries the call), but `fetch()`, `localStorage`,
  `sessionStorage`, `IndexedDB` and cookies do not. Keep every state in the backend, and keep the
  template's build settings (one script and one stylesheet, images inlined, no dynamic
  `import()`): Handler sends the whole page at once. Design for 390 px wide first.
- **Person:** each request carries `X-HANDLER-Person` (`owner` for now; family members later): keep
  personal data per person, as the template does.
- **Health:** `GET /api/health` answers 200 only once the app is ready (migrations done). A deploy
  starts the new version on a copy of the data and waits for it; without it, the deploy fails.
- **State changes:** use POST/PUT/DELETE for anything that changes data (Handler refuses them unless
  they come from the app's own page).
- **Secrets:** never put keys or passwords in the folder.
- **Size:** the installed app stays small (Handler refuses more than 256 MiB), and no links pointing
  outside the folder.

## Calling a model (or any other service)

The backend calls models itself (the person chose which one); Handler only opens the way:

```toml
[needs]
egress = ["host.containers.internal:3000"]   # a model server on the person's computer
secrets = ["LLM_API_KEY"]                     # its value is entered by the person in handler
```

- `host.containers.internal:<port>` is the person's own computer (e.g. llama.cpp, Ollama,
  llama-swap on port 3000, OpenAI-compatible `/v1/chat/completions`). A server on the local
  network is `192.168.1.20:11434`; a public API is `api.example.com:443`. Ask the person which
  one if they did not say; never pick a paid API on your own.
- Read keys with `process.env.LLM_API_KEY`. Secret names are capitals, digits and `_`; not
  `HANDLER_…`, `BUN_…`, `PATH`, `HOME` or the proxy variables. Never write a key anywhere: not in the
  folder, not in a log line.
- Put the model's URL and name in one place (`server/config.ts`), so the person can change them.
- A model is slow: show the UI as busy while waiting, and handle errors (host down, 401, timeout)
  with a readable message.
- Tests get **no** secrets and no network: test the parsing of answers and the prompts you
  build, with the model call replaced by a function passed in.

## Doing things on its own: a time of day, notifications, files, "later"

```toml
[needs]
notify = true                     # server/handler.ts: notify(title, {body, person})

[needs.files.notes]               # server/handler.ts: files().notes, the folder the person gives
description = "Your notes"        # what the person reads when they choose it
mode = "ro"                       # or "rw"

[routes]
"POST /api/checkin" = "queued"      # from a phone while the computer is off: runs when it is back
```

- **At a time of day** (every morning, every 30 minutes): an app has no schedule of its own. Write
  the route (`POST /api/cron/morning`) and tell the person to add an automation that calls it
  (`~/.config/handler-ai/automations/<name>/automation.toml`, which you cannot write):
  `when = { at = "08:30", days = ["mon", "tue", "wed", "thu", "fri"] }` (or `every = "30m"`, at
  least 5m) and `run = { app = "<the app's name>", call = "POST /api/cron/morning" }`. Handler starts
  the backend and calls it as the owner (header `X-HANDLER-Automation`: the automation's name). It
  runs while Handler runs; after the computer was off, only the latest missed time runs. The route
  must be quick-ish (5 min at most) and safe to run twice.
- **Notifications** go to the computer and, content-free, to the person's phones (who then
  open Handler to read them): short title, optional body, no secrets. At most 30 an hour. `person`
  is `owner` (default) or a person the app is shared with.
- **Files** are the person's: a folder (or a file) they choose at install for each
  `[needs.files.<name>]`, mounted at the same path, read-only unless `mode = "rw"`. Never write a
  path in the app: the code reads `files().<name>`. `description` says what it is for, in the
  person's words ("Where your tasks are kept"). Handler never gives keys nor its own folders.
- **Ask for a folder, not a single file**, even when the app uses one file in it (`agenda.md`
  in "Where your agenda is kept"). Given one file, the app gets that file alone:
  - Many editors save by writing a new file and putting it in the old one's place (TextEdit,
    JetBrains): the app then keeps reading the version it started with until it restarts. The
    person sees "the app ignores my edits". In a folder, the app reads the new one at once.
  - Nothing can be added beside it: no temporary file, no backup, no SQLite journal.
  - A file in `mode = "rw"` must be written in place (`Bun.write(path, text)`, or append). Writing
    a temporary file and renaming it over fails: the app cannot replace it.
  - Never give an app's database as a file need: it lives in `HANDLER_APP_DATA`.
- **Queued routes** are for actions a phone may send while the computer is off (a check-in, a
  note): the phone answers 202 `{queued: true}` at once, Handler runs the call later (up to 7 days).
  They get an `Idempotency-Key` header: store it and ignore a second call with the same key.
  Show the person that it was saved for later (a 202 from `api()`).

## Asking one of the person's agents

When a screen needs judgment (what matters most today, a plan, a summary of the week), the app
does not call a model itself: it runs one of the person's **agents**, which has its own tools,
folder, models and settings. The app says what that agent must be, and ships its **definition**;
the person, when they install the app, sets one up from it (choosing its models) or gives one of
theirs that fits. Only a **job** can be run: an agent with a form and a result.

```toml
[needs.agents.planner]
description = "Tells you what to do next, from your tasks"   # what the person reads
from = "agent"                    # its definition: the folder agent/
worksIn = "tasks"                 # optional: it works in the folder given for [needs.files.tasks]
```

The definition is the folder `from` names, in the format of Handler's built-in agents:

```
agent/agent.toml        [agent]: name, description, and its sandbox (network, egress, allow,
                        confinement), permissions = "bypass" (a job runs alone), skills
agent/instructions.md   what it does on each run: {{key}} is replaced by that field of its form
agent/interface.json    {"fields": <JSON Schema of its form>, "result": <JSON Schema of its result>}
agent/skills/<name>/    optional: skills that come with it (installed in the person's library)
```

```toml
# agent/agent.toml
[agent]
name = "Planner"
description = "Tells you what to do next, from your tasks"
network = "none"                  # its model is reached anyway; add hosts only if it needs them
permissions = "bypass"
```

```json
{
  "fields": {"type": "object", "properties": {
    "request": {"type": "string", "title": "Request", "x-handler": "long-text"}}},
  "result": {"type": "object", "required": ["status", "summary"], "properties": {
    "status": {"enum": ["ok", "attention", "failed"], "title": "Status"},
    "summary": {"type": "string", "title": "Summary"}}}
}
```

- **The form is what the app sends; the result what it reads.** Give every field a `title` (the
  person sees it) and keep its key as the code sends it. A field the app may leave out is not in
  `required`. The result always has `status` (`ok`, `attention` when the person should look,
  `failed`) and `summary` (one sentence: the inbox shows it), then what the app reads.
- **Fits** is checked by Handler: an agent of the person's can be given only if its form takes
  each field the app sends (same type), requires none the app may leave out, and its result
  always gives each required field of the definition's (same type); with `worksIn`, it works in
  that folder. Changing the definition's form or result in a new version can make the agent given
  no longer fit: the person is told, and gives (or sets up) another.
- The person's agent is theirs once set up: a new version of the app does not change its
  instructions or settings. Say in the instructions everything a run needs to know (the folder's
  files and their format, what to write where).

```ts
// in a route answering the person (a click): pass that request, its X-HANDLER-Start header
const run = await runAgent(req, "planner", { request: "What matters most today?" });
// then GET /api/... polled by the UI every few seconds:
const now = await getRun(run.id);   // state: waiting | running | succeeded | failed | cancelled
// now.result: the job's result, { status, summary, ... } once it succeeded
```

- **Only while answering the owner.** A run starts only from a route the owner called (their
  click, on the computer or the phone): Handler puts a start token in that request's
  `X-HANDLER-Start` header, valid until it is answered. Start the run before answering. A route an
  automation calls, or a family member's request, gets none: an agent on a schedule is the
  person's automation, not the app's.
- A run takes minutes: answer at once with the run's id, show it as busy, poll `getRun` (from a
  route the UI calls every few seconds). Its result also goes to the person's inbox, with a button
  that opens the app: the person may close it meanwhile.
- One run of an agent at a time: a second one waits for the first (`waiting`), at most 30 minutes.
- Its `fields` are its form's (wrong ones: `runAgent` throws with the reason). At most 30 runs an
  hour. The deploy fails while a need has no agent given that fits.
- **The agent on a schedule** is an automation, not the app: suggest it, and the person makes it
  from the app's page (off until they turn it on; its results open the app):

  ```toml
  [[automations]]                   # up to 5
  description = "What to do next, every 5 hours"
  when = { every = "5h" }           # or { at = "08:30", days = ["mon", "fri"] }
  run = { agent = "planner", input = { fields = {} } }   # one of its [needs.agents]
  ```

## Its actions: what the person can ask it in a sentence

An app says what it does in sentences the person could say, its **actions**: `[actions.<name>]`
in `app.toml`. Its page in Handler lists them (with *Try*), and Ask picks one when the person
asks something. Each is done by the app's **code** (instant: prefer it for anything you can
write down, and for rules that must hold, such as "no two appointments at once") or by one of
its **agents** (judgment: "plan my day").

```toml
[actions.add]
description = "Add something to my calendar, on a day, maybe at a time"  # what the router reads
examples = ["Tomorrow I call the bank at 10"]                             # what a person says
route = "POST /api/actions/add"
[actions.add.fields]                       # its form: the JSON Schema of an object, as a job's
type = "object"
required = ["what", "day"]
properties.what = { type = "string", title = "What" }
properties.day = { type = "string", title = "Day", pattern = "^\\d{4}-\\d{2}-\\d{2}$" }

[actions.plan]
description = "Plan my day: what matters most, what is late"
agent = "planner"                       # a [needs.agents.planner]: its form is the agent's own
```

- An action done by a route: Handler POSTs the fields as JSON (already checked against `fields`) as the owner
  (`X-HANDLER-Person: owner`, `X-HANDLER-Action: <name>`), and the backend answers at once (30 s at
  most) `{"status": "ok" | "attention" | "failed", "summary": "…", "data": …}`: the summary one
  or two plain sentences, readable aloud ("Added Wednesday 21 October at 10:00. It clashes with
  the dentist at 10:00."); `attention` when the person should look at something. Dates come as
  `YYYY-MM-DD`: the assistant turns "tomorrow" into one.
- An action done by an agent: the agent's job must give `status` and `summary` in its result (the Planner's
  interface.json, above). Its run takes a while; its answer also reaches the person's inbox.
- Test the routes like the others (`main_test.ts`).

## A folder shared with an agent

An app and an agent can work on the same data: one folder the person gives, read-write for the
app (`[needs.files.tasks] mode = "rw"`), where the agent works (`worksIn = "tasks"`). It is the
same folder on disk, no copy: what the person changes in the app is what the agent reads at its
next run, and what the agent writes is on the app's next screen.

```toml
[needs.files.tasks]
description = "Where your tasks are kept, shared with Planner"
mode = "rw"
init = ["agent/README.md"]        # copied into the folder given, when it has no README.md yet
```

- Keep the data in files both can read: JSON (one file per kind of thing, `tasks.json`) or JSON
  Lines for a log that grows (`notifications.jsonl`); write down their format in a `README.md`
  (copied into the folder by `init`) and say in the agent's instructions to follow it. The app
  must work on an empty folder: no file yet means nothing yet.
- Both may write at the same moment: read the file again just before writing, change it, then
  write it whole to a temporary file in the same folder and rename it over the old one. Never keep
  the file's content in memory between requests.
- Simple edits (done, postponed, deleted) are the app's, with no model; leave judgment to the
  agent's runs.

## Dates, money, text

- Store dates as ISO 8601 strings in UTC (`strftime('%Y-%m-%dT%H:%M:%SZ','now')`), show them
  with `toLocaleString()`.
- Store money as integer cents; compute in cents; format with `Intl.NumberFormat`.
- The person may write in any language: keep the UI's words short and plain, match the
  language they asked in.
