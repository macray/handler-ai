# Apps

An **app** is a small web app an agent writes for you: a tracker, a price calculator, a
coach that asks how your tasks are going. Handler runs it on your machine, and you use it from
your desktop (its own window) or from your phone, always the same app with the
same data: there is one copy of each app, on your machine, and nothing to sync.

## Apps from a source

**Library → Apps → Get more** lists the apps the [sources](sources.md) offer: Handler's
(**Notes**, the actions and decisions your Scribe agent finds in your notes; **Tracker**, what you
count with a tap, and a Coach agent looking at it), then those of a source you
added, each saying where it comes from (*Get apps* on the Apps page leads there). **Install**
opens its install page (below), like for any app. Handler keeps its code; when its source holds a
new version, Get more offers it (**Get it**), and the app's page then offers to deploy it.

**Apps**, in the menu, is where you open your apps: a card each; a click on it opens the app
(or, when it is not installed, its install page; when it still needs something, its page). On a
card, the gear opens the app's page and the pin puts it in the menu's *Pinned*. **Library → Apps** is where you manage them: a row each,
what it still needs (*Incomplete*, with **Fix**), a new version to deploy. Each app has its own
page: open it, what you gave it
(each folder, agent and secret with its value and **Change…**), what you can ask it, what runs by
itself, *Under the hood* (its code, the version before it, its agents, its log), what it may
touch, the phones it opens on, and **Uninstall** last: it deletes the app, the data it keeps
for itself and its agents (the page says which first); the folders you gave it stay. **Export**
first if you want to keep its code.

## Have an agent write one

In **Library → Apps → Get more**, *Make your own* → **New app**: a session with the **App creator** starts
(the first time, its card opens there: choose who works, then **Turn on**; it gets the built-in
`app-builder` tool): tell it what the app should do. It works on a
**draft** Handler keeps, never a folder of yours. When it is ready, **Install it** (on the bar at
the top of the session, or under *Being written* in Library → Apps) opens its install page, and
the session ends: a later change is a new draft (*Change it*, below). When
the draft cannot be installed or opened, that bar says why; **Ask the App creator to fix it**
puts the reason in your message, for you to send.

**Change it**, on an app's page, starts a session with the App creator on a copy of the app's
code. While the draft waits, the app's page says so: **Continue** the session, **Throw away**
the draft, or **Use it**: its code becomes the app's next version, deployed at once (when it may
reach more than before, the page asks first). The app as you use it is untouched until then. One
draft per app at a time.

