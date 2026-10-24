# Remote control — design

Status: **implemented** (2026-09-27), except what §8 lists: F.7, gateway, connector, remote
client. Tests:
`tests/remote` (protocol, hostile gateway), `tests/e2e/test_remote_ui.py` (a phone in a real
browser), `remote-gateway/tests`, the envelope vectors on both sides.

Setting it up, as users do: [your phone](../../user/phone.md).

Reach running agents from a phone or tablet, like Claude Code Remote Control: Handler never listens to
the outside and never opens a port; it polls a **gateway** outbound. The gateway may run on
another machine, may be reachable from the internet, and **may be compromised**: it only relays
end-to-end encrypted envelopes it cannot read or forge.

## 1. Pieces

```
 phone / tablet                   GATEWAY (untrusted)                        host (no inbound port)
┌──────────────────┐ HTTPS ┌───────────────────────────────┐   HTTPS    ┌──────────────────────────┐
│ remote client     │─────►│ mailbox per (host, device):    │◄───────────│ handlerd                  │
│ ACP over an E2E   │◄─────│   down: device → host          │ long-poll  │  └ remote connector       │
│ transport         │ poll │   up:   host → device          │ (outbound) │    decrypt · verify ·     │
└──────────────────┘      │ + serves the client's static   │            │    allow-list · attach    │
                          │   files (v1)                    │            │    to the session (F)     │
                          └───────────────────────────────┘            └──────────────────────────┘
        └──────────── AES-256-GCM, one key per device; the gateway never has it ────────────┘
```

| Piece | Where | Depends on |
|---|---|---|
| Gateway | `remote-gateway/` — independent project: own `pyproject.toml`, no import from Handler, Handler does not import it | the envelope spec only (§4) |
| Remote client | `packages/remote-client` — a separate small web app (session list + session view), **not** the Handler web UI | `packages/acp-view`, the envelope spec |
| Shared view | `packages/acp-view` — agent-output rendering extracted from `packages/web-ui`: sanitizer (`render.ts`), transcript model, Timeline, ToolCall, PermissionPrompt, Composer | ACP SDK |
| Connector | handlerd (control plane), one loop for all remote-enabled sessions; uses sessions only through their public ACP/attach interface, so the policy (C.4) applies unchanged | contracts |

