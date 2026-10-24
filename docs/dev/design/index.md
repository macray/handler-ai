# Design notes

Why each feature is built the way it is: its use cases, the choices made and the alternatives
left out, its limits, and what is not built yet (the last section of each note). The formats and
guarantees they rely on are normative in [`contracts.md`](../contracts.md); the big picture is
[`architecture.md`](../architecture.md), every concept and its rules [`model.md`](../model.md).
A new feature gets its note here, and its user page in `docs/user/`.

| Note | What it designs | Status | Contract | For users |
|---|---|---|---|---|
| [Configuration](configuration.md) | accounts, providers, agents, work folders: who owns which setting, and why | built | D, E | [where things are kept](../../user/configuration.md) |
| [Addons](addons.md) | tools for one kind of system in their own image, bindings, how credentials reach a tool | built; gateway endpoints, audit log, credential files not yet | G | [addons](../../user/addons.md) |
| [Browser](browser.md) | an agent's browser (Playwright MCP) in the sandbox, its window on your desktop, logins | built; hosted MCP servers not yet | A.6, G.1 | [a browser for your agents](../../user/browser.md) |
| [Knowledge](knowledge.md) | read-only folders of notes per agent | built | D.5 | [knowledge folders](../../user/knowledge.md) |
| [Apps](apps.md) | small web apps an agent writes and you deploy: runtime, origins, phone, queued calls, notifications | built (runs of your agents too, H.11); overlay not yet | H | [apps](../../user/apps.md) |
| [Remote control](remote.md) | a phone reaching sessions through an untrusted gateway: pairing, envelopes, trust model | built; client off the gateway, session pushes not yet | D.7, F.7 | [your phone](../../user/phone.md) |
| [Checks](checks.md) | a job's runs kept with their right answer, run again when asked; improving its instructions until they pass | built; a judge, schedules not yet | D.20, D.21 | [concepts](../../user/concepts.md) |
| [Agents files](agents-files.md) | a project's agents exported without what is yours, and set up in another project on one page; the definitions of Handler's needs | built; updates, Discover not yet | D.18, D.23 | [concepts](../../user/concepts.md), [`handler project`](../../user/cli/project.md) |
| [Sources](sources.md) | git repositories offering apps, agents and addons: Handler's official one and those you add, read without running anything | built; private repositories, signing, Discover not yet | D.26, G.5, H.13 | [sources](../../user/sources.md), [`handler source`](../../user/cli/source.md) |
| [The model alone](model-alone.md) | an agent with no program: one model call a turn, no sandbox, no tools | built; streaming, images not yet | D.18 | [concepts](../../user/concepts.md) |
| [Services](services.md) | capabilities behind a contract (a model, OCR…) that agents, scripts and apps call | proposal; `llm/v1` for automations built | I.5 | — |
