# web-ui — Svelte client

**Implements:** a client of contracts C (ACP over WebSocket) and D (Control API). Served by `handlerd`
at `/`; opened with `handler ui` (the token travels in the URL fragment, never to the server).
**Depends on:** the generated contract types (`src/lib/contracts.gen.ts` ← `schemas/`), the ACP
TypeScript SDK, `packages/acp-view` (the session view it shares with the remote client). Never
imports Python code, never talks to anything but `handlerd`. A bun workspace member: install from
the repository root (`bun install`).

```
(cd ../.. && bun run gen:types)   # schemas/ → src/lib/contracts.gen.ts (after contract changes; scripts/gen-types.ts)
bun run check       # svelte-check (browser code) + tsc (build scripts)
bun run test        # vitest: session model, run status, projects, sanitizer, router, transport
bun run build       # → dist/, served by handlerd
bun run dev         # hot reload, proxies /v1 to handlerd (HANDLER_URL, default 127.0.0.1:7430)
```

No Node or Bun on the host? `scripts/build-web-ui.sh` builds inside the toolbox image.

| Path | Role |
|---|---|
| `src/lib/auth.ts` | token from `#token=…` → sessionStorage, removed from the address bar |
| `src/lib/api.ts` | Control API client (D), typed with the generated contracts |
| `src/lib/acp/transport.ts` | browser WebSocket → the `Transport` of an acp-view `AcpConnection` (subprotocols `acp.v1` + `bearer.<token>`) |
| `@handler/acp-view` | the session view: connection, view model, sanitizer (`render.ts`), Timeline, ToolCall, Diff, Composer, PermissionPrompt, theme ([README](../acp-view/README.md)) |
| `src/lib/remote.svelte.ts` + `components/RemoteSettings.svelte`, `QrCode.svelte` | **remote control** (D.7): the connector's light (sidebar, session header), Settings → Remote (gateway, pair with a QR code, revoke), the session's Remote switch |
| `src/lib/sessions.svelte.ts` | **the supervised chat sessions** (sidebar): daemon-held (F), so a reload re-attaches and the turn in progress carries on. Status (needs you / working / replied / idle / open elsewhere / stopped); several tabs at once (F.7: prompts from the others are shown, a permission answered elsewhere is withdrawn); close = stop, resumable from the project's page |
| `src/lib/agents.ts` | helpers shared by agents of projects and ad-hoc ones: the settings of an ad-hoc agent (saved from the network panel), how sandboxed an agent is, folder names, "2 hours ago" |
| `src/lib/router.svelte.ts` | hash routes (`#/sessions/<session id>` survives a reload) |
| `src/views/` | Projects (home), Project (start with a request, live / recent sessions, agents), ProjectEdit, AgentEdit, Session (chat + network panel, Close), Settings (model access: accounts and providers; tools, skills, folders, remote, images, appearance), Knowledge |
| `src/components/` | Sidebar, PageHeader (the top bar: breadcrumb, actions), PageTitle (the heading a page's content opens with), SessionStatus, ModelAccessPicker (an account or a provider, the harness, the model), AgentEditor (presets, risks confirmed), FoldersSettings (work folders), HostList (allowed hosts), FolderPicker (with new folder), BindingPicker, KnowledgePicker, SessionControls, NetworkPanel, HarnessImages, StatusBadge, RemoteSettings, QrCode, AccountsSettings (create, log in in a terminal window handlerd opens, rename), ProvidersSettings + ProviderForm (from a template) |
| `src/lib/components/ui/` | [shadcn-svelte](https://shadcn-svelte.com) components (bits-ui, Tailwind v4), copied in by its CLI (`components.json`): add more with `bunx shadcn-svelte add <name>`, edit freely |
| `src/app.css` | Tailwind entry: shadcn, Inter (self-hosted), and acp-view's `theme.css` (Linear-like tokens with one orange accent, light / `.dark`, markdown styles, `.term-surface`) |
| `src/lib/theme.svelte.ts` | light, dark or like the OS: Settings → Appearance (`components/AppearanceSettings.svelte`), kept in this browser (localStorage), applied as `.dark` |

Security layers for agent output: renderer (no raw HTML, no unsafe links/images) → DOMPurify →
the daemon's Content-Security-Policy. The UI implements no `fs`/`terminal` client capability.

Tests: `tests/` (vitest); real browser: `tests/e2e/test_web_ui.py` (repository root).
