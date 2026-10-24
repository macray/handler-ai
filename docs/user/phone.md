# Your phone: the gateway

The gateway (`handler-gateway`, in [`remote-gateway/`](../../remote-gateway/README.md)) lets a phone or
tablet control shared agent sessions and apps. Handler never opens a port: it polls the gateway
outbound, and the phone talks to the same gateway. Everything relayed is end-to-end encrypted;
the gateway cannot read or forge it. How it is built and what a
compromised gateway can do: [remote control design](../dev/design/remote.md).

```
phone ──HTTPS──► gateway ◄──HTTPS (outbound long poll)── handlerd on your machine
```

The gateway does two jobs:

- a **mailbox** between Handler hosts and their paired devices (`/v1/...`);
- a **web server** for the remote client, the small web app the phone opens (`/`).

## Before you start

- **HTTPS is required.** Browsers only give the remote client WebCrypto on `https://` pages (or
  localhost). Plain `http://` over the LAN does not work.
- **Where to run it.** Any always-on machine that both the phone and your Handler machine can reach:
  a home server, a NAS, a VPS, or the Handler machine itself.
- **Choose how it is reached** (this guide covers both):
  - **Tailscale** (recommended): reachable only from your own devices, TLS certificate handled
    for you.
  - **Public, behind a reverse proxy** (Caddy on a VPS): reachable from anywhere. See
    [Security](#security) first.
- **Choose how it runs:** a container (Podman; builds the remote client for you), or directly
  with `uv` (needs `bun` to build the client).

## 1. Install and run it

### Option A: container (recommended)

Build from the **repository root** (the image also builds the remote client):

```bash
podman build -f remote-gateway/Containerfile -t handler-gateway .
```

Try it:

```bash
podman run -d --name handler-gateway -p 127.0.0.1:7431:7431 -v handler-gateway:/state handler-gateway
curl http://127.0.0.1:7431/v1/health
```

It listens on `127.0.0.1:7431` only; TLS comes in step 2. The `handler-gateway` volume holds its
state (`/state/state.json` and `/state/state.queue/`).

To keep it running across reboots, replace the `podman run` with a Quadlet unit.
`~/.config/containers/systemd/handler-gateway.container`:

```ini
[Unit]
Description=handler remote-control gateway

[Container]
Image=localhost/handler-ai-gateway:latest
ContainerName=handler-gateway
PublishPort=127.0.0.1:7431:7431
Volume=handler-gateway:/state

[Service]
Restart=always

[Install]
WantedBy=default.target
```

```bash
podman rm -f handler-gateway             # the test container, if still there
systemctl --user daemon-reload
systemctl --user start handler-gateway
loginctl enable-linger "$USER"           # keep user services running when you are logged out
```

### Option B: without a container

Build the remote client (from the repository root):

```bash
bun install
cd packages/remote-client && bun run build      # → packages/remote-client/dist
```

Install and run the gateway (its own project, with its own virtualenv):

```bash
uv tool install ./remote-gateway                # → ~/.local/bin/handler-gateway
handler-gateway serve --port 7431 --client "$PWD/packages/remote-client/dist"
```

As a systemd user service, `~/.config/systemd/user/handler-gateway.service`:

```ini
[Unit]
Description=handler remote-control gateway

[Service]
ExecStart=%h/.local/bin/handler-gateway serve --port 7431
Environment=HANDLER_GATEWAY_CLIENT_DIR=/path/to/handler/packages/remote-client/dist
Restart=always

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now handler-gateway
loginctl enable-linger "$USER"
```

State lives in `~/.local/state/handler-gateway/` (set `HANDLER_GATEWAY_STATE` to move it).

## 2. Put HTTPS in front

### Tailscale

Enable MagicDNS and HTTPS certificates for your tailnet (admin console → DNS), then on the
gateway machine:

```bash
tailscale serve --bg --https=443 http://127.0.0.1:7431
```

The gateway is now at `https://<machine>.<tailnet>.ts.net`, for devices on your tailnet only.
Install Tailscale on the phone too. Use `tailscale serve`, not `tailscale funnel` (Funnel makes
it public).

### Caddy (public)

Point a DNS name at the server, open ports 80 and 443, then in the `Caddyfile`:

```
gateway.example.com {
	reverse_proxy 127.0.0.1:7431
}
```

Caddy gets the certificate by itself. Its defaults suit the gateway's long polls (held up to
25 s); if you use another proxy, allow at least 30 s of read timeout and 8 MiB request bodies.

Leave the gateway on `127.0.0.1`; use `--host 0.0.0.0` only when the thing in front terminating
TLS cannot reach localhost (the container image already does this inside the container, and the
port is published on `127.0.0.1` only).

Check:

```bash
curl https://<gateway>/v1/health
```

and open `https://<gateway>/` on the phone: the remote client should load.

## 3. Register your Handler machine

On the gateway machine, add one host per Handler machine:

```bash
podman exec handler-gateway handler-gateway add-host laptop  # container
handler-gateway add-host laptop                              # without a container
```

It prints the **host token, shown once**. The gateway only keeps its hash. Copy it now.

```bash
handler-gateway hosts             # hosts and how many devices each has
handler-gateway remove-host h_…   # a host and all its devices
```

## 4. Connect Handler and pair a phone

In the Handler web UI (`handler ui`) on your machine:

1. **Settings → Remote**: the gateway URL (`https://<gateway>`) and the host token, then
   **Connect**. Saved in `~/.config/handler-ai/remote.json` (0600).
