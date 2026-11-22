---
name: app-builder
description: Write or change a Handler app — a small personal web app (Svelte UI + Bun backend + SQLite, and jobs: work it asks a model to do) that the person deploys to Handler and opens with one click or from their phone. Use when asked to build a small tool, dashboard, tracker, calculator or form "as an app", or to change a folder that has an app.toml.
---

# Apps

An app is a folder that Handler installs and runs for the person: a **Svelte UI** (built to static
files), a **Bun backend** (TypeScript) and a **SQLite** database, and, when some of its work
needs a model, its **jobs**. One language, one runtime (Bun, installed here as `bun`), no other
stack. The `template/` folder next to this file is a complete, working app (short notes, an
action done by its code, a job writing a note and its `then` saving it): start from it.

You write and test the app. **You never deploy it**: the person does, from Handler's Apps page (or
`handler app deploy`), after you are done.

## Layout

```
app.toml                 the manifest (handler.app/v1): name, title, version, needs, jobs, actions…
server/main.ts           backend entry: serves on the socket handler gives (HANDLER_APP_SOCKET)
server/routes.ts         the routes, all under /api/; GET /api/health must answer 200
server/db.ts             SQLite + migrations (runs migrations/NNN_*.sql not applied yet)
server/handler.ts        what the backend may ask handler, typed: notify, nudge, nudgeDone,
                         withdrawNudge, answeredNudge, runJob, getRun, listRuns, cancelRun, files,
                         smdParse, smdCheck, smdWrite, history, historyChange; the types JobEnded,
                         ActionResult, NudgeKey, NudgeRef
server/migrations/       001_init.sql, 002_….sql — never edit one that was deployed: add one
server/*_test.ts         tests (bun:test): handler runs them before every deploy, a failure stops it
server/package.json      its scripts (dev, test, check) and its type checker, for you only
ui/src/                  Svelte 5 UI; ui/src/api.ts is the only way to call the backend
ui/dist/                 the built UI (`bun run build` in ui/): what handler serves
jobs/<name>.md           one per [jobs.<name>]: that job's instructions (nothing else in jobs/)
schemas/                 only with `schemas`: the formats of its documents, <$id>.schema.json
```

Handler installs `app.toml`, the whole `server/` directory but its `node_modules/`, `ui/dist/`,
`jobs/` and `schemas/`. Nothing else.

