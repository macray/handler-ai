# UI-UX

Directives for anything a person sees: the web UI (`packages/web-ui`), the phone client
(`packages/remote-client`), session rendering (`packages/acp-view`), CLI output and help, and the
user docs (`docs/user/`). Read before a frontend task; keep it short, add a rule when one is decided.

## Words

- One name per concept, the same in the UI, CLI flags, files, API values and docs; the word users
  see wins. No users yet and no shims (CLAUDE.md), so each rename is one commit.
- Three tiers of words:
  - **Core** (README, everywhere in the UI): model access, project, agent, session, safety preset.
  - **When you need it** (shown where it is used): addon and its configurations, skill, knowledge
    folder, remote device, app, automation (*when this happens, run that*), how an agent is used (*Chat*, *Brief*, *Job*) and a job's runs.
  - **Internals** (contributor docs only): harness, ACP, toolbox, sandbox spec, attachment, origin,
    work folder. In the UI a harness is shown by its product name ("Claude Code"); work folders
    appear inline where a folder is refused.
- Renames decided (2026-10-04), in this order, one commit each: addon "configuration" / `binding`
  → **connection** ("shopify: dev-shop", `--connect`, `~/.config/handler-ai/connections/`; an agent's
  live sandboxes, today `connections`, become `sandboxes` first); confinement `nested` / "Runs
  containers" → **`containers`**; `scope` → **`folder`**; "ad-hoc agent" → **agent outside
  projects**; then a test next to `tests/architecture/` that fails when a retired word appears in
  user-visible text (web UI strings, CLI help, `docs/user/`, `README.md`). Done: the safety presets
  (Locked down / Guarded / Open), `filtered` / `log-only`, "Learn hosts"; project context →
  **area** (2026-10-15: "context" read as a model's context window).
- `docs/user/concepts.md`'s "Words that are easy to mix up" table is the glossary. Concepts are
  named the same in it and in `docs/dev/model.md` (the full rules, for contributors).
- Plain sentences: say what happens ("It will never ask before acting"), not internal terms
  (contract sections, ACP, toolbox) in the user's path.

## What the app can do is visible

- No option hidden from the UI or reachable only by editing a file (CLAUDE.md). An option that
  weakens the sandbox is shown with a warning, and a save that widens what an agent may do is
  confirmed (D.8).
- A choice that matters is never made silently for the person: with two or more accounts or
  providers, the model picker asks instead of picking one.
- Exception (2026-10-08): starting a session with an account or provider its project's area
  does not allow is CLI only (`--anyway`, acknowledged by typing `yes`); the web UI says it is
  hidden and how to do it from the CLI. A guard against mistakes, kept out of the click path.

## Low friction first

Guidelines (2026-10-08), not fixed rules: changing one is a deliberate decision, said here.

- **Boundaries only where they protect something.** Simplicity and low friction are goals: every
  wall between things makes the app more cumbersome and closes uses. A boundary is kept where
  crossing it does harm: the sandbox, and which account works for whom (a work account never on a
  personal project). What you know and how you work is not walled: knowledge folders, addon
  configurations and skills are shared by every area, and a work agent may use a personal one
  (a stand-up prep reading your personal calendar to tell the team you are off tomorrow). The
  agent's settings and its permissions say what it gets; no workspace hides it.
- **Pick a goal, don't describe it.** People come to Handler with a goal already in mind: they select
  it (a pinned agent, a project's agent), they are not asked to put it into words for Handler to
  route. A free-text "what do you want to do?" entry is another way of interacting (like voice),
  not the main path.

## Vendors' terms (subscriptions)

Handler runs the vendors' own harnesses on the person's own subscriptions. The UI helps them stay
within those terms. Anthropic's, read 2026-10-05: signing in to the unmodified Claude Code with
one's own subscription is allowed, including where a platform hosts Claude Code, through
Anthropic's own flow; a third-party product offering that login, or storing its tokens, is not,
unless approved; plan limits assume ordinary, individual usage. So:

- **The sign-in is the vendor's and the person's.** Handler never runs a token sign-in nor reads its
  output: the account screen shows the command the person runs (`claude setup-token`) and says it
  is Claude Code's own sign-in, with their subscription, for their own use.
- **For your own use.** Wherever an account (a subscription) is created or chosen, the UI says it
  is for the person's own use; it never suggests sharing one.
- **Unattended means an API key.** Subscription plans assume ordinary, individual use: an agent
  that runs on its own (a job, a scheduled or triggered run, a background
  agent) shows that an API key (a provider) is recommended when it runs on an account.
  A Claude subscription is for interactive use only: sessions the person starts and follows.
  An automation's agent run follows its login's verdict (2026-10-09, contracts I.7), one per
  vendor since their terms differ: `allowed`, `check-terms` (a warning: check your plan's terms,
  an API key is recommended, with the terms' link) or `refused` (it does not run). The accounts
  screen shows each account's.
- **Their names are theirs.** The UI and docs may say in plain text that Handler "runs Claude Code";
  Handler's own names (its product, features, buttons, suggested config names, logos) never use
  "Claude Code", "Anthropic" or another vendor's name or logo. Name things after the person's
  account (`claude-perso`) or after Handler.
- The README and the UI do not make "use your subscription" a headline: model access is "an API
  key, a local model, or your own subscription for your own use".

## Building it

- Svelte 5 + TypeScript, shadcn-svelte components, Tailwind; a light theme with one orange accent.
  Reuse the existing components before writing new ones.
- The look (2026-10-15): warm neutrals (stone greys, not blue-greys) around the one accent, in
  the light and dark themes and the terminal. Prose in Inter (optical sizes: page titles get its
  display cut); facts in the mono face, JetBrains Mono, as in the terminal: paths, counts, times,
  agent and model names (`.fact`), and a section's name, lowercase (`.section-label`, the
  sidebar's groups). Concentric radii (cards 10px, controls 8px), soft layered
  shadows (`shadow-panel`, `shadow-lift` for what lifts under the pointer).
- Motion (2026-10-15): something moves only when a state or a place changes, so the motion says
  what changed: the page coming in, a session
  arriving in a list, its status dot popping and a "needs you" ring, what the agent adds to the
  timeline, a permission request rising, a `<details>` unfolding. One curve (`--ease`), three
  lengths (`--dur-1/2/3`), only `transform` and `opacity` (and heights unfolding); nothing moves
  while you type, nothing loops but a status that waits for you or works; none under
  `prefers-reduced-motion`. No motion for decoration.
- Sheets (2026-10-15): what opens over a session on a narrow screen (≤ 900px: its Files,
  Network… panels; on the phone, a permission request) is a sheet from the bottom with a handle
  (`acp-view/lib/sheet.ts`): dragged down it goes (a permission: down to a "Needs you" bar, a tap
  brings it back), dragged up it grows; the session recedes behind it, still there. On a wide
  screen those panels stay beside the session (you watch the agent while reading them), never over
  it.
- Settings pages (2026-10-15, Remote and Model access): a list shows, a dialog changes. Things
  of one kind are one card with divided rows (an icon, the name and its tags, its state, a
  `.fact` line of what it is; one main action and Edit), never a grid of cards with forms
  opening inside. What uses a thing (agents, sessions) is said in its Edit dialog and before it is
  deleted, not on its row; a warning on a row is a small amber badge whose tooltip says it in
  full. Making, logging in and editing happen in a dialog (`Dialog.svelte`) with labelled fields;
  Delete is in the Edit dialog. Sections are apart (`space-y-10` or more), each with its heading,
  a sentence, and its Add on the right. An empty section says so in a dashed card. A page-wide
  status is shown only when it asks for something (finish one, fix this computer, the next step).
- The frame (2026-10-15): the menu on the left never moves, and every page sits flush against it
  (one edge, no card around the page). Its foot lists the open sessions, those that ask or replied
  under "waiting for you" (in amber), then the others under "open" (2026-10-19; one "open
  sessions" heading when none waits); the one shown unfolds into its card (`lib/sessioncard.svelte.ts`), only what the row
  and the session's caption do not say (2026-10-16): what it runs on (the program, the account or
  provider by its name, the model), then its actions as icons, the sandbox one of them (a shield,
  amber when weakened, its words in the tooltip; a click opens its network). No folder line: it
  is the project's. The session itself is one dark room: a
  caption line (its title, its project and agent, its status), the terminal, and what the card
  opens (Files, Network…) beside it, dark too, divided by a line. Nothing about the sandbox in the
  terminal's own bar. The menu hidden (a narrow window, or closed), a tap on the caption opens the
  card as a panel. Settings → Appearance: the menu liquid (translucent over a calm backdrop,
  the default) or flat (one colour).
- The Projects page and the menu (2026-10-16): every project by name, so each keeps its place,
  one card of rows (its icon tinted by area, its name and area tag, its description or its
  folder, what its sessions do only when they do something: needs you, working, open; never the
  sessions themselves, the menu's foot lists them), an area switch (All, each area in use, No
  area) and a small filter field (no shortcut). Each row has a pin: the menu lists the pinned
  projects only (under their area's name, by name in each, then Other folders; no "Pinned"
  label), and a new project is pinned, so the pin is learnt on this page. Unpinning says the project stays on the page, with
  Undo. With no project yet, the first steps side by side, the next one ringed with the page's
  only primary button, the done ones saying what is ready.
- The menu (2026-10-19): a project's icon is a plain folder (not a git sign: Handler is not only
  for developers), tinted by its area. A place (a project, Other folders) shows one dot for its
  sessions, the most urgent winning (needs you, replied, working, running; nothing when none
  runs), or how many need you when more than one does; never a bare count of sessions, which the
  open sessions list says. One still highlight for the current page, no motion. A count in a
  filled pill is something waiting for you (the inbox's unread, in the accent). The menu is the
  same on every page: Settings list their sections in the page, left of the section (a dropdown
  in a narrow window), Settings lit at the menu's foot. Remote has no row: the menu says it only
  while it is used (a phone on a shared session; a line when the gateway is unreachable or
  refused while a session is shared), the rest is in Settings → Remote.
- A project's page (2026-10-15): its facts on one line (folder, caches, skills), what waits for
  you whichever agent is chosen, then its agents on the left and the chosen one's workspace beside
  them (the route says which: `?agent=`, else the default). Every agent's workspace reads the same
  way: who it is (goal, models, preset, schedule, Edit), how it starts, in one card at the top (a
  request for a chat; its form for a brief or a job), then what it did. The start
  card is a dark console (`.term-surface`, the colours of the session it opens), for every kind.
- Other folders (2026-10-17, named *Outside projects* until 2026-10-20) is the place of the
  agents of no project but Chat's, as a project is
  theirs: always in the menu, right after the pinned projects (no line, no pin: it is never
  hidden), and under the projects on the Projects page, in a card of its own; no "All projects"
  link (the Projects entry is that page). Its page reads as a project's (the same agent list and
  workspace, `AgentPick.svelte`, `AgentWorkspace.svelte`) without what only a project has (its
  facts, Settings), its agents in three groups: yours; for Handler and your apps (each saying
  for what, a grey tag: "Skill reviewer", "Planner", "writes Planner"); from the command line,
  folded, called by their folder. An agent's address (`#/agents/:id`) opens its place with it
  chosen (Chat, for someone you talk to).
- Chat (2026-10-20) is Handler's own place for who you talk to, listed first under *Apps* in the
  menu (and the first card of the Apps page), though it is no app (nothing installed; its agents'
  home is `chat`, D.1): *Who you talk to* as tiles (name, what they are for, their model; *Someone
  new*, a short dialog: name, how they behave, who answers, model), the chosen one's workspace
  below (the console, their conversations). Who is in Chat is the agents whose home is Chat (made there: no folder,
  no form). One Chat with several people to talk to, not one app each: Apps stays
  the list of what works for you. Handler's helpers (the agents given for its needs) are chosen where they are used (Skills → *Agents for
  skills*; Apps → *New app*), never a kind of agent on a page of their own.
- How an agent is used (2026-10-16) is the agent editor's first question, three cards on one
  scale of how much you stay: *Chat* (you talk with it), *Brief* (a form to start, then you work
  on it together), *Job* (a form; it works alone and returns a result). Each card's sentence says
  the same three things in the same order: how it starts, who is there, how it ends. The choice
  changes only the sections that differ (the form, a job's result and time limit, a job's
  permissions and automations), and switching keeps what was typed (a brief's form becomes the
  job's); a switch that drops a saved brief or result says so before saving. Below it, each
  group needs only what is above it (2026-10-19): what it is for (its name), then the form and
  a job's result, then its instructions, which name the form's fields and say what the result
  is for: never a field to fill in before what it refers to (the agent receives them in the
  other order, the instructions first; the editor follows how you think, not the message). The
  "in → out" strip sums a saved agent up on its page, not in its editor. A session started
  from a form shows the form filled in where the first turn would be, never the JSON the agent
  reads. "Run" is a job's word; a brief's button is *Start*. Saved, an agent says how it is used
  with the same word and the editor card's icon everywhere it is shown (`UseChip.svelte`: its
  chip beside its name, its icon and "Chat · …" in a list), never "runs unattended" or "a brief".
  What it did is a timeline by day (`Timeline.svelte`): the time, a dot on the rail, the title
  and its note, what it ran on; open sessions to Open, ended ones to Resume, runs with their
  result. No agent dropdown: the list chooses.
- Agents files (2026-10-21, were blueprints; the word is gone, 2026-10-22). *Export agents* is
  on a project's header: its agents ticked, each saying what of yours it leaves out (from the
  server's dry run) and what is kept; a download. *Add agents from a file* sits under the
  project's agent list, beside *Add an agent*. Setting them up is one page, as an install: where,
  each agent asking only what it needs, what comes with it, and what it will be allowed to do beside
  the button (pressing it confirms that). The set-up of Handler's helpers is that page too, and so is an app's install page (where it keeps
  its data, its agents, secrets, what runs by itself, who opens it; Install ends on its project).
- Sources and Discover (2026-10-22): *Discover*, first in the menu's library, is the whole shelf:
  by kind (Apps, Agents, Tools for your agents), a search, a kind switch and a source filter;
  each card says where it comes from (*from Handler* in the accent, a source you added in grey)
  and up to two notes from its manifest (amber when it weakens the sandbox); its name opens its
  page (README, what it may do and needs, a trust line: reviewed by Handler, or amber for a
  source you added), its button goes to its kind's own install page (an addon's preview opens on
  Library → Addons). Where a kind is used, a short list stays (the Apps page's *Get more*: three;
  the addon installer; *Add agents from a source*), ending in *See all in Discover*. Settings →
  Sources lists the sources (one card of rows; Read again, Remove for one added). Adding one says, in amber, that Handler does not check what is in it,
  and Add stays grey until the person ticks that they trust it. "Source" is a *when you need it*
  word.
