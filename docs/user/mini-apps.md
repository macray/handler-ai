# Mini apps

A **mini app** is a small web app an agent writes for you: a tracker, a price calculator, a
coach that asks how your tasks are going. Handler runs it on your machine, and you use it from
your desktop (its own window, a keyboard shortcut) or from your phone, always the same app with the
same data: there is one copy of each app, on your machine, and nothing to sync.

## Have an agent write one

Give the agent the built-in `miniapp` addon: make a configuration of it (Settings → Addons; it
needs no setting) and select it in the agent's settings, or `handler run … --binding <its name>`.
Its skill tells the agent how an app is laid out: a Svelte page, a small Deno backend with an
SQLite database, tests. The agent builds and tries the app in its sandbox (`deno task dev` shows a
preview), then tells you it is ready.

An agent can never put an app live: **only you deploy**.

## Deploy it

On the **Apps** page, **Add an app** with its folder, once (or `handler app add` in that folder).
From then on the page says when a new version is ready, with what it would be allowed to reach
(below), and a **Deploy** button (`handler app deploy NAME`).

A deploy runs the app's tests, then starts the new version on a copy of its data. If anything
fails, the app stays as it was and its log says why. **Roll back** returns to the previous version
and to its data as it was then: what changed since is lost, and the page says so. Removing an app
keeps its data.

## Open it

- **Open** on the Apps page, or `handler app open NAME`: the app opens in its own window
  (Firefox with a separate `handler-apps` profile, else Chromium's app mode, else your browser).
- A **keyboard shortcut** you choose on the Apps page (`handler app shortcut NAME "<Super>n"`),
  added to your GNOME shortcuts.
- Each app has its own address, `http://<name>.localhost:7430/`, reachable from this machine only.

An app runs only while it is used: opening it starts it (about a second), and it stops after
10 minutes without use.

## What an app may reach

By default nothing: no network, no file of yours. An app declares what it needs in its
`app.toml`, and the Apps page shows it before you deploy; a new version that asks for more is
confirmed first.

| Need | For | You give it |
|---|---|---|
| network hosts | a model server, a calendar server | nothing more: only those hosts are reachable |
| secrets | an API key, a password | its value, on the Apps page (`handler app secret NAME KEY`). The agent that writes the app never sees it |
| files | a calendar kept in a markdown file | the file or folder, read-only or not, inside your work folders |
| notifications | "coach has something for you" | nothing: they reach your desktop, your [inbox](cli/inbox.md) and your phone |

An app calls its own models, with the key you give it: Handler only lets it reach them.

## On your phone

With a [gateway](phone.md) set up, tick on the Apps page the persons who may use the app: you,
and family members you paired a phone for (theirs reach apps only, never your agents). The phone
lists the shared apps above the shared sessions.

When your machine is off, the phone shows the last copy of the app it got; actions fail with
"host offline", except those the app marks as able to wait: they are kept at the gateway (up to 7
days) and run when your machine is back, and the phone is notified of the answer.

## At a time

To have an app do something on its own (every weekday at 08:30, read the agenda and notify you),
make an [automation](automations.md) that calls one of its routes.

## See also

[`handler app`](cli/app.md) · [phone](phone.md) · [automations](automations.md) · how it is built:
[mini apps design](../dev/design/miniapps.md)