The client is an **Handler client** (it speaks ACP to Handler and holds Handler's device keys); the gateway
only stores and serves its files. The two web apps share rendering code at build time, never
screens: the remote client contains no management UI.

The client speaks **plain ACP**; only its transport differs: `mailboxStream()` (encrypt, post,
long-poll, decrypt) instead of `websocketStream()`. Sessions (F) already give what a flaky mobile
link needs: the agent keeps running between attachments, and `session/load` with
`handler.dev/afterSeq` resyncs after a gap.

## 2. Trust model

| A compromised gateway can… | …but cannot |
|---|---|
| stop relaying (lights go red) | read prompts, output, paths, session names |
| see who talks to whom, when, how much | send a command (no key) |
| replay, alter, relabel, or reflect envelopes, hold a command back more than 5 min | have them accepted (envelope id bound to the ciphertext, replay cache, time window, per-direction keys — §4) |
| drop or reorder envelopes | more than a stale view: nothing runs twice or late; the client re-syncs from the session log (`afterSeq`) |
| lie about "fetched" | forge the host's encrypted ack |
| **serve malicious JavaScript to the phone** (v1: it hosts the client) | — accepted for v1, see §7 |

Whatever the device holds, Handler only lets it: reach sessions whose `remote` switch is on, call the
allow-listed methods (§5), through the usual policy pipeline, and — the owner's devices only —
start a session of an agent whose owner marked it `remoteStart` ("Can be started from your
phone", 2026-09-29): that agent as configured, in its project's folder, nothing else chosen from
the device. No project, agent, network or other session creation from remote.

v1 deployment: home server behind Tailscale (the gateway is not on the public internet). The
design does not rely on that; a VPS later changes nothing in the protocol.

## 3. Pairing (per-device keys)

1. Local Handler web UI → Settings → Remote → **Pair a device**.
2. handlerd creates `deviceId` + random 256-bit `K_dev`, shows a QR code:
   `https://<gateway>/#pair=<gatewayUrl>,<hostId>,<deviceId>,<K_dev>` — the fragment is never sent
   to a server.
3. The phone scans it; the client imports `K_dev` as a **non-extractable** WebCrypto key into
   IndexedDB.
4. handlerd registers the device with the gateway, sending only `sha256(authToken)`, where
   `authToken = HKDF(K_dev, "handler-remote gateway-auth")`: the gateway can authenticate the device
   and learns nothing about the encryption keys.

Revoking a device (Handler UI) deletes its key on the host and at the gateway. Even if the gateway
ignores the revocation, Handler rejects the device. A device can only be enrolled from the local UI:
the gateway cannot add one.

Host ↔ gateway: `handler-gateway add-host` prints a host token; Handler's settings hold the gateway URL
and that token.

## 4. Envelope

Implementation: `packages/control-plane/src/handler_control/remote_crypto.py` (host) and
`packages/remote-client/src/lib/crypto.ts` (WebCrypto); both are checked against
`tests/fixtures/remote-vectors.json`.

```jsonc
// what the gateway sees (it adds `dev` and `cursor` when it hands envelopes to the host)
{ "id": "<128 random bits>", "nonce": "<96 bits>", "ct": "<ciphertext + tag>" }   // base64url
// ct = AES-256-GCM(key[dir], nonce, plaintext, aad = "handler-remote/v1|hostId|deviceId|dir|id")
{ "expires": 1790000300000,                              // unix ms: taken before it, once
  "frames": [ { "s": "s_…" | null, "m": { /* JSON-RPC */ } } ],
  "acks": ["<id>"…], "rejected": [{ "id": "…", "reason": "expired" }] }   // up only
```

- Keys: `HKDF-SHA256(K_dev, salt "handler-remote/v1", info "down" | "up" | "gateway-auth")`. Down is
  device → host, up is host → device: an envelope sent back to its sender does not open.
- The AAD binds the envelope to its host, device, direction and id: the gateway cannot relabel
  one or move it to another device.
- **Expiry, replays:** each envelope says until when its reader may take it (`expires`, set by
  its sender): the reader takes it once, before then, whichever way it came. A device's command
  expires in 5 min (now or never), a call it queues for an offline host in 7 days (§5, `apps.md`
  §5.3), handlerd's own envelopes in 15 min. handlerd keeps each id it took until it expires
  (`<state>/remote-replay.json`, so a restart does not forget them), refuses one that expires more
  than 7 days ahead, and says when it refused an expired one in its next `up` envelope
  (`rejected`): the client shows the command as expired. The client keeps the ids it opened in
  its tab's `sessionStorage` (a reload keeps them; each tab polls on its own) and gives its
  requests random ids, so an old answer replayed never answers a new request. Why an expiry
  rather than one replay window per way in: the gateway chooses the way (it can keep a command
  and hand it over later as queued), the expiry is sealed. Ids rather than counters: several
  tabs of the client may share a device key.
- **Frames:** `s` is the Handler session id: the frame is ACP traffic of the device's attachment to
  that session. `s: null` is the control channel (§5).
- **Up** traffic is batched (~250 ms, ≤ 512 KiB of plaintext per envelope).
- **Status of a command:** sent (the gateway answered 202) → fetched (the gateway saw the host
  take it: `fetched` in the device's poll — a hint only) → acknowledged (`acks`, sealed by the
  host: the truth).

## 5. Connector (handlerd)

Implementation: `packages/control-plane/src/handler_control/remote.py`; Control API: contract D.7.

- **Remote switch:** `remote` on the live session (`PUT /v1/sessions/{id}/remote {enabled}`),
  **off by default**, toggled from the session view at runtime; only a running session can be
  shared (409). **Reset to off** when the session stops (stop, idle timeout, agent exit, daemon
  restart). Off closes the devices' attachments at once (`_handler/remote/closed`, code 4004).
- **Reachable:** running sessions with the switch on. A stopped session is not restarted from
  remote. A device is an ordinary attachment (F.7) of the session: the policy applies, and the
  local tabs see its prompts.
- **Messages are contract documents** `handler.remote/v1` (`handler_contracts/remote.py`, schemas
  `schemas/handler.remote.v1.*`, TypeScript `packages/remote-client/src/lib/remote.gen.ts`): each
  request's params and result, and each notification's params, has its model; handlerd refuses
  params that do not fit with -32602. Absent fields are left out, never `null`.
- **Control channel** (`s: null`): `_handler/remote/list_sessions` → `{sessions: [{id, title,
  label ("project · agent"), projectId, project, agent, origin, harness, scope, acpSessionId,
  busy, pendingPermissions}]}` (shared ones only; the client groups them by project);
  `_handler/remote/list_agents` → `{projects: [{projectId, project, agents: [{id, name, description,
  default}]}], chats: [{id, name, description, default}]}` (the agents marked `remoteStart`; and
  who you talk to in Chat, D.1 `chat`, the one used last the default: no folder, so started as
  Ask runs, with no `remoteStart`; both empty for an `apps` device);
  `_handler/remote/start_session {agentId, prompt?}` → `{session}` (a listed agent only, an
  `all` device only, -32602 otherwise): a session of that agent, origin `phone`, its request sent
  first, shared with the devices once it runs (`sessions_changed` then lists it and the device
  attaches); Ask (D.24), an `all` device only (-32602 otherwise: Ask runs actions as the owner):
  `_handler/remote/ask_options` → `{actions: [{app, action, description}]}`, `_handler/remote/ask
  {turns, timezone?}` → the `AssistantAnswer` (answered once the router decided and the pick ran:
  the client waits up to 2 minutes), `_handler/remote/action_run {app, action, runId}` → the
  `ActionRun` (an agent's action read again); `ask_options` also says whether the host `listens` (a speech model
  chosen, D.25) and `readAloudSpoken`/`readAloudTyped`; `_handler/remote/transcribe {audio,
  format, language?}` → `{text}` (an `all` device only; answered once the provider wrote it down;
  16 kbit/s Opus for at most 60 s keeps the envelope under the gateway's 256 KiB); `_handler/remote/ping` (notification: renews the lease); `_handler/remote/detach {s}`. From the host:
  `_handler/remote/sessions_changed {sessions}` (the new shared list: with nothing shared, no
  agent startable and nothing to Ask, handlerd stops polling, so a device could not ask), `_handler/remote/closed {s, code, reason}` (an
  attachment was closed: F.4/F.7 codes, 4004 unshared, 4003 too far behind).
- **Session channel** (`s: <id>`): `initialize` attaches (again), then `session/load` (with
  `afterSeq`), `session/prompt`, `session/cancel`, `session/set_mode`,
  `session/set_config_option`, and answers to permission requests (all options). Errors:
  **-32020** not shared, **-32021** not attached (send `initialize`), **-32022** not allowed
  remotely (anything else, e.g. `session/new`).
- **Lease:** a device that sent nothing for 90 s is detached (so an idle session can still stop)
  and told so (`_handler/remote/closed`, code 1001 "device idle"): it re-attaches when it wakes up.
  The client pings every 30 s while it is open. A phone that slept may not have the notice yet
  when it is used again, so the client does not wait for it: back on after nearly 90 s without
  sending, it re-attaches at once, and a prompt refused with -32021 is sent again on a new
  attachment (the agent never got it). A prompt that still fails goes back into the input, and
  the input is kept on the phone for each session until it is sent.
- **Polling:** one loop, only while a gateway is set and at least one session (or app) is shared,
  or an agent is marked `remoteStart` (so a device can start one):
  `GET /v1/host/poll` held up to 25 s (a quick poll first when the light is not green), given up
  as soon as nothing is shared any more. Output goes up with `POST /v1/host/up`; a device more than
  16 MiB behind is detached (it re-syncs).
- **Status light** (`GET /v1/remote`, shown in Settings → Remote and by each session's switch;
  the menu has no Remote row: a phone on each shared session, and a line only when the gateway is
  unreachable or refused while a session is shared, since that is when it costs you):
  ⚪ `off` no gateway · ⚪ `idle` nothing shared, not polling · 🟢 `ok` the last poll succeeded ·
  🔴 `unreachable` (with the error, since when) · 🟠 `unauthorized` host token refused. The
  gateway keeps "host last seen", so the client shows the host online or offline.
- **Files:** `<config>/remote.json` (gateway URL, host token) and `<config>/remote-devices.json`
  (devices and their keys), both 0600; `<state>/remote-replay.json`.

## 6. Gateway

`remote-gateway/` ([README](../../../remote-gateway/README.md)). Store-and-forward mailbox, small
enough to audit: Starlette, a JSON registry (hosts and devices, by token hash), envelopes in
memory with a TTL (10 min) and bounds; rate limits; no admin UI; TLS by a reverse proxy or
`tailscale serve` (HTTPS is required: WebCrypto). Serves the client's static files (v1) with a
strict Content-Security-Policy.

| Route | Caller | |
|---|---|---|
| `GET /v1/host/poll?after=&wait=` | host | long-poll envelopes from its devices, marks them fetched |
| `POST /v1/host/up` | host | envelopes for its devices |
| `GET /v1/host/devices` · `PUT/DELETE /v1/host/devices/{dev}` | host | list / register (token hash) / revoke |
| `POST /v1/device/down` | device | an envelope → 202 |
| `GET /v1/device/poll?after=&wait=` | device | long-poll envelopes + fetched ids + host last seen |

## 7. Where it lives

| Piece | Code | Tests |
|---|---|---|
| F.7 several attachments | `packages/control-plane/src/handler_control/sessions.py` | `tests/sessions` |
| Envelopes | `handler_control/remote_crypto.py`, `packages/remote-client/src/lib/crypto.ts` | `tests/fixtures/remote-vectors.json` on both sides |
| Connector + D.7 | `handler_control/remote.py`, `api/remote.py` | `tests/remote` (real gateway, Python device, hostile cases) |
| Gateway | `remote-gateway/` | `remote-gateway/tests` |
| Web UI | `packages/web-ui/src/lib/remote.svelte.ts`, `components/RemoteSettings.svelte` | `tests/e2e/test_remote_ui.py` |
| Remote client | `packages/remote-client/` (+ `packages/acp-view`) | its vitest, `tests/e2e/test_remote_ui.py` |

## 7b. Apps

Devices also reach **apps** (docs/dev/design/apps.md §5.2, contract H.8): frames on `s:
"app:<name>"`, a device person and scope (`apps`-only devices for family members), and handlerd polls
while a session or an app is shared.

## 8. Not built yet

- **Client hosted in a separate trust domain:** today whoever serves the client's JavaScript can
  steal the device key. Move it off the gateway (static hosting of a reproducible build); handlerd
  shows the expected bundle hash at pairing.
- Restart a stopped remote-enabled session from remote.
- Restrict some permission answers (e.g. "always allow") to the local UI.
- Push notifications for sessions ("agent waiting for permission"), content-free through Web Push
  like the inbox's (`apps.md` §7).
- PIN / passphrase lock of the key on the device; forward secrecy (ephemeral ECDH per connection).
