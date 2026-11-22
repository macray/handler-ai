# Your phone: the gateway

The gateway (`handler-gateway`, in [`remote-gateway/`](../remote-gateway/README.md)) lets a phone or
tablet control shared agent sessions and apps. Handler never opens a port: it polls the gateway
outbound, and the phone talks to the same gateway. Everything relayed is end-to-end encrypted;
the gateway cannot read or forge it. What a compromised gateway can do: [security](#security).

## How it works

Three pieces: the phone, the gateway, and Handler on your computer. The gateway does two jobs,
in one program today:

- **Gateway UI**: a web server for the **remote client**, the small web app the phone opens
  (`https://<gateway>/`). Just files: the phone runs them.
- **Gateway relay**: a **mailbox** between Handler and its paired devices (`/v1/...`). It keeps
  sealed messages (envelopes) until the other side takes them.

```
                         ┌────────────────── gateway (handler-gateway) ──────────────────┐
  phone / tablet         │                                                               │
 ┌────────────────┐  1   │  ┌──────────────────────┐                                     │
 │ browser        │◄─────┼──│ Gateway UI           │ the remote client's files (/)       │
 │ ┌────────────┐ │      │  └──────────────────────┘                                     │
 │ │ remote     │ │  2   │  ┌──────────────────────┐                                     │
 │ │ client     │─┼─────►┼─►│ Gateway relay        │  per device: commands down,         │
 │ │ (its key)  │◄┼──────┼──│ mailboxes, queue     │  output up (10 min); calls queued   │
 │ └────────────┘ │      │  └──────────▲───────────┘  for later (7 days)                 │
 └────────────────┘      └─────────────┼─────────────────────────────────────────────────┘
                                       │ 3  outbound long poll (Handler opens no port)
                          ┌────────────┴─────────────────────────┐
                          │ Handler on your computer (handlerd)  │
                          │ the device keys · sessions · apps    │
                          └──────────────────────────────────────┘

  1  the phone loads the app (HTTPS)
  2  the app sends and fetches envelopes (HTTPS; sealed inside)
  3  Handler fetches and sends envelopes (HTTPS; sealed inside)
  ═  phone ⇄ Handler: end-to-end encrypted, with a key the gateway never has
```

A prompt from the phone, step by step:

1. The phone seals the prompt and posts it to the relay, in its host's mailbox.
2. Handler, waiting on the relay (a long poll, up to 25 s at a time), takes it, opens it, checks
   it, and gives it to the session as any other client would.
3. Handler seals the agent's output and posts it to the relay, in the phone's mailbox.
4. The phone, waiting on the relay too, takes it and opens it.

Handler waits on the relay only while something is reachable from a phone (a session or an app
shared, an agent you may start from the phone, Ask set up). When your computer is off, the
phone shows what it saw last, and an app's calls marked for it wait in the relay's queue until
Handler is back.

### How the data is encrypted

**Pairing gives the phone its key.** *Pair a device* makes a random 256-bit key for that device,
on your computer. The QR code is a link to the gateway with the key after `#`: a browser never
sends that part to a server, so the gateway never sees it. Handler keeps the key in
`~/.config/handler-ai/remote-devices.json` (0600); the phone keeps it in its browser, in a form
the page can use but not read back.

**Three keys come from it** (HKDF-SHA256): one for what the phone sends, one for what Handler
sends, and the device's password towards the gateway. The gateway only stores a hash of that
password, and of Handler's host token. It checks who is calling; it cannot open anything.

**Every message is an envelope**, sealed with AES-256-GCM, a fresh random nonce each time. The
seal is bound to your computer, the device, the direction and the envelope's id, so the gateway
cannot change a byte, give one phone's envelope to another, or send Handler's output back to it
as a command: any of these fails to open, and is dropped unread. Inside, each envelope says
until when it is valid (a command: 5 minutes; a queued call: 7 days), and Handler takes each one
once: a gateway that replays a command, or hands it over late, gets it refused.

**Around that, HTTPS.** Every link (1, 2, 3) is HTTPS too, so someone on the network sees even
less than the gateway does.

**Notifications** go through your phone's browser's push service, not the gateway. A push holds
one byte (which kind: *a session needs you* or *something new*), encrypted for that phone and
padded to the same size, signed with a key of your computer's. The text itself stays on your
computer until the phone fetches it, sealed, through the relay.

**On the phone**, the last Home it showed is kept encrypted (AES-256-GCM), with a key of its own
that the page cannot read; *Forget this phone* erases both.

What each side can see:

| | Reads your prompts, output, app data | Sees |
|---|---|---|
| Handler on your computer | yes | everything |
| your phone | yes, what is shared with it | what is shared with it |
| the gateway | no | which device talks to which computer, when, how much; their IP addresses |
| the push service | no | that a phone gets a notification, when |

Two limits, said plainly:

- **The Gateway UI is trusted.** The phone runs the code the gateway serves, and that code holds
  the key. Whoever controls the gateway could serve a modified client: see [security](#security).
- **No forward secrecy.** A device's key stays the same until you pair it again: someone who
  recorded its envelopes and later gets that key could open them. Revoke a phone you lost.

## Before you start

- **HTTPS is required.** Browsers only give the remote client WebCrypto on `https://` pages (or
  localhost). Plain `http://` over the LAN does not work.
- **Where to run it.** An always-on machine that both the phone and your Handler machine can
  reach: a home server, a NAS, a VPS. **Not the Handler machine**: Handler never accepts
  connections from outside, and the gateway would open one there; a gateway taken over should
  never be a step to your Handler machine.
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
Image=localhost/handler-gateway:latest
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

1. **Settings → Your phone**, *1 · Set up your gateway*: the steps above, as copy-ready commands
   (a tab for each way: *Container*, *Without a container*), then step 4: its address
   (`https://<gateway>`) and the host token, and **Connect**. A Connect refused says why (the
   address is not `https://`, the token is not one). Otherwise it is saved in
   `~/.config/handler-ai/remote.json` (0600), and Handler tries the gateway once, at once (a few
   seconds at most): when that fails, it says beside **Connect** what went wrong, in words (the
   gateway didn't answer, something else answered, or the gateway doesn't know the token), and
   the form stays open to fix it. Once it works, the address shows its status light (green), the
   token *sealed*; **Change** enters another (or removes it). After that one try, Handler reaches
   the gateway only while something is on your phone. *This computer's name* is what your phones
   call it (the computer's hostname until you **Rename** it): a phone paired after a rename
   shows the new name; one paired before keeps the name it was given until you pair it again.
2. *2 · Your devices* → **Pair a device** (greyed until a gateway is set): a dialog asks who the device is for and its name, then
   shows a QR code: scan it with the phone, then tap **Pair**. The key travels in the link's
   `#fragment`, which never reaches a server, and the code is shown only once. Devices can only
   be paired from here, never from the gateway.
   - **Who is it for?** *Me* for your own devices (sessions and apps). *A family member*, with
     their name (`alice`; lowercase letters, digits, `-`, `_`): the device reaches apps only,
     never a session.
   - **Device name** is just a label (`phone`, `alice-tablet`).
3. In a session, turn on its phone button (**On your phone**). The phone lists the session.

The phone opens even without a network, or with the gateway or your computer away: it shows the
last Home it saw, faded, under a big title (*laptop is away* · *As it was at 14:02. Answer when it
is back.*), and a session opened then says it is offline. Once your computer answers, the live
Home replaces it.

## 5. Use an app from the phone

[Apps](apps.md) are reached through the same gateway, end-to-end encrypted like
sessions. The app still runs only on your machine: there is no URL of its own from outside
(`http://<name>.localhost:7430/` works on the machine itself only).

1. Deploy the app (its page, or `handler app deploy`).
2. On the app's page, under **On phones**, tick the persons who may use it: *you*
   for your own devices, and each family member you paired a device for. Apps are shared with
   **persons, not devices**: every device of a ticked person gets the app, and a device paired
   later for that person gets it too. Nothing is ticked by default (local only).
3. On the phone, open `https://<gateway>/`: the shared apps are on the **Apps** tab.
   Tap one to open it.

When your machine is off, the phone shows the last copy of the app's UI it received; calls fail
with "host offline", except routes the app declares `queued`, which wait at the gateway (up to
7 days) and run when the machine is back.

## 6. The screens

Tabs at the bottom: **Ask** · **Sessions** · **Apps** · **Inbox** · **Settings**. Ask is there
only when your computer offers something to ask (see [Ask from the phone](#7-ask-from-the-phone));
without it there are four tabs. An amber number on a tab says how many sessions need you, or how
many things in your inbox wait for you. Each screen has a one-line header: its name, and your
computer as a small chip on the right (*● laptop*; tap it to refresh), with its counts under it
(*2 needs you · 1 working · 1 idle*).

A **big title** shows only when the screen is a state, never over a list:

- **First launch**: while the phone reaches your computer, the chain *this phone → gateway →
  computer* lights link by link.
- **Pair this phone with laptop?**: a phone opened from a pairing link, with three steps: show the
  QR code in Handler on your computer, point the phone's own camera at it (the link opens Handler
  there), tap **Pair**. The phone cannot open its camera by itself: the camera app reads the code.
- **laptop is away**: the last Home it saw, faded, *As it was at 14:02. Answer when it is back.*
  What you answer waits at the gateway for 10 minutes at most.
- **all quiet**: nothing needs you.

**Sessions** lists every session your computer shares, in one list, with **New session** (the
**+** button above the tabs). A card shows the session's project and agent, how long ago its state
changed (amber when it waits for you), the state (*working*, *idle*) and the agent's last line. A
session that needs you has a warm tint and says what it asks. A **safe** ask (read a file, say) is
answered on its card: **Reject** or **Allow**, once; a risky one only opens the session. If the
ask is gone or changed when you tap, nothing is allowed and the session opens, saying so.

**Permission requests.** In a session, a request opens as a sheet over it. A **safe** one has two
buttons, **Reject** and **Allow** (once, or always when the agent offers it). A **risky** one (the
agent runs a command, deletes, moves or fetches, or reaches outside its folder or network) says why
in a line, asks you to choose its scope first (the agent's own choices, such as **Allow once** or **Always allow**), and is allowed only
with a **slide**: an accidental tap cannot allow it, and "always" is never quicker than "once".
**Reject** is always a tap. The slide is also a button for the keyboard and screen readers: press
it twice. A session stays dark, like a terminal, in every theme.

**Apps** lists the apps shared with you as a launcher: tap one to open it.

**Inbox** lists, first, what is *asked of you* (a nudge: its small form, filled and sent from
there); then the messages from your apps, automations, plans, sessions and notes (the last five, each marked *new* until you tap it; a tap reads it on your
computer too, later if it is away); then **Waiting for laptop**: the calls you left for your computer, with **Clear
done**.

**Settings** shows this phone (its name, the computer it is paired with, what it can do) and:

- **Appearance**: **System** (light or dark like this phone), **Light** or **Dark**, kept in this
  browser. Sessions stay dark either way.
- **Notifications**: see [Notifications](#8-notifications).
- **Voice**: read aloud *when spoken* or *when typed* (with Voice set up).
- **Connection**: the chain lit link by link, whether the gateway is reachable and your computer
  listening, and the ids of the gateway, the computer and this phone, each with a copy button.
- **Forget this phone**, set apart and red: erases its keys and what it kept; **slide to forget**
  in the sheet that opens. Pairing again needs a new QR code from your computer.

## 7. Ask from the phone

With Ask set up on the computer (its router, the first time you open Ask in the web UI) and an
app that can be asked something (Tracker, Notes), your own phone opens on **Ask**: type what you want
("I drank 2 glasses of water"); Handler picks the app that does it and answers. An app's
agent that takes a minute answers there and in your inbox (pushed, when notifications are on).
When no app does it, **Start a chat about it** opens a new session on Chat with your words
typed. The other tabs have the rest, and **New session** (on Sessions) starts one: on an agent
of a project that **Can be started from your phone**, or on someone you talk to in Chat (they
have no folder, so your own phone may start them, as it asks). An agent with a brief or a job
shows its form instead of a request: fill it in and **Start**, as on the computer. A family member's phone has no
Ask and starts nothing: it runs apps' actions as you. With Voice set up (Settings → Expert → Voice), hold the
microphone to speak, and *Dictate* in New session writes down what you say the same way. See
[Ask](ask.md#speaking).

Status lights (Settings → Your phone and each session's switch): 🟢 ok · ⚪ idle (nothing shared,
Handler not polling; after Connect, the light shows its try instead) · 🔴 unreachable · 🟠 unauthorized (host token refused). A shared session's
header shows its phone button on, and the menu says when the gateway is unreachable or refused while a session
is shared; nothing otherwise.

## 8. Notifications

On the phone, **Settings → Notifications** has two switches, each turning on one kind:

- **When a session needs you**: a session you share with the phone asks you something (a
  permission); the phone shows "A session needs you". Once for each time it starts waiting, not
  for each question. Only on a phone that sees your sessions.
- **When an app has news**: an app's message, an automation's result, or a call you left for your
  computer has run; the phone shows "Something new for you".

The notification says nothing more: the text stays on your machine, and the phone reads it,
encrypted, when you open Handler. Turning both off stops notifications on this phone. On an iPhone, add Handler to the home screen first
(Share → Add to Home Screen) and open it from there.

**Send a test notification** checks it, with two notifications:

1. "Test 1 of 2: shown by this phone": the phone shows it itself. None: the phone's settings
   block notifications, the browser's (a site permission) or the phone's own (the browser's
   notifications, Do Not Disturb).
2. "Something new for you", a few seconds later: Handler sends it through the browser's push
   service, as for a real message. A red line says why when the push service refused it. Only
   the first one appears: the push service took it but it never reached the phone.

## Operations

**Update.** Container: `git pull`, rebuild the image, `systemctl --user restart handler-gateway`
(or `podman rm -f` + `podman run`). Without a container: `uv tool install --reinstall
./remote-gateway`, rebuild the client, restart the service. A restart loses envelopes in transit
(in memory, 10 min at most); Handler and the phones resync from the session log on their own.
Envelopes queued for an offline host (`state.queue/`, up to 7 days) survive.

**Back up** the state: the `handler-gateway` volume, or `~/.local/state/handler-gateway/`. It only
holds token hashes and still-encrypted queued envelopes, nothing readable.

**Lost host token.** `remove-host` the old host (this removes its devices at the gateway too),
`add-host` a new one, and enter the new token in Settings → Your phone. Pair the phones again if
they do not reconnect.

**Revoke a phone** from Handler (Settings → Your phone, its **Revoke**). Handler deletes its key and removes it from the
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
| The phone shows the host offline | Handler only polls while something is shared: turn on a session's phone button, or share an app |
| The phone lists no apps | the app is not deployed, or not ticked for the device's person on the app's page |
| The phone lists no sessions | no running session has its phone button on (it resets to off when a session stops) |
| A command shows "expired" | the phone's or the host's clock is more than 5 min off |
| Every request on the phone ends in "the host did not answer", and Handler's log says `dropped an envelope … no expiry` | the gateway serves an old phone client: rebuild the gateway's image and restart it |
| Only "Test 1 of 2" appears when you test notifications | the push service took it but it does not reach the phone: on Android, check that the browser may run in the background (Settings → Apps → the browser → Battery) |
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

What the phone keeps: its keys (usable by the page, never readable); the client's own files, so
it opens without a network (nothing of yours in them; the gateway's answers are never kept); and,
to show your Home at once on the next opening while it asks your computer again, or when nothing
answers, the last Home it showed (what is shared with you, your inbox, what you can ask), only
encrypted, with a key of its own that the page cannot read. **Forget this phone** in Settings
erases it, and so does pairing again.

Moving the client off the gateway is planned.