**Open the draft** (on that bar, or on the session's) tries it first: the app as the draft
makes it opens in a new tab, at its own address, a striped banner on each page. It works on
copies taken when you open it: its data, and the folders you gave it (a folder over 64 MB is used
read-only instead); what you do there changes neither the app nor your files. Open it again for
fresh copies; it closes when you use the draft or throw it away. Changing an app from a source this way makes it yours: its source no
longer offers it a new version.

Any agent can write one too: give it the built-in `app-builder` tool in its settings (it needs no
setting), or `handler run … --tool app-builder`. It brings Bun, the runtime apps run on. Its skill tells the agent
how an app is laid out: a Svelte page, a small backend run by Bun with an SQLite database, tests.
The agent builds and tries the app in its sandbox (`bun run dev` shows a preview), then tells you
it is ready.

An agent can never put an app live: **only you deploy**.

## Give it what it needs, deploy it

In **Library → Apps → Get more**, **Install from a file**: an app's file (a `.zip`, its export), or
`handler app add` in its folder. Handler keeps its own copy of its code: the file can go, and
changing the folder afterwards changes nothing until you add it again. Its **install page**
opens: one page with what it needs, in the app's own words, and beside it what it will be
allowed to do:

1. **Where it keeps your files** ("Where your calendar is kept"): a folder of yours, new or one
   you have (a project's too). The app and its agent share it.
2. **Its agents** ("Tells you what to do next"): set up from what the app brings (you choose what
   it runs on), or one of yours that fits. Set up there, it is one of the app's parts.
3. **Its secrets**, kept by Handler.
4. **Runs by itself**: the automations it suggests, each off unless you switch it on.
5. **On phones**: whose phones it opens on, when you have paired one.

**Install** does all of it, then deploys (its tests first). If a step fails, what was done is
kept and the page says where it stopped: open it again (**Install** on the app's row) and it goes
on from there (**Install** on the app's card or page). Nothing of yours is ever in an app's code, so an app written by your
agent, by you, or by someone else installs the same way. Cancel, before it was ever installed,
forgets it.

The file of an app you already have is its next version: its page then says a new version is
ready, with what it would be allowed to reach (below), and a **Deploy** button (`handler app
deploy NAME`).

**Export**, at the top of the app's page (`handler app export NAME`), gives its code as one file,
`NAME-VERSION.zip`, to share it or keep a copy: never its data, the folders and agents you gave
it, its secrets or its runs. Whoever installs it gives it their own.

A deploy runs the app's tests, then starts the new version on a copy of its data. If anything
fails, the app stays as it was and its log says why. **Go back to** the previous version (under
*Under the hood*) returns to it and to its data as it was then: what changed since is lost, and the page says so. Removing an app
removes its parts with it (its agents, what runs them by itself); your files and its data stay.

## Ask it

An app may say what you can ask it in a sentence: Tracker's *Log something I did* ("I drank
2 glasses of water"), *Say where each of my trackers is today*, *Look at my days and weeks*. Its page lists them under
**What you can ask it**, each with **Try**: its form, one real run, its answer in a sentence.

- **instant**: done by the app's code. It answers at once, and holds the app's rules (Tracker
  makes a tracker you do not have yet).
- **takes a while**: done by its agent, which thinks about it: seconds or minutes, as the
  request needs. Its answer shows when it ends, and comes to your inbox too.

Handler's assistant, which picks the right ask from what you say (typed or spoken, from here or
your phone), is [Ask](ask.md).

## Open it

- Its card on **Apps**, **Open** on its page, or `handler app open NAME`: the app opens in its own window
  (Firefox with a separate `handler-apps` profile, else Chromium's app mode, else your browser).
- Each app has its own address, `http://<name>.localhost:7430/`, reachable from this machine only.

An app runs only while it is used: opening it starts it (about a second), and it stops after
10 minutes without use.

## What an app may reach

By default nothing: no network, no file of yours. An app declares what it needs in its
`app.toml`, and its install page shows it before you deploy; a new version that asks for more is
confirmed first. An installed app's page says what it may reach (*What it may touch*).

| Need | For | You give it |
|---|---|---|
| network hosts | a model server, a calendar server | nothing more: only those hosts are reachable |
| secrets | an API key, a password | its value, on the app's page (`handler app secret NAME KEY`). The agent that writes the app never sees it |
| folders | where your tasks are kept, a calendar kept in a markdown file | a folder (or file) of yours, inside your home, for each one it names; read-only unless it says it writes it (`handler app folder NAME NEED PATH`, `--new` to make it). Never Handler's own files nor your keys |
| notifications | "coach has something for you" | nothing: they reach your desktop, your [inbox](cli/inbox.md) and your phone |
| agents | a planner's "what matters most today?" asks your Planner agent | an agent for each one it names: **Set up a new one** from what the app brings (its instructions, its form, its result: you choose its model), or one of yours that fits (`handler app agent NAME NEED AGENT_ID`) |

**An agent the app needs.** The app brings what that agent must be: what it does, what it is
given (its form) and what it gives back (its result). *Set up a new one* opens the agent's
settings filled with it: choose its model, change what you want, save; it is given to the app,
and it is your agent like any other (you can talk with it, an automation can run it). Or pick one
of yours: only those that fit are offered, those whose form takes what the app sends and whose
result gives what the app reads, and that work in the folder you gave the app for them. The
agent's settings list the apps that use it (*Used by apps*), and deleting it says which ones stop.
If you later change its form, or delete it, the app's page says it no longer fits.

An app calls its own models, with the key you give it: Handler only lets it reach them. Or it
runs one of your **agents**, with its own tools and settings:

- only while it answers **you**: a click of yours, on the computer or your phone. Never on its
  own (an agent on a schedule is your [automation](automations.md)), never for a family member
  you share it with;
- the run is like one you start with the agent's *Run* button: a session of the agent, listed
  with its runs ("by the app planner"), on its model;
- its result goes back to the app, and to your inbox with an **Open planner** button, in case you
  closed the app meanwhile;
- one run of an agent at a time: a second one waits for the first, at most 30 minutes.

## An app and an agent on the same data

An agent that keeps your calendar and tasks in its folder, and tells you what to do next every few
hours (an [automation](automations.md)), and an app to see and change them, on your computer and
your phone: the app asks for one folder, which it reads and writes, and its agent works there. It
is the same folder, no copy: what you tick in the app is what the agent reads at its next run.
The install page gives both at once; afterwards, the app's page changes them.

The agent set up for an app is one of the app's **parts**: listed on its page only (*How it
works*), never among your projects' agents nor *Agents outside projects*, started only by the app (what
you ask it, its screen, what it runs by itself), and uninstalled with it, with what runs it by
itself. Open it from there to read its runs, change its settings or improve it.

When the folder you give an app is a project's, the project's page lists the app (*Apps using
this folder*, and when its agent last ran there): you work in the project, the app works for you,
on the same files. The app itself stays in Apps.

- Simple changes (done, read, postpone to tomorrow) are the app's: instant, no model.
- What needs judgment ("what matters most today?") is a run of the agent from the app.
- What the agent already told you, it writes in its folder too, and reads at the next run: say so
  in its instructions, so it does not tell you the same things again.
- In the automation, *Its results open* the app: each result in your inbox opens it.

## Automations it suggests

An app may suggest automations: Notes, "What's still open for you, weekdays at 9:00", running the agent
you gave it. Its install page lists them, each off unless you switch it on (then made and turned
on at Install); later, its page lists them (*Runs by itself*), **Make it** creating one off. Its results
open the app; turning one on or off is yours, on its page, as for any
[automation](automations.md).

## On your phone

With a [gateway](phone.md) set up, tick on the app's page the persons who may use the app: you,
and family members you paired a phone for (theirs reach apps only, never your agents). The phone
lists the shared apps above the shared sessions.

When your machine is off, the phone shows the last copy of the app it got; actions fail with
"host offline", except those the app marks as able to wait: they are kept at the gateway (up to 7
days) and run when your machine is back, and the phone is notified of the answer.

## At a time

To have an app do something on its own (every weekday at 08:30, read the agenda and notify you),
make an [automation](automations.md) that calls one of its routes.

## See also

[`handler app`](cli/app.md) · [phone](phone.md) · [automations](automations.md) · every key of
`app.toml`: [`handler.app.v1`](../schemas/handler.app.v1.schema.json)
