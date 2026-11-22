# remote-client — drive shared sessions from a phone

**Implements:** the device side of remote control:
pairing from Handler's QR code, envelopes sealed with WebCrypto, and a plain ACP client over them.
Served by the gateway (`remote-gateway/`, v1); talks only to the gateway it is served from, and
through it only to Handler — end to end encrypted.
**Depends on:** the generated D.7 types (`src/lib/remote.gen.ts` ← `schemas/handler.remote.v1.*`, `bun run gen:types` at the root), `packages/acp-view` (the session view, the same as the Handler web UI's), the ACP
TypeScript SDK. Never imports the Handler web UI.

```
bun run check   # svelte-check
bun run test    # vitest: envelopes against tests/fixtures/remote-vectors.json, pairing links
bun run build   # → dist/ (+ .br/.gz of each text file), served by `handler-gateway serve --client …`
bun run dev     # hot reload, proxies /v1 to a gateway (HANDLER_GATEWAY_URL, default 127.0.0.1:7431)
```

| Path | Role |
|---|---|
| `src/lib/crypto.ts` | envelopes: HKDF keys, AES-256-GCM seal/open, AAD — the twin of `handler_control/remote_crypto.py` |
| `src/lib/pairing.ts` | `#pair=…` → non-extractable keys in IndexedDB (the raw key is not kept); the fragment leaves the address bar |
| `src/lib/mailbox.svelte.ts` | the link to the host: posts sealed frames (several requests in one envelope: `requestAll`), long-polls (a quick first poll), opens, tracks each command (sent → fetched → delivered, or expired); the ids it opened and its cursor kept across launches; one ACP `Transport` per session; lights (gateway reachable, host polling) |
| `src/lib/app.svelte.ts` | the app: pairing, Home (its lists in one envelope, shown in one go), the tab shown, the open session (an acp-view `AcpConnection`) |
| `src/lib/snapshot.ts` | the last Home, shown at once on the next launch while the host is asked again: sealed under a non-extractable key in IndexedDB, erased with the pairing |
| `src/lib/lazy.ts` | the session and app screens and the ACP connection in chunks of their own, fetched when the browser is idle |
| `src/lib/theme.svelte.ts` | the theme: System, Light or Dark, kept in this browser (localStorage), the twin of the web UI's |
| `src/lib/risk.ts` | a permission is safe or risky: handlerd's `risk` when it is about the same tool call, else risky unless known safe; its scopes (once, all session) |
| `src/lib/card.ts` | what a session's card shows (its age, last line, the ask it can answer) and answering that ask: a short `session/load` past the last event, only the card's tool call, then detach |
| `src/lib/nudges.ts` | a nudge's form drawn from its action's schema, how often it alerts (H.17) |
| `public/sw.js` | the service worker: the client's own files kept (their list written in by the build, `vite.config.ts`), fetched from the gateway first and from the copy when it does not answer, so the app opens offline; the API never kept; notifications |
| `src/lib/update.ts` | a new client on the gateway: a page left open reloads when it comes back to the front, or when a part it loads later is gone |
| `src/views/` | the tabs under a `TabBar`: `AskScreen`, `Sessions` (cards, `CardAnswers` for a safe ask), `Apps` (a launcher), `Inbox` (with `NudgeCard`), `Settings` (with `Appearance`, `Connection`); each list under a `ListHeader` (a one-line title, the computer, counts), a state said big by `BigState`; `PageHeader` (a page's back and title), `Chain` (this phone → gateway → computer), `Docked` (the link's banners, at the foot), `Slide` (a slide to confirm, also a button); `SessionScreen` with `PermissionSheet`; `Pair`, `Starting`, `Lights`, `Offline`, `NewSession`, `AppScreen` |
| `index.html` | a neutral screen ("Connecting…", the tabs' place) in plain HTML and an inline style (no script: the page's policy), painted before the app's files arrive; the build moves the app's stylesheet and script after it |

Security: agent output is rendered by acp-view's sanitizer; the gateway serves the page with a
strict Content-Security-Policy. Whoever serves this JavaScript could misuse the device key: see
[your phone, security](../../docs/phone.md#security) (serving it from elsewhere is planned).
