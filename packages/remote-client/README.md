# remote-client — drive shared sessions from a phone

**Implements:** the device side of remote control ([`docs/dev/design/remote.md`](../../docs/dev/design/remote.md)):
pairing from Handler's QR code, envelopes sealed with WebCrypto, and a plain ACP client over them.
Served by the gateway (`remote-gateway/`, v1); talks only to the gateway it is served from, and
through it only to Handler — end to end encrypted.
**Depends on:** the generated D.7 types (`src/lib/remote.gen.ts` ← `schemas/handler.remote.v1.*`, `bun run gen:types` at the root), `packages/acp-view` (the session view, the same as the Handler web UI's), the ACP
TypeScript SDK. Never imports the Handler web UI.

```
bun run check   # svelte-check
bun run test    # vitest: envelopes against tests/fixtures/remote-vectors.json, pairing links
bun run build   # → dist/, served by `handler-gateway serve --client …`
bun run dev     # hot reload, proxies /v1 to a gateway (HANDLER_GATEWAY_URL, default 127.0.0.1:7431)
```

| Path | Role |
|---|---|
| `src/lib/crypto.ts` | envelopes: HKDF keys, AES-256-GCM seal/open, AAD — the twin of `handler_control/remote_crypto.py` |
| `src/lib/pairing.ts` | `#pair=…` → non-extractable keys in IndexedDB (the raw key is not kept); the fragment leaves the address bar |
| `src/lib/mailbox.svelte.ts` | the link to the host: posts sealed frames, long-polls, opens, tracks each command (sent → fetched → delivered, or expired); one ACP `Transport` per session; lights (gateway reachable, host polling) |
| `src/lib/app.svelte.ts` | the app: pairing, the shared sessions, the open session (an acp-view `AcpConnection`) |
| `src/views/` | Pair, SessionList, SessionScreen, Lights |

Security: agent output is rendered by acp-view's sanitizer; the gateway serves the page with a
strict Content-Security-Policy. Whoever serves this JavaScript could misuse the device key: see
`docs/dev/design/remote.md` §2 and §8 (v3: another trust domain).
