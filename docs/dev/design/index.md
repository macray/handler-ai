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
| [Mini apps](miniapps.md) | small web apps an agent writes and you deploy: runtime, origins, phone, queued calls, notifications | built; overlay, `agent.run` not yet | H | [mini apps](../../user/mini-apps.md) |
| [Remote control](remote.md) | a phone reaching sessions through an untrusted gateway: pairing, envelopes, trust model | built; client off the gateway, session pushes not yet | D.7, F.7 | [your phone](../../user/phone.md) |
| [Services](services.md) | capabilities behind a contract (a model, OCR…) that agents, scripts and apps call | proposal; `llm/v1` for automations built | I.5 | — |