**What it needs, in its own words.** The app's folder holds nothing of the person's: no path of
theirs, no model, no account. It says what it needs (`[needs.files.<name>]`, a secret's name) and
the person gives each one when they install it: a folder, a value. Who runs its jobs (which
program, account or API key, model) is chosen by the person too: their **Who works**. The code
uses the need's name (`files().tasks`, `runJob(req, "plan")`). So the same folder installs on
anyone's computer, with nothing to edit first.

## Steps

1. `cp -r <this skill's folder>/template <app folder>` (unless the folder is already an app).
2. In `app.toml`: `name` (it becomes the address `http://<name>.localhost:7430/`), `title`
   (what the person sees it called, "Planner"; without it, its name), `description`, `version`.
   Every name in it (the app's, its needs', jobs', actions', nudges') is lowercase letters,
   digits and `-`, starting with a letter, 30 at most: `add-task`, never `add_task`.
3. Backend: routes in `server/routes.ts`, tables in a new migration, tests next to them.
4. Jobs, if some work needs a model: `[jobs.<name>]` and `jobs/<name>.md` (below).
5. UI: components in `ui/src/`, every backend call through `api()` from `ui/src/api.ts`.
6. Check, in this order, and fix until all pass (`bun install` first, in each of `server/` and
   `ui/`: it downloads typescript, vite and svelte from npm):
   - `cd server && bun test`
   - `cd server && bun run check` (the types: Bun runs TypeScript without checking it)
   - `cd ui && bun run build`
7. Preview if you can: `cd server && bun run dev` (backend on 127.0.0.1:8787) and
   `cd ui && bun run dev` (UI on 127.0.0.1:5173, forwards /api to the backend). With a browser
   tool, open http://127.0.0.1:5173 at phone width (390 × 844) too: the app is also used on
   phones. Jobs do not run in a preview (no Handler there): test their `then` route instead.
8. For a change to an app already deployed: raise `version` in `app.toml` (e.g. 0.1.0 → 0.2.0),
   say in `changes` what this version changes, for the person who updates to it (top level,
   ≤ 500 characters, their words: `changes = "Import a LinkedIn profile from its link"`), add
   migrations rather than changing old ones, rebuild the UI.
9. Tell the person it is ready: "`handler app add` in this folder (Handler keeps its own copy of
   the code): its install page says what it needs, give it that and choose who works on its
   jobs, then Install", or, for an app they already have, the same `handler app add`, then
   **Deploy** on its page (what it may now reach is asked then). Working on a draft Handler keeps
   (the App creator's sessions): **Use it** instead. Say what changed and whether data changes
   (migrations).

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
  personal data per person, as the template does. Every `X-HANDLER-…` header is Handler's: one
  sent by a page never reaches the backend, so trust them.
- **Health:** `GET /api/health` answers 200 only once the app is ready (migrations done). A deploy
  starts the new version on a copy of the data and waits for it; without it, the deploy fails.
- **State changes:** use POST/PUT/DELETE for anything that changes data (Handler refuses them unless
  they come from the app's own page).
- **Secrets:** never put keys or passwords in the folder.
- **Size:** the installed app stays small (Handler refuses more than 256 MiB), and no links pointing
  outside the folder.
- **Durations** (`every`, `remind.every`, a job's `timeout`) are minutes, hours or days: `"30m"`,
  `"2h"`, `"1d"`.

## Look

An app may look however it wants; it must not look unfinished. Handler imposes no theme.

- **Start from the template's `ui/src/app.css`.** It styles the plain elements (headings,
  buttons, inputs, lists, tables, `details`, `code`), light and dark, phone and desktop, plus
  seven classes: `.card` (`ul.card` is a list of rows), `.row`, `.toolbar`, `.chip`, `.empty`,
  `.notice`, `.error`. Write plain HTML with these before writing any CSS.
- **Make it yours with the tokens, not the rules:** one `:root { … }` after the file, setting
  `--accent`, `--radius`, `--font` (and `--width`, `--font-mono`). Your own CSS is for your own
  layout (a grid, a calendar), a few dozen lines, using `var(--line)`, `var(--muted)`… not new
  colours.
- **One accent**, dark enough to carry white text. It marks one thing at a time: the primary
  button, a count, the focus ring. Everything else stays neutral: no colour per item, per
  category or per state beyond `--ok` / `--warn` / `--danger`.
- **Layout:** one column (`main` is already one, up to `--width`), sections under an `h2`,
  spacing from the steps the file uses (.25, .5, .75, 1, 1.5, 2 rem). No sidebars, no fixed
  bars.
- **Words:** a button says what it does ("Add what I did", "Write a CV", not "Submit",
  "OK"). One `primary` button per view; Cancel/Skip are `quiet`; Delete is `danger`. Dates in
  words people say ("today 09:12", "3 Oct"), not `toLocaleString()`.
- **Every page has its states**, each in a sentence that says what to do:
  - empty: `.empty`, what is missing and the one button that fills it ("Import a CV");
  - loading: `aria-busy="true"` on the button or line that waits; disable what would repeat it;
  - error: `.error`, what failed and what to do now, in the person's words, not a stack trace;
  - done: `.notice` saying what changed ("Added 2 things to Staff engineer").
- **Phone first:** build and check at 390 px, then widen. Rows wrap; nothing scrolls sideways;
  tap targets stay ≥ 40 px (the file does it: don't shrink buttons or inputs).
- **Dark mode comes free** from the tokens: never write a colour as a hex value in a rule; if
  you need one, add a token with `light-dark(light, dark)`.
- **Toggles and states in markup:** `aria-pressed="true"` for the open panel, `disabled` for
  what cannot be done yet, a `.chip` (with `.ok` / `.warn` / `.danger` it gets a dot) for a
  state.
- **Do not:** coloured left stripes or coloured rings on cards to show state (a soft tint and a
  chip instead); gradients; text under 13 px or grey on grey;
  external fonts, CDNs or icon sets (the CSP blocks them; a font you need goes in `ui/src/`);
  copying Handler's own pages (its sidebar, its cards): an app is a page, not a Handler screen.

## Code or job: where each piece of work goes

- **Code** for anything you can write down: adding, listing, moving, totals, dates, rules that
  must hold ("no two appointments at once"). It answers at once and the same way every time.
  A quick function is always code, never a job.
- **A job** for what needs judgment or language: "what matters most today?", "write a CV for this
  ad", "summarize my week". A job is a model at work, in its own sandbox, for seconds to
  minutes, on the person's subscription or API key: worth it only where code cannot do it.
- **The backend calling a model itself** (`egress` + a secret, below) only when the person asks
  for a particular model service (their llama.cpp server, say). Otherwise prefer a job: the person
  chooses and pays for who works, and sees each run.

## Jobs: work that needs a model

A job is declared in `app.toml`, its instructions in `jobs/<name>.md`. The app says what the job
does and what it may reach; the **person** chooses who works on it (program, account or API key,
model): at install, for all the app's jobs, and per job later on the app's page. Never write a
model's or a program's name in the app.

```toml
[jobs.plan]
description = "Tells you what to do next, from your tasks"   # the person reads it (≤ 200)
files = { tasks = "write", notes = "read" }   # the folders it reaches, each a [needs.files.*]
worksIn = ["tasks"]               # where it starts: the first of them it writes
schemas = ["task-list@1"]         # optional: SMD formats it reads/writes (among the app's)
egress = ["api.example.com:443"]  # optional: hosts it may reach (its model's are added)
timeout = "30m"                   # optional: each turn ("30m", "2h", at most "1d")
then = "POST /api/plans/ended"    # optional: a route of yours, called once when a run ends

[jobs.plan.fields]                # its form: the JSON Schema of an object (what you send)
type = "object"
properties.request = { type = "string", title = "Request", "x-handler" = "long-text" }

[jobs.plan.result]                # what it gives back: always `status` and `summary`
type = "object"
required = ["status", "summary", "next"]
properties.status = { enum = ["ok", "attention", "failed"], title = "Status" }
properties.summary = { type = "string", title = "Summary" }
properties.next = { type = "array", items = { type = "string" }, title = "Next" }
```

`jobs/plan.md`:

```markdown
Read the tasks in your folder (`tasks.json`, its format in `README.md`) and say what the person
should do next. They asked: {{request}}

Change only `tasks.json`, as README.md says. In your result, `next` lists up to three tasks
(their titles), `summary` says in one sentence why the first one.
```

- **Instructions:** `{{key}}` is replaced by that field of its form (a list joined by ", ", yes/no
  as `yes`/`no`, an empty field by nothing); a `{{key}}` that is no field of its form fails the
  deploy. Handler adds below them the input as JSON, a `## Folders` section with each folder's
  path and whether it may write it, and the rule for its result. Each run starts fresh, knowing
  nothing of the last one: say everything it needs (the files and their format, what to write
  where, what to give back). Paths come from `## Folders`: never write one.
- **The form is what you send; the result what you read.** Give every field a `title` (the
  person sees it on the action's form, Try and the run's page). The result always has `status`
  (`ok`; `attention` when the person should look; `failed`) and `summary` (one sentence: the
  inbox shows it), then what your code reads. The deploy refuses a result without them.
- **What it may reach is the app's, and only that.** A run gets the folders in `files` at the
  paths the person gave the app, nothing else of theirs nor of the app: not `HANDLER_APP_DATA`,
  not the database, not the backend's secrets. Its network is filtered to `egress` and its
  model's hosts. The app's page shows it (*Can do*) and the person cannot widen it; a new
  version reaching more is said to them before they deploy it. Why: the person chooses who
  thinks, the app says where it may go, and nobody widens the other's part unseen.
- **`read` is read-only, enforced** (the folder is mounted read-only). `write` needs the files
  need given `mode = "rw"`.
- **The model alone.** A job reaching no folder, schema or host may run on a model with no
  program (seconds, an API key only): it reads its instructions and form and answers. A job with
  folders, schemas or hosts needs a program; the person's choice is greyed with why otherwise.
- **Who works, and the vendors' terms.** A subscription is for runs the person starts; a job an
  automation runs is recommended an API key, and a Claude subscription is refused there. Handler
  says so to the person; nothing to do in the app but not to assume a run will always happen.
- **A version reaching more**, a job added, a folder now written, a host: the person sees it
  before deploying. Declare only what the job needs.

### Writers of a folder take turns: return what you produce

Runs of jobs that **write** a folder run one at a time on it, in the order they were started
(per folder, whatever the job, whatever the app); runs only **reading** it never wait, even while
one writes (they may see it half-changed: harmless, run again). A run waits at most 30 minutes,
then fails. Why: two models editing the same files at once lose each other's changes.

What follows for the app's design:

- **A job that produces something (a CV, a report, a draft) returns it in its result**, reading
  its folders only; your `then` route saves it (the template's `draft` and `POST
  /api/drafts/ended`). It never waits for a turn, and the app decides where and how it is
  saved.
- **Write only to change what is there** (mark tasks done, reorder a list): then `write`.
- **Two kinds of data that never conflict are two files needs** (`cv`, `cvs`): a job rewriting
  your CV and one adding a cover letter then never wait for each other. The turn is per
  folder, never per file inside it.

### Starting a run

A job runs when the person asks one of its **actions** (below), when an **automation** runs it,
or when your **code** starts it with `runJob`, only while answering the owner:

```ts
// in a route answering the person (a click): pass that request, its X-HANDLER-Start header
const run = await runJob(req, "plan", { request: "What matters most today?" });
// answer at once with run.id; the UI polls a route that reads it every few seconds:
const now = await getRun(run.id);   // state: waiting | running | succeeded | failed | cancelled
// now.result: the job's result once it succeeded; now.error: why it failed
```

- **Only while answering the owner.** Handler puts a start token in each request of the owner's
  (`X-HANDLER-Start`, valid until it is answered): start the run before answering. A route an
  automation calls, a nudge's `prepare`, a `then`, a family member's request get none:
  `runJob` throws. Why: a job spends the person's subscription or money and acts in their
  folders; it runs when they ask, or on a schedule they approved (an automation), never because
  the app decided to. On a schedule: suggest an automation (below).
- A run takes minutes: show it as busy. Its end also reaches the person's inbox, with a button
  that opens the app: the person may close it meanwhile.
- `fields` must fit its form (`runJob` throws with the reason); at most 30 runs an hour; nobody
  chosen to work on it, or a folder not given: `runJob` throws, saying so.
- **Its runs are Handler's:** `listRuns()` gives the app's last 50, newest first: each one's job,
  what it was asked (`fields`: the fields its run got, from `runJob`, an action's form or an
  automation), state, result or error, when it started and ended, and `startedBy`: your code, one
  of its actions and how the person asked it (`via`: `ask`, `try`, `nudge`), or an automation.
  Keep no table of runs nor of the requests you started them with: `listRuns()` (or
  `getRun(id)`) says both. `cancelRun(id)` stops one.

### `then`: the app told when a run ended

`then = "POST /api/…"` names a route Handler calls **once** when a run of that job ended,
succeeded or failed, whatever started it (an action, an automation, your code), the backend
started if needed, with a `JobEnded` body:

```ts
case "POST /api/plans/ended": {
  const ended = (await req.json()) as JobEnded<{ next: string[] }>;
  // { runId, job, state: "succeeded" | "failed", fields, result (null when it failed) }
  if (ended.state === "succeeded") savePlan(db, ended.runId, ended.result!.next);
  return Response.json({ ok: true });
}
```

- It comes as the owner, with **no start token**: it cannot start another job. Why: a `then`
  starting a run whose `then` starts a run would loop forever.
- Answer 2xx within 5 minutes. A failure is shown on the run and its inbox message and never
  retried: the result stays in the run (`getRun`, `listRuns`). A cancelled run calls nothing.
- It is the place to save what a job produced, to send a nudge about it, to notify.

### On a schedule: an automation it suggests

An app has no schedule of its own: a job on a schedule is the person's automation. Suggest it
and it is installed with the app: the install page shows it with a switch, on unless you mark it
`optional` (then off until the person turns it on; the CLI asks for each). Its results open the
app. Mark optional what the app works without (a weekly digest), not what it is for:

```toml
[[automations]]                   # up to 5
description = "What to do next, every 5 hours"
when = { every = "5h" }           # or { at = "08:30", days = ["mon", "fri"] }, every = "1d"
run = { job = "plan", input = { fields = {} } }   # one of its [jobs]
# optional = true                 # off at install until the person turns it on
```

An automation's run of a job waits for its turn like any other, and calls its `then`.

## Its actions: what the person can ask it in a sentence

An app says what it does in sentences the person could say, its **actions**: `[actions.<name>]`
in `app.toml`. Its page in Handler lists them (with *Try*), Ask picks one when the person asks
something, a nudge opens one's form. Each is done by its **code** (`route`, instant) or by one of
its **jobs** (`job`, takes a while). An action is a way in; a job is the work: one job may be
done by an action, an automation and your code alike.

```toml
[actions.add]
description = "Add something to my calendar, on a day, maybe at a time"  # what the router reads
examples = ["Tomorrow I call the bank at 10"]                             # what a person says
route = "POST /api/actions/add"
[actions.add.fields]                       # its form: the JSON Schema of an object
type = "object"
required = ["what", "day"]
properties.what = { type = "string", title = "What" }
properties.day = { type = "string", title = "Day", pattern = "^\\d{4}-\\d{2}-\\d{2}$" }

[actions.plan]
description = "Plan my day: what matters most, what is late"
job = "plan"                               # its form is the job's `fields`
```

- **Done by a route:** Handler POSTs the fields as JSON (already checked against `fields`) as the
  owner (`X-HANDLER-Person: owner`, `X-HANDLER-Action: <name>`, a start token: it may `runJob`),
  and the backend answers within 30 s an `ActionResult`: `{"status": "ok" | "attention" |
  "failed", "summary": "…", "data": …, "open": "/?line=…"}`, the summary one or two plain
  sentences, readable aloud ("Added Wednesday 21 October at 10:00. It clashes with the dentist at
  10:00."), and `open` (optional) the page of your UI showing what it did: Ask's history opens
  your app there. `askedVia(request)` says where it was asked (`"ask"`, `"try"`, `"nudge"`):
  show "added by Ask" on what Ask changed, so the person sees it where it landed. Dates come as
  `YYYY-MM-DD`: the assistant turns "tomorrow" into one.
- **Done by a job:** a run of it, its answer the job's `status` and `summary`; it also reaches the
  person's inbox. Its `then` is called as for any run.
- Test the routes like the others (`main_test.ts`).

## Its nudges: asking the person to do something

A **nudge** asks the person to do something (log the day's work, answer a question about their
CV). It waits in their inbox, open, until it is done; Handler alerts them, reminds them, and lets
them tone it down. Declare each one in `app.toml`, under a name that stays the same:

```toml
[nudges.daily-log]
description = "Add what you did today"     # for the person, on the app's page
action = "log"                             # opens that action's form (one of [actions]), or
# open = "/log"                            # a page of the app's UI
remind = { every = "2h", times = 2 }       # reminders after the first alert (≥ 30m; ≤ 5); none: once
ifIgnored = "The day stays empty"          # shown when it expires unanswered
when = { at = "18:00", days = ["mon", "tue", "wed", "thu", "fri"] }  # Handler sends it then
prepare = "POST /api/nudges/daily-log"     # optional, with `when`: called first, to fill it in or skip it
until = "next"                             # optional, with `when`: still open at its next time, it expires
```

**At a time** (`when`, as an automation's: `at` with `days`, or `every` "30m", "2h", "1d", at
least 5m): Handler sends it at each time, your code does not, and no automation is needed. The
person may set their own time on the app's page (theirs replaces yours). It comes while Handler
runs; after the computer was off, only the latest missed time comes. Without `prepare`, it is
sent as it is: its `description` as title, its key the time (`2026-W47` for one a week,
`2026-11-16` for one a day, `2026-11-16T14:30` for more often). With `prepare`, Handler first
calls that route as the owner, with no start token (no `runJob` there) and no body; do not call
`nudge()` from it. It answers what to send (`PreparedNudge`):

- `{title, body?, fields?, key?}`: that nudge (`fields` fills its action's form; no `key`: the
  time's), or `[{title, key, ...}, ...]`: several of this name (one per question), each with its
  own key, at most 10;
- `204`: none this time (nothing to ask today).

Anything else (an error, no answer in 5 minutes, a bad answer) sends nothing, is written in the
app's log and told in the person's inbox, and is not tried again before the next time: keep it
quick and test it.

Left open, one time's nudge stays beside the next time's (a different key). When the next one
makes it pointless (this week's log replaces last week's), set `until = "next"`: at each of its
times, the open ones of that name expire first, whatever their key and whatever `prepare` then
answers (even 204: the time came), and the person sees `ifIgnored` on them. Without it, an open
one stays until done, dismissed or withdrawn: right for questions that stay worth answering.

**From your code**, for a nudge with no `when`: `nudge(name, title, {body, key, fields, until,
person})`, when something happens (a job's `then` found three questions to ask, say):

- `key` (`NudgeKey`) names this one among its name's: sending the same name and key again
  replaces the open one. Letters, digits and `- _ . :` only, 100 at most (refused otherwise):
  make it from ids or dates (`"2026-11-12"`, `"question:42"`), never from text the person wrote.
  Keep the `id` it returns to end it. It returns `null` when the person turned that nudge off on
  your page (nothing sent, not an error): carry on.
- `fields` fills the action's form in beforehand (a job's draft): the person corrects and sends,
  or speaks and Handler fills it in. Fields the form does not have are dropped.
- `until` (an ISO time with its offset): it expires then if still open, and `ifIgnored` is shown.
- It is **done** when its action succeeds from it (`ok` or `attention`): nothing to do in your
  code. Done another way (the person did it in the app's page)? `nudgeDone(id)`. No longer
  needed? `withdrawNudge(id)`.
- **By its name and key**, when your code never got its id (one Handler sent at its `when`:
  `prepare` gets no id back): `nudgeDone({ name, key })`, `withdrawNudge({ name, key })` end the
  open ones of that name and key, whoever they went to, and return their ids (`[]` when none is
  open: not an error). The person answers question 42 on your page: `nudgeDone({ name: "asked",
  key: "question:42" })`. Keep the id when you have it (a nudge your code sent), and make keys
  that name one thing each.
- **Which nudge an answer is for:** a route doing an action sent from a nudge's form gets
  `X-HANDLER-Nudge: <id>; key=<key>`; `answeredNudge(req)` gives `{id, key}`, or `null` when the
  action was not done from a nudge. Find the question you asked by its key, never by its text.
  An action done by a job gets nothing more: the job gets the form's fields only.
- An action's nudge goes to the owner only; a page's may go to a person the app is shared with,
  and opens it with `?nudge=<id>` added: pass it to your backend to call `nudgeDone(id)`.
- Nudges your code sends count with notifications: at most 30 an hour. Never choose how the
  person is alerted nor how often after: the reminders are Handler's (`remind` is the default the
  person tones).

## Other things it can do: notifications, files, "later"

```toml
[needs]
notify = true                     # server/handler.ts: notify(title, {body, person})

[needs.files.notes]               # server/handler.ts: files().notes, the folder the person gives
description = "Your notes"        # what the person reads when they choose it
mode = "ro"                       # or "rw"

[routes]
"POST /api/checkin" = "queued"      # from a phone while the computer is off: runs when it is back
```

- **Notifications** go to the computer and, content-free, to the person's phones: short title,
  optional body, no secrets. At most 30 an hour. `person` is `owner` (default) or a person the
  app is shared with.
- **Files** are the person's: a folder (or a file) they choose at install for each
  `[needs.files.<name>]`, mounted at the same path, read-only unless `mode = "rw"`. Never write a
  path in the app: the code reads `files().<name>`. `description` says what it is for, in the
  person's words ("Where your tasks are kept"). Handler never gives keys nor its own folders.
- **History, kept by Handler:** a folder given `rw` gets the history notes folders have: each
  change kept every few minutes, named after the app and its jobs that could write it, with
  **Undo** on the app's page. Its own `.git` is read-only to the app and its jobs (a folder whose
  `.git` is a link or a file is refused). So never run `git` there, and never ask the person to
  keep their data in git "to be safe": Handler does it. The code reads that history, read only
  (`history("tasks")`: the last changes, newest first, each with who could write then and its
  files; `historyChange("tasks", id)`: one change's files with their lines), to show "what
  changed" on its page; Undo stays on the app's page in Handler: link there, never rebuild it.
- **Ask for a folder, not a single file**, even when the app uses one file in it (`agenda.md`
  in "Where your agenda is kept"). Given one file, the app gets that file alone: an editor that
  saves by replacing the file leaves the app on the old one until it restarts, nothing can be
  added beside it (no temporary file, no SQLite journal), and a file in `rw` must be written in
  place (`Bun.write(path, text)`), never by renaming a new one over it. Never give an app's
  database as a file need: it lives in `HANDLER_APP_DATA`.
- **Something else at a time** (every morning, every 30 minutes) that is no nudge nor job: write
  the route (`POST /api/cron/morning`) and tell the person to add an automation that calls it
  (`run = { app = "<the app's name>", call = "POST /api/cron/morning" }`, `when` as above). It is
  called as the owner (header `X-HANDLER-Automation`: its name) with no start token; it must be
  quick-ish (5 min at most) and safe to run twice.
- **Queued routes** are for actions a phone may send while the computer is off (a check-in, a
  note): the phone answers 202 `{queued: true}` at once, Handler runs the call later (up to 7 days).
  They get an `Idempotency-Key` header: store it and ignore a second call with the same key.
  Show the person that it was saved for later (a 202 from `api()`).

## A folder shared with its jobs

The app and its jobs work on the same data: one folder the person gives, read-write for the app
(`[needs.files.tasks] mode = "rw"`), where a job works (`files = { tasks = "write" }`, `worksIn =
["tasks"]`). It is the same folder on disk, no copy: what the person changes in the app is what
the job reads at its next run, and what the job writes is on the app's next screen.

```toml
[needs.files.tasks]
description = "Where your tasks are kept"
mode = "rw"
init = ["tasks/README.md"]        # files of the app's folder copied into the one given (by
                                  # their name), when it has none of that name yet
```

- `init`'s paths are relative to the app's folder: the one you build it in (its source), else
  its installed version's. Keep each folder's files in a folder of the app's named after its
  need: `tasks/README.md` for `[needs.files.tasks]`. Each is copied by its file name alone, at
  the top of the folder the person gives, when the person gives it (`tasks/README.md` becomes
  `<their folder>/README.md`); a file already there is never replaced. A path that does not
  exist is skipped, one leading out of the app's folder (a link) is refused.

- Keep the data in files both can read: JSON (one file per kind of thing, `tasks.json`), JSON
  Lines for a log that grows, or structured markdown (below) for what the person also reads and
  edits. Write down their format in a `README.md` (copied in by `init`) and say in the job's
  instructions to follow it. The app must work on an empty folder: no file yet means nothing yet.
- The backend may write while a job writes (only jobs take turns): read the file again just
  before writing, change it, then write it whole to a temporary file in the same folder and
  rename it over the old one. Never keep the file's content in memory between requests.
- Simple edits (done, postponed, deleted) are the app's code, with no model; leave judgment to
  the jobs.

## Documents in structured markdown

When the person's data is notes they also read and edit by hand (a CV, a reading log,
decisions), keep it in **structured markdown** (SMD): a plain markdown file with a known shape, a
frontmatter naming its schema (`schema: cv@1`), a `# Title`, one `## ` heading per item with
`field: value` lines and `### ` sections. Never parse or write that markdown yourself: Handler
does it for the app's code, and gives the app's jobs the same tool the person's agents use.

```toml
schemas = ["cv@1"]                # its formats: schemas/cv@1.schema.json, each one there

[needs.files.cv]
description = "Where your CV is kept"
mode = "rw"                       # to write; "ro" only reads and checks

[jobs.enhance]                    # a job reading or writing those documents names them too:
files = { cv = "write" }          # it gets the `handler-smd` command and its skill
schemas = ["cv@1"]
```

```json
{
  "$id": "cv@1",
  "title": "CV",
  "description": "Roles, one item each.",
  "item": {
    "description": "One role.",
    "fields": {
      "company": {"type": "string", "missing": "error", "description": "Who it was for."},
      "start": {"type": "date", "missing": "warning", "description": "When it began."},
      "skills": {"type": "list", "of": "string", "missing": "none", "description": "What it used."}
    },
    "sections": {
      "done": {"heading": "What I did", "missing": "warning", "description": "One bullet each."}
    }
  }
}
```

- A field's `type`: `string`, `date`, `datetime`, `enum` (with `values`), `list` (with `of`),
  `ref` (a link to `other.md#item-slug`); field and section keys in snake_case; `missing`:
  `error`, `warning`, `info` or `none` (optional). A schema may `extends` another of
  `schemas/` (one level). An `$id` is `name@version`: change a schema in a way documents already
  written break, and it is a new version (`cv@2`).
- `schemas/` holds exactly the schemas `schemas` lists, else the deploy fails. At install they
  join the person's Library; one of the same `$id` there that differs refuses the install, said:
  never reuse an `$id` for another shape.
- The code, with the paths of `files()`:

```ts
const path = `${files().cv}/cv.md`;
const { document, diagnostics } = await smdParse(path);   // each item and section with its line
document!.items[0].sections.done.content += "\n- Led the migration";
const problems = await smdWrite(path, document!);         // written, then checked
// smdCheck(files().cv): the problems of every .md of the folder
```

- `smdWrite` writes the canonical form: the first write of a file written by hand may change its
  blank lines, never its words; its frontmatter stays exactly as the person wrote it while its
  fields are the same (else, if it holds a comment, `smdWrite` throws and nothing is written).
  A document is written even with problems: show them (`diagnostics`: file, line, message).
- Only in the folders the person gave, `smdWrite` only in one given `mode = "rw"`; never through
  a link. A document sent to `smdWrite` is 1 MiB of JSON at most.

## Calling a model from the backend

Only when the person asks for a particular model service (otherwise: a job). Handler only opens
the way:

```toml
[needs]
egress = ["host.containers.internal:3000"]   # a model server on the person's computer
secrets = ["LLM_API_KEY"]                     # its value is entered by the person in handler
```

- `host.containers.internal:<port>` is the person's own computer (llama.cpp, Ollama, an
  OpenAI-compatible `/v1/chat/completions`); a server on the local network is
  `192.168.1.20:11434`; a public API `api.example.com:443`. Ask the person which one; never pick a
  paid API on your own.
- Read keys with `process.env.LLM_API_KEY`. Secret names are capitals, digits and `_`; not
  `HANDLER_…`, `BUN_…`, `PATH`, `HOME` or the proxy variables. Never write a key anywhere: not in
  the folder, not in a log line. Put the model's URL and name in one place (`server/config.ts`).
- A model is slow: show the UI as busy, handle errors (host down, 401, timeout) with a readable
  message. Tests get **no** secrets and no network: test the parsing of answers and the prompts,
  with the model call replaced by a function passed in.

## An app written for an earlier Handler

Apps once needed agents set up for them. Handler now refuses `[needs.agents.*]`, an action's
`agent = …` and an automation's `run = { agent }`, and no longer reads `agent/`. To bring one up
to date: each agents need becomes a `[jobs.<name>]` (same name): `agent/instructions.md` →
`jobs/<name>.md`; `interface.json`'s `fields` and `result` → the job's; `worksIn` → `files = {
<need> = "write" }` (or `"read"`) and `worksIn = ["<need>"]`; the agent's `egress` → the job's;
`runAgent` → `runJob`; `agent = "x"` → `job = "x"`; `run = { agent = "x" }` → `run = { job = "x"
}`; delete `agent/`. A suggested automation is now turned on at install unless marked `optional
= true`, while one running an agent was off until the person turned it on: mark those
`optional = true` to keep that. A file `agent/` held for a folder's `init` (its format's
`README.md`) moves to `<need>/README.md`, `init` naming that path. Raise `version`. The person keeps their data, and when the app was installed
with an agent, its Who works is already that agent's program, account and model.

## Dates, money, text

- Store dates as ISO 8601 strings in UTC (`strftime('%Y-%m-%dT%H:%M:%SZ','now')`), show them
  with `toLocaleString()`.
- Store money as integer cents; compute in cents; format with `Intl.NumberFormat`.
- The person may write in any language: keep the UI's words short and plain, match the
  language they asked in.
