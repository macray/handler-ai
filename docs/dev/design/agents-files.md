# Agents files, and the definitions of Handler's needs

Agents written so they can be set up again, as a whole: a project's agents exported as one file
and set up in another project. Normative: [contracts §D.23](../contracts.md) (and D.18 for
Handler's needs). The UI says *agents file*, *Export agents*, *Add agents from a file*; the code
says the same (`agents_files.py`, `AgentsFile`, `/v1/agents-files`).

## Why

What a person builds in Handler (an agent's instructions, its form and result, the checks that
say it works, the skills it picks) is worth keeping beyond the folder it was made in: to set the
same agents up for another client, another shop, after a change, and later to share them. An
agents file is that, without what is the person's own, so that it sets up anywhere.

2026-10-21: with apps the unit you install for what works for you (an app's code kept by Handler,
H.15), what remained of the earlier *blueprints* is agents that work with you in a project. Two
things to share, told apart by the question asked: an app (*something done for me*) or agents
(*help on this folder*). So blueprints stopped being a place of their own (a Blueprints page,
*Save as blueprint*, versions kept by Handler) and became a file.

2026-10-22: the word *blueprint* is gone from the code too. It named two things that shared a
format and nothing else: the agents file, and the agent Handler ships for each of its own
features that need one. The second is now **one of Handler's needs** (`HandlerNeed`, D.18): a
need, as an app's (H.2), with its definition beside it; the UI calls the agent given a *helper*.

## Choices

- **A file, not a store.** An export is made on the fly and downloaded; Handler keeps no copy (a
  store of "yours" was a second place for the same agents, and a page to keep tidy). Reading a
  file keeps it only until its agents are set up (the set-up page reads it by name, then
  forgets it). Exported from where the agents live, a project, not from one agent: a single
  agent is a file with one agent; the dialog ticks which.
- **One format for every definition.** An agents file's agents are agent definitions, the format
  an app ships for its needs (`agent.toml`, `instructions.md`, `interface.json`, `skills/`),
  plus `checks.json`; Handler's needs ship the same definition, beside a `need.toml`. There is no
  second kind of "built-in agent".
- **Handler's needs apart from agents files.** Which agent Handler uses for one of its features
  (the skill review) is given as an app's need is; the need ships the definition that sets one
  up. An agents file knows nothing of Handler's features, and an imported file never clashes
  with one of their names: they are not in one namespace.
- **What is yours is left out by rules.** Models (accounts, providers), the folder, which addon
  configuration and knowledge folder were given: each becomes what it needs ("a configuration of
  shopify", "a knowledge folder: recipes"), asked at set-up. The export dialog shows each
  replacement before exporting (a dry run). Free text (instructions, a check's input and answer)
  is kept as written: the dialog says to read it before giving the file away.
- **The origin stays.** An agent set up from one keeps `{kind: "agents-file", name, version,
  agent}` (version 1 for an export), one set up for a need of Handler's `{kind: "handler-need",
  name, version}`, so what it came from is known.
- **No setting-up endpoint.** Setting one up is creating its agents through the routes that
  already make agents and projects, with the origin: one path for the rules an agent must pass.
  The origin brings the agent's skills to the library first and its checks once it exists. A new
  project is one request; agents added to an existing project are several (if one is refused,
  the page says which were made).
- **Nothing follows afterwards.** The agents are the person's: the file changes nothing in them.
- **Imported files are not trusted.** A file from elsewhere is read with an app file's checks
  (paths, links, size), and its set-up page says *Not from Handler* above what each agent will be
  allowed to do.
- **Set it up is one page**, an install: where, each agent asking only what it needs, what
  comes with it, what it will be allowed to do beside the button. The agents for Handler's needs
  are set up on that page too (`#/helpers/<need>/set-up`).

## Not built yet

Exporting agents outside projects (Other folders); discovering agents files (Discover's places,
with apps); updating what was set up from a file while keeping the person's changes; the content
of a project's folder in a file.
