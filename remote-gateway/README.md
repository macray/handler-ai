# handler-gateway — remote-control relay

A mailbox between Handler hosts and their paired devices (phone, tablet), for remote control of
shared agent sessions. Handler polls it outbound; Handler never
listens to the outside. It relays **end-to-end encrypted envelopes it cannot read or forge**:
assume it can be compromised, the design does.

It is kept in the Handler repository but is an **independent project**: its own `pyproject.toml`
and virtualenv, no import from Handler (checked by `tests/architecture`), and Handler does not import it.
It shares only the envelope format, as data. Run every command from this folder.

```bash
uv run handler-gateway add-host laptop    # prints the host token (shown once): give it to handler
uv run handler-gateway hosts              # hosts and their device counts
uv run handler-gateway remove-host h_…    # a host and its devices
uv run handler-gateway serve --port 7431 --client ../packages/remote-client/dist
uv run pytest                             # its own tests
```

State: `$HANDLER_GATEWAY_STATE` (default `~/.local/state/handler-gateway/state.json`, 0600): hosts
(hash of their token) and the devices each host registered (hash of their gateway token);
the CLI and the server change it in turn (`state.lock`), so neither undoes the other.
Envelopes in transit live in memory only (10 min, bounded): a restart loses them, and readers
start over (their cursors belong to the previous run).
Next to it, `state.queue/` (one file per envelope, 0600): envelopes a device queued for when its
host is back (Handler's apps, "queued" routes), kept up to 7 days until the host takes them;
still opaque.
`/appframe.html` of the client is served with its own policy (no connection at all): an app
runs in it on the phone.

## Deploying

- **HTTPS is required** for the remote client: browsers give WebCrypto only to `https://` pages
  (and localhost). Behind Tailscale: `tailscale serve --bg --https=443 http://127.0.0.1:7431`
  gives `https://<machine>.<tailnet>.ts.net`, reachable from your devices only. On a VPS: a
  reverse proxy (Caddy) in front.
- It listens on 127.0.0.1 by default; `--host 0.0.0.0` only behind something that terminates
  TLS.
- Container: `podman build -f remote-gateway/Containerfile -t handler-gateway .` from the
  repository root (it builds the remote client too), then
  `podman run -d -p 127.0.0.1:7431:7431 -v handler-gateway:/state handler-gateway`, and
  `podman exec <container> handler-gateway add-host laptop`.

## API

| Route | Caller | |
|---|---|---|
| `GET /v1/host/poll?after=&wait=` | host | long poll (≤ 25 s) for envelopes from its devices; marks them fetched |
| `POST /v1/host/up` `{envelopes: [{dev, id, nonce, ct}]}` | host | envelopes for its devices |
| `GET /v1/host/devices` · `PUT/DELETE /v1/host/devices/{dev}` `{tokenHash}` | host | register, re-key, revoke its devices |
| `POST /v1/device/down` `{id, nonce, ct}` | device | an envelope for its host → 202 |
| `GET /v1/device/poll?after=&wait=` | device | long poll for envelopes, ids the host fetched, `hostSeen` |
| `GET /v1/health` | anyone | |
| `/` | anyone | the remote client's static files (`--client`), strict Content-Security-Policy |

Auth: `Authorization: Bearer <hostId>.<secret>` (host) or `<deviceId>.<token>` (device), compared
by SHA-256 hash. Limits: 20 requests/s per caller (burst 60), 256 KiB per command envelope, 8 MiB
per upload, 500 queued envelopes per host (then 503: commands are never dropped silently), 5000
per device (the oldest are dropped: the device re-syncs from Handler's session log).

What a compromised gateway can and cannot do: [your phone, security](../docs/phone.md#security).