- An app's page (2026-10-21): Open and the top bar's *Change it* and *Export* first; then *What
  you gave it*, always on top: each folder, agent and secret a row with the app's sentence, the
  value in bold and **Change…** (a dialog changes it; never an empty field under a value that is
  set), "all set" when nothing is missing, a missing one amber with the page's primary button
  (Open stays grey while the app cannot start). Then its actions (*What you can ask it*), what runs by itself, and *Under
  the hood* folded (its code and state, said once in words: "asleep, starts when opened"; the
  version before it with *Go back to…*; its parts; its log, unfolding in place). **Remove** is
  the last card, saying what goes and what stays, its confirmation a dialog. Beside them what it
  may touch and the phones it opens on. The manifest's ids (a need's name) are not shown.
- A project's settings (2026-10-16) are a page of rows (`SettingRow.svelte`): each setting its
  label and a sentence on the left, its control on the right, a group's rows in one card. An
  existing project's changed controls are ringed in the accent and counted on a bar at the foot
  (Undo, Save), shown only when something changed; Delete comes last, saying what goes.
- What a session or a run starts with is a sentence (2026-10-15, 2026-10-19): "in [program] on
  [account or provider] with [model]", each list short and naming one thing (the programs; the
  accounts and providers that run the chosen one, each once by its name, the agent's own first;
  that one's models), never one line per provider × program, and no "its default" label. The
  model list puts the agent's own model first, already chosen, grouped under its name ("CV
  filler's model"), then the provider's others ("other llamacpp models"). Another model picked
  is for that session only and is not said again beside the sentence: the list shows whose is
  whose, picking the agent's again is the way back, and the agent's settings are where its model
  changes. No area tag in the sentence: every account and provider offered is made for the
  area; those not made for it, the agent's own included, are one folded line.
