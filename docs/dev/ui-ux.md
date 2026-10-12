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
    folder, remote device, mini app, automation (*when this happens, run that*), agent with an interface and its runs.
  - **Internals** (contributor docs only): harness, ACP, toolbox, sandbox spec, attachment, origin,
    work folder. In the UI a harness is shown by its product name ("Claude Code"); work folders
    appear inline where a folder is refused.
- Renames decided (2026-10-04), in this order, one commit each: addon "configuration" / `binding`
  → **connection** ("shopify: dev-shop", `--connect`, `~/.config/handler-ai/connections/`; an agent's
  live sandboxes, today `connections`, become `sandboxes` first); confinement `nested` / "Runs
  containers" → **`containers`**; `scope` → **`folder`**; "ad-hoc agent" → **agent outside
  projects**; then a test next to `tests/architecture/` that fails when a retired word appears in
  user-visible text (web UI strings, CLI help, `docs/user/`, `README.md`). Done: the safety presets
  (Locked down / Guarded / Open), `filtered` / `log-only`, "Learn hosts".
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
- Exception (2026-10-08): starting a session with an account or provider its project's context
  does not allow is CLI only (`--anyway`, acknowledged by typing `yes`); the web UI says it is
  hidden and how to do it from the CLI. A guard against mistakes, kept out of the click path.

## Low friction first

Guidelines (2026-10-08), not fixed rules: changing one is a deliberate decision, said here.

- **Boundaries only where they protect something.** Simplicity and low friction are goals: every
  wall between things makes the app more cumbersome and closes uses. A boundary is kept where
  crossing it does harm: the sandbox, and which account works for whom (a work account never on a
  personal project). What you know and how you work is not walled: knowledge folders, addon
  configurations and skills are shared by every context, and a work agent may use a personal one
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
  that runs on its own (an agent with an interface, a scheduled or triggered run, a background
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
- Project contexts (Work, Personal, a client) are the one exception to the single accent
  (2026-10-08): each context has a colour the person picks from a fixed palette that never uses
  orange, green, amber or red (they already mean the accent, ok, warning, danger). A project or
  an agent shows its icon tinted in that colour and a tag in that colour with the context's name
  (the sidebar's projects, pinned agents, project cards); the session header and the model
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
- No single-key shortcuts on a page (2026-10-08) (`y`/`n` to answer…): a choice is a click on a
  labelled button.
- Every control an end-to-end test drives has a `data-testid`; `tests/e2e/test_web_ui.py` covers
  the main flows (the Playwright image runs them).
- `bun run check` (svelte-check, warnings are errors) and `(cd packages/web-ui && bun run test)`
  pass; `scripts/build-web-ui.sh --quick` before the e2e tests.