2. **Settings → Remote → Pair a device**: a dialog asks who the device is for and its name, then
   shows a QR code: scan it with the phone, then tap **Pair**. The key travels in the link's
   `#fragment`, which never reaches a server, and the code is shown only once. Devices can only
   be paired from here, never from the gateway.
   - **Who is it for?** *Me* for your own devices (sessions and apps). *A family member*, with
     their name (`alice`; lowercase letters, digits, `-`, `_`): the device reaches apps only,
     never a session.
   - **Device name** is just a label (`phone`, `alice-tablet`).
3. In a session, turn on the **Remote** switch. The phone lists the session.

## 5. Use an app from the phone

[Apps](apps.md) are reached through the same gateway, end-to-end encrypted like
sessions. The app still runs only on your machine: there is no URL of its own from outside
(`http://<name>.localhost:7430/` works on the machine itself only).

1. Deploy the app (Apps page, or `handler app deploy`).
2. On the **Apps** page, next to **Remote (devices of)**, tick the persons who may use it: *you*
   for your own devices, and each family member you paired a device for. Apps are shared with
   **persons, not devices**: every device of a ticked person gets the app, and a device paired
   later for that person gets it too. Nothing is ticked by default (local only).
3. On the phone, open `https://<gateway>/`: the shared apps are listed above the shared sessions.
   Tap one to open it.

When your machine is off, the phone shows the last copy of the app's UI it received; calls fail
with "host offline", except routes the app declares `queued`, which wait at the gateway (up to
7 days) and run when the machine is back.

## 6. Ask from the phone

With Ask set up on the computer (its router, the first time you open Ask in the web UI) and an
app that can be asked something (Planner), your own phone opens on **Ask**: type what you want
("tomorrow I call the bank at 10"); Handler picks the app that does it and answers. An app's
agent that takes a minute answers there and in your inbox (pushed, when notifications are on).
When no app does it, **Start a chat about it** opens a new session on Chat with your words
typed. **Home** has the rest: shared sessions, apps, your inbox, and **New session**: on an agent
of a project that **Can be started from your phone**, or on someone you talk to in Chat (they
have no folder, so your own phone may start them, as it asks). A family member's phone has no
Ask and starts nothing: it runs apps' actions as you. With Voice set up (Settings → Voice), hold the
microphone to speak, and *Dictate* in New session writes down what you say the same way. See
[Ask](ask.md#speaking).

Status lights (Settings → Remote and each session's switch): 🟢 ok · ⚪ idle (nothing shared,
Handler not polling) · 🔴 unreachable · 🟠 unauthorized (host token refused). The menu shows a
phone on each shared session, and says when the gateway is unreachable or refused while a session
is shared; nothing otherwise.

## Operations

**Update.** Container: `git pull`, rebuild the image, `systemctl --user restart handler-gateway`
(or `podman rm -f` + `podman run`). Without a container: `uv tool install --reinstall
./remote-gateway`, rebuild the client, restart the service. A restart loses envelopes in transit
(in memory, 10 min at most); Handler and the phones resync from the session log on their own.
Envelopes queued for an offline host (`state.queue/`, up to 7 days) survive.

**Back up** the state: the `handler-gateway` volume, or `~/.local/state/handler-gateway/`. It only
holds token hashes and still-encrypted queued envelopes, nothing readable.

**Lost host token.** `remove-host` the old host (this removes its devices at the gateway too),
`add-host` a new one, and enter the new token in Settings → Remote. Pair the phones again if
they do not reconnect.

**Revoke a phone** from Handler (Settings → Remote). Handler deletes its key and removes it from the
gateway; even a gateway that ignored the removal cannot get the phone's commands accepted.

**Limits** (built in): 20 requests/s per caller (burst 60), 256 KiB per command, 8 MiB per
upload, 500 waiting commands per host (then `503`: commands are never dropped silently), 5000
waiting output envelopes per device (the oldest are dropped; the phone resyncs).

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| The phone opens the page but says crypto is unavailable | not served over HTTPS |
| 🔴 unreachable in Handler | wrong URL, gateway down, or the Handler machine cannot reach it (e.g. not on the tailnet) |
| 🟠 unauthorized in Handler | wrong or removed host token: `handler-gateway hosts`, then `add-host` again |
| The phone shows the host offline | Handler only polls while something is shared: turn on a session's **Remote** switch, or share an app |
| The phone lists no apps | the app is not deployed, or not ticked for the device's person on the Apps page |
| The phone lists no sessions | no running session has **Remote** on (it resets to off when a session stops) |
| A command shows "expired" | the phone's or the host's clock is more than 5 min off |
| `/` returns 404 | the client is not configured: `--client` / `HANDLER_GATEWAY_CLIENT_DIR` (the container sets it) |

Logs: `journalctl --user -u handler-gateway` (or `podman logs handler-gateway`).

## Security

The design assumes the gateway can be compromised: it cannot read your prompts or output, send
commands, or replay them. **One exception in v1:** the gateway also serves the remote client's
JavaScript, so whoever controls the gateway could serve a modified client and take the key of a
phone that opens it. Hence:

- prefer Tailscale, so the gateway is not on the public internet;
- on a public server, keep it patched, run nothing else sensitive on it, and use the container
  (non-root user, only `/state` writable);
- if you think the gateway was tampered with, revoke every device in Handler and pair again after
  redeploying.

Moving the client off the gateway is planned.