- A session says what it is doing, truly (2026-10-15): while it starts, its real steps (its
  sandbox starting or reached, then its conversation), with the time taken. Never a progress
  that is not measured.
- Areas (Work, Personal, a client) are the one exception to the single accent
  (2026-10-08): each area has a colour the person picks from a fixed palette that never uses
  orange, green, amber or red (they already mean the accent, ok, warning, danger). A project or
  an agent shows its icon tinted in that colour and a tag in that colour with the area's name
  (pinned agents, project cards; the menu names each area once instead, as the heading of its
  projects, and its open sessions say the project in plain text); the session's caption and the model
  dropdown's accounts and providers show the tag (`any` in grey). Never a dot alone, a stripe or a
  tinted background. Light and dark values for each colour.
- Contrast (2026-10-08): text meets WCAG AA (4.5:1; the accent is `#c2410c` so white on it and
  it as text pass), form fields' borders 3:1, no control text under 12px; a disabled button is
  grey, not a faded accent. A warning ("not set up", "needs you") is amber, never the accent.
- No side stripe on a rounded box (2026-10-08): a card, a list item, a callout with rounded
  corners never gets a thicker or coloured border on one side (the left bar bending round the
  corners looks broken and machine-made). Such a box has the same border all around; what it is,
  is said by its title, a badge or its background. A plain bar on a square, borderless block is
  fine (the session's "your message" lines, a quote).
- The session's terminal (2026-10-13) keeps the one accent: the prompt, focus and Send are orange,
  green only says a step succeeded, amber only that something waits or weakens the sandbox (the
  Auto-approve mode chip); inline code is neutral. Paths are shown relative to the session's
  folder, each once; a step says in one line what it gave back (a failure's first line). People's
  words (your messages, the agent's) are in the text face, steps, code and diffs in the mono one.
- No single-key shortcuts on a page (2026-10-08) (`y`/`n` to answer…): a choice is a click on a
  labelled button.
- Touch screens (2026-10-13, `pointer: coarse`; a phone is often in a pocket, screen on): Return
  starts a new line and the Send button sends (no Shift+Enter there); stopping the agent takes a
  second tap; the buttons that act on the agent (Interrupt, a permission's answers) take no tap for
  a moment after they appear or the screen comes back on (`acp-view/lib/touch.svelte.ts`), and a
  fill sweeping across a permission's answers shows that moment (they are live when it ends); tap
  targets are about 40px high; no keyboard hints. How a turn ended, when not normally, is said at
  the end of the timeline, also to a client that was away.
- Every control an end-to-end test drives has a `data-testid`; `tests/e2e/test_web_ui.py` covers
  the main flows (the Playwright image runs them).
- `bun run check` (svelte-check, warnings are errors) and `(cd packages/web-ui && bun run test)`
  pass; `scripts/build-web-ui.sh --quick` before the e2e tests.
