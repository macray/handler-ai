---
name: miniapp
description: Write or change a Handler mini app — a small personal web app (Svelte UI + Deno backend + SQLite) that the person deploys to Handler and opens with one click or from their phone. Use when asked to build a small tool, dashboard, tracker, calculator or form "as an app", or to change a folder that has an app.toml.
---

# Mini apps

A mini app is a folder that Handler installs and runs for the person: a **Svelte UI** (built to static
files), a **Deno backend** (TypeScript) and a **SQLite** database. One language, one runtime
(Deno, installed here as `deno`), no other stack. The `template/` folder next to this file is a
complete, working app (short notes): start from it.

You write and test the app. **You never deploy it**: the person does, from Handler's Apps page (or
`handler app deploy`), after you are done.

## Layout

```
app.toml                 the manifest (handler.miniapp/v1): name, version, description, needs
server/main.ts           backend entry: serves on the socket handler gives (HANDLER_APP_SOCKET)
server/routes.ts         the routes, all under /api/; GET /api/health must answer 200
server/db.ts             SQLite + migrations (runs migrations/NNN_*.sql not applied yet)
server/handler.ts        what the backend may ask handler: notify(), files()
server/migrations/       001_init.sql, 002_….sql — never edit one that was deployed: add one
server/*_test.ts         tests: handler runs them before every deploy, a failure stops it
ui/src/                  Svelte 5 UI; ui/src/api.ts is the only way to call the backend
ui/dist/                 the built UI (`deno task build` in ui/): what handler serves
```

Handler installs `app.toml`, the whole `server/` directory and `ui/dist/`. Nothing else.

## Steps

1. `cp -r <this skill's folder>/template <app folder>` (unless the folder is already an app).
2. In `app.toml`: `name` (lowercase letters, digits, `-`; it becomes the address
   `http://<name>.localhost:7430/`), `description`, `version`.
3. Backend: routes in `server/routes.ts`, tables in a new migration, tests next to them.
4. UI: components in `ui/src/`, every backend call through `api()` from `ui/src/api.ts`.
5. Check, in this order, and fix until all pass:
   - `cd server && deno task test`
   - `cd ui && deno task build` (the first build downloads vite and svelte from npm)
   - `cd server && deno check main.ts`
6. Preview if you can: `cd server && deno task dev` (backend on 127.0.0.1:8787) and
   `cd ui && deno task dev` (UI on 127.0.0.1:5173, forwards /api to the backend). With a browser
   tool, open http://127.0.0.1:5173 at phone width (390 × 844) too: the app is also used on
   phones.
7. For a change to an app already deployed: raise `version` in `app.toml` (e.g. 0.1.0 → 0.2.0),
   add migrations rather than changing old ones, rebuild the UI.
8. Tell the person it is ready: "Apps page → Add (this folder) → Deploy", or **Deploy** if the app
   is already registered. Say what changed and whether data changes (migrations).

## Rules (Handler enforces most of them)

- **Backend runtime:** Deno, offline, in a sandbox. It may read its code and read/write only
  `HANDLER_APP_DATA` (the data folder: `app.db` and any files). No network unless `app.toml` lists
  hosts in `[needs] egress = ["host:443"]` — and the person sees that when deploying. It is
  stopped when unused and started on the next request: keep no state in memory that matters.
- **No npm or jsr dependencies in the backend** unless really needed: `node:sqlite`, `Deno.serve`,
  Web APIs and `@std` cover most needs. If you add one, set `"vendor": true` and
  `"nodeModulesDir": "auto"` in `server/deno.json` and run `deno install` there: dependencies
  must be inside `server/`, Handler never downloads anything when it runs the app.
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
- Read keys with `Deno.env.get("LLM_API_KEY")`. Secret names are capitals, digits and `_`; not
  `HANDLER_…`, `DENO_…`, `PATH`, `HOME` or the proxy variables. Never write a key anywhere: not in the
  folder, not in a log line.
- Put the model's URL and name in one place (`server/config.ts`), so the person can change them.
- A model is slow: show the UI as busy while waiting, and handle errors (host down, 401, timeout)
  with a readable message.
- Tests get **no** secrets and no network: test the parsing of answers and the prompts you
  build, with the model call replaced by a function passed in.

## Doing things on its own: a time of day, notifications, files, "later"

```toml
[needs]
notify = true                                           # server/handler.ts: notify(title, {body, person})
files = [{ path = "~/notes/agenda.md", mode = "ro" }]   # server/handler.ts: files()[0]

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
- **Files** are the person's, mounted at the same path, read-only unless `mode = "rw"`. Prefer a
  folder to a single file (editors that replace a file on save are only seen through a folder).
  Paths go in `app.toml`; the code reads `files()`. Never keys, never Handler's own folders (Handler
  refuses them).
- **Queued routes** are for actions a phone may send while the computer is off (a check-in, a
  note): the phone answers 202 `{queued: true}` at once, Handler runs the call later (up to 7 days).
  They get an `Idempotency-Key` header: store it and ignore a second call with the same key.
  Show the person that it was saved for later (a 202 from `api()`).

## Dates, money, text

- Store dates as ISO 8601 strings in UTC (`strftime('%Y-%m-%dT%H:%M:%SZ','now')`), show them
  with `toLocaleString()`.
- Store money as integer cents; compute in cents; format with `Intl.NumberFormat`.
- The person may write in any language: keep the UI's words short and plain, match the
  language they asked in.
