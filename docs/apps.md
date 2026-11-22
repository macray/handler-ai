# Apps

An **app** is a small web app an agent writes for you: a tracker, a price calculator, a
coach that asks how your tasks are going. Handler runs it on your machine, and you use it from
your desktop (its own window) or from your phone, always the same app with the
same data: there is one copy of each app, on your machine, and nothing to sync.

## Apps from a source

**Library → Apps → Community** lists the apps the [sources](sources.md) offer: Handler's
(**Notes**, the actions and decisions found in your notes; **Tracker**, what you count with a
tap, and a coach looking at it), then those of a source you
added, each saying where it comes from (*Get apps* on the Apps page leads there). **Install**
opens its install page (below), like for any app. Handler keeps its code; when its source holds a
new version, the app's page says so (Settings → *Version*: what it changes and what it may reach
that it could not before) and **Update to** it gets it and deploys it (`handler app update NAME`);
Library → Apps → Community's **Update…** leads there.

**Apps**, in the menu, is where you open your apps: a card each; a click on it opens the app
(or, when it is not installed, its install page; when it still needs something, its page). On a
card, the gear opens the app's page and the pin puts it in the menu's *Pinned*. **Library → Apps** is where you manage them: a row each,
what it still needs (*Incomplete*, with **Fix**), a new version to deploy. Each app has its own
page (**Library → Apps**, or ⋯ → *Manage in Library* on Apps). Its header says its state
(running, or asleep until opened), its version and where it comes from, and what waits for you (a
version to deploy, something to give it); there: **Open** it, *Pin*, and its ⋯ (*Change it with
the App creator*, **Export**, *Stop it*, **Uninstall…**). Then two tabs:

- **Activity**, what it did, newest first, by day: its jobs' runs, each change to a folder it
  writes (its files and lines, **Undo**), what it sent you (its nudges, its messages), its
  versions deployed; a filter for each, and *Problems*. **Its log** (what its code printed) opens
  from there.
- **Settings**, what you chose, with an index: its *Version* (the one in use, the next one to
  deploy, a change waiting from the App creator, the one kept and **Go back**), *What it uses*
  (each folder and secret, **Change…**), *Who works* on its jobs (the app's, then each job's own),
  *What you can ask it*, *What it asks you* (its nudges), *Runs by itself* (each automation it
  proposes, made and turned on or off there), *Who can use it* (the phones it opens on) and *What
  it may touch*.

It opens on Settings while it still needs something, else on Activity. **Uninstall…** deletes the app, the data it
keeps for itself, its jobs' runs and what runs them by itself (the page says which first); the
folders you gave it stay. **Export**
first if you want to keep its code.

## Have an agent write one

In **Library → Apps → Community**, *Make your own* → **New app**: a session with the **App creator** starts
(the first time, its card opens there: choose who works, then **Turn on**; it gets the built-in
`app-builder` tool): tell it what the app should do. It works on a
**draft** Handler keeps, never a folder of yours. When it is ready, **Install it** (on the bar at
the top of the session, or under *Being written* in Library → Apps) opens its install page, and
the session ends: a later change is a new draft (*Change it*, below). When
the draft cannot be installed or opened, that bar says why; **Ask the App creator to fix it**
puts the reason in your message, for you to send.

**Change it with the App creator**, in the ⋯ of an app's page, starts a session with the App creator on a copy of the app's
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

In **Library → Apps → Community**, **Install from a file**: an app's file (a `.zip`, its export), or
`handler app add` in its folder. Handler keeps its own copy of its code: the file can go, and
changing the folder afterwards changes nothing until you add it again. Its **install page**
opens: one page with what it needs, in the app's own words, and beside it what it will be
allowed to do:

1. **The app's folder** ("Planner's folder", for the app Planner): a folder of yours, new or one
   you have (a project's too), in your work folders or your [notes](notes.md). The app and its
   jobs share it. A new folder named after the app is chosen for you (in your notes first when
   the app keeps notes in a known format), but you can pick another. Its other folders, if it
   has some, are offered the same way.
2. **Who works** on its jobs (the work it needs a model for, "Tells you what to do next"): a
   program on one of your accounts or an API key, and a model. What each job may reach is the
   app's, shown beside it; you choose who thinks.
3. **Its secrets**, kept by Handler.
4. **Runs by itself**: the automations it suggests, installed with it: each one says what it
   does, when it runs and who works, with a switch, on unless the app marks it optional. Switch
   off what you do not want before **Install**.
5. **On phones**: whose phones it opens on, when you have paired one.

**Install** does all of it, then deploys (its tests first). If a step fails, what was done is
kept and the page says where it stopped: open it again (**Install** on the app's row) and it goes
on from there (**Install** on the app's card or page). Nothing of yours is ever in an app's code, so an app written by your
agent, by you, or by someone else installs the same way. Cancel, before it was ever installed,
forgets it.

The file of an app you already have is its next version: its page then says a new version is
ready, with what it would be allowed to reach (below), and a **Deploy** button (`handler app
deploy NAME`).

**Export**, in the ⋯ of the app's page (`handler app export NAME`), gives its code as one file,
`NAME-VERSION.zip`, to share it or keep a copy: never its data, the folders you gave it, who
works on its jobs, its secrets or its runs. Whoever installs it gives it their own.

A deploy runs the app's tests, then starts the new version on a copy of its data. If anything
fails, the app stays as it was and its log says why. **Go back to** the previous version (Settings →
*Version*) returns to it and to its data as it was then: what changed since is lost, and the page says so. Removing an app
removes its parts with it (its jobs' runs, what runs them by itself); your files stay.

## Ask it

An app may say what you can ask it in a sentence: Tracker's *Log something I did* ("I drank
2 glasses of water"), *Say where each of my trackers is today*, *Look at my days and weeks*. Its page lists them under
**What you can ask it**, each with **Try**: its form, one real run, its answer in a sentence.

- **instant**: done by the app's code. It answers at once, and holds the app's rules (Tracker
  makes a tracker you do not have yet).
- **takes a while**: done by one of its jobs, which thinks about it: seconds or minutes, as
  the request needs. Its answer shows when it ends, and comes to your inbox too.

Handler's assistant, which picks the right ask from what you say (typed or spoken, from here or
your phone), is [Ask](ask.md).

## When it asks you to do something

An app may ask you to do something now and then: a work log asks you at the end of the day what
you did. It comes to your inbox, on the computer and your phone, and stays there, at the top,
until it is done:

- **Its form**, filled in by the app as far as it can (what it drafted from your day): correct
  it and **Send**, or press the microphone and say it ("I fixed the login bug and reviewed two
  pull requests"): what you say fills the form in, and nothing is sent until you press Send.
  Speaking needs a speech model ([Ask](ask.md#speaking)), and works on your own phone, not a
  family member's.
- Or **Open**, when what it asks needs the app's own page.
- It is **done** when what you sent worked, or when the app sees you did it another way. You can
  **Dismiss** it. Past its time, it shows as expired, with what that means for the app.

If you leave it, Handler reminds you, as often as the app says. Too often? **Reminders** on it:
*As the app says*, *No reminders* (it alerts you once), or *Never alert me* (it comes to your
inbox quietly), each saying what it means for this one. Not wanted at all? **⋯ → Stop these
nudges**: none come after it (this one stays until you send or dismiss it; **Turn back on**
undoes it). Both hold for that one thing the app asks, the next times too, and nothing else; the
app's page lists what it may ask you, each with its **On** switch and its reminders, to change
there too. Turned back on, it comes from its next time: none missed while it was off.

Some come at a time the app proposes ("Fridays at 16:00"): Handler sends them then, the app does
not. The app's page and the thing it asks say when; **Change** sets your own time (every day
at 09:00, another day, every 2 days), which holds for its next ones, and **Back to the app's**
undoes it. It comes while Handler runs: after your computer was off, only the latest missed
time comes, once. The app may look first whether there is anything to ask (nothing new this
week: nothing comes); if it fails to answer, your inbox says so. When the next one makes the
last one pointless (this week's log after last week's), the app may have the last one expire
when the next time comes, if you left it open: it shows as expired, not beside the new one.

What an app may ask you is written in its `app.toml`; it cannot ask you anything else, nor choose
how or how often you are told.

## Open it

- Its card on **Apps**, **Open** on its page, or `handler app open NAME`: the app opens in its own window
  (Firefox with a separate `handler-apps` profile, else Chromium's app mode, else your browser).
- Each app has its own address, `http://<name>.localhost:7430/`, reachable from this machine only.
  Its name (`planner`, the `name` of its `app.toml`) is what the CLI and its address use; the
  web UI shows its title (`title = "Planner"`), or its name when it has none.

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
| folders | where your tasks are kept, a calendar kept in a markdown file | a folder (or file) of yours, inside your home, for each one it names; read-only unless it says it writes it (`handler app folder NAME NEED PATH`, `--new` to make it). Never Handler's own files nor your keys. A folder it writes keeps its `.git` read-only, and has a history on the app's page (Activity): each change, and Undo ([notes](notes.md#see-what-changed-and-undo-it)) |
| notifications | "coach has something for you" | nothing: they reach your desktop, your [inbox](cli/inbox.md) and your phone |

**Documents of a known shape.** An app may keep its data as notes you also read and edit
yourself (a CV, a reading log), in markdown with a [schema](notes.md#documents-of-a-known-shape).
It brings the schemas it uses: they join your **Library → Schemas** when you install it (one
with the same `$id` already there but different stops the install, saying which: never two
shapes under one name), and stay there when the app goes. Handler reads and writes those
documents for the app, only in the folders you gave it, and only in those it may write: never
through a link to elsewhere. Its first change to a file you wrote by hand may change its blank
lines, never its words; the block at its top (between its `---` lines) stays as you wrote it.

**Its jobs** reach only what each one says, shown on the app's page ([below](#its-jobs)).

When the folder you give an app is a project's, the project's page lists the app (*Apps using
this folder*): you work in the project, the app works for you, on the same files. The app itself
stays in Apps.

## Its jobs

What needs judgment ("what matters most today?", "write a CV for this ad") is one of the app's
**jobs**: work it asks a model to do. The app brings each one's instructions, what it is given
and gives back, and what it may reach (the folders it reads or writes, the sites it may visit);
**you choose who works** on it: a program on one of your accounts or an API key, and a model.
No agent is set up for an app: its jobs are no agents of yours, and your agents stay yours.

- **At install**, *Who works* is chosen once for all the app's jobs. Later, the app's page
  lists **Its jobs**, each with its *Who works* (*as the app*, or its own: the pencil changes it,
  *Back to the app's Who works* undoes it) and its **Can do**, locked: what it reaches is the
  app's, set by its version, and a version that asks for more says so before you deploy it.
- **What cannot run it** is shown greyed, with why: the model alone (no program) cannot run a job
  that reaches folders or sites; a subscription whose terms refuse runs nobody follows cannot run
  one an automation runs. For those, an API key is recommended.
- **When it runs:** while the app answers **you** (a click of yours, on the computer or your
  phone), when you ask one of its actions (Try, Ask, a nudge's form), or from an automation; never
  on its own, never for a family member you share the app with. Its result goes back to the app,
  and to your inbox.
- **Its runs**, under its jobs on the app's page: the last ones, newest first, each with what
  started it (*by its code*, when you clicked in the app; *by Ask*, *Try* or *a nudge*; *by the
  automation …*), what it was asked (the values of its form, on one line), how it went, and the
  run itself, opened with a click.
- **Runs writing one folder take turns**, so two never change your files at once; those only
  reading it never wait. A job's folder it only reads is read-only to it.

## Automations it suggests

An app may suggest automations: Notes, "What's still open for you, weekdays at 9:00", running one
of its jobs; Planner, "Old days to the history, each night", calling one of its routes (its code,
no model: nobody works on it, no API key needed). They are installed with the app: its install page lists each one (what it does,
when it runs, who works) with a switch, **on** unless the app marks it optional (then off until you
switch it on), and **Install** makes and turns on those left on. While who works for it is a
subscription whose terms don't allow runs nobody follows, its switch is off and says so: choose an
API key in Who works and it is on again. A run by itself has nobody
following it: an API key is recommended for who works rather than your subscription (the page says
so). From the CLI, `handler app deploy` installing the app turns on none unless you say so: it
asks for each, or, with no terminal, takes those named with `--automation`; one that cannot be
turned on (its account's terms, say) is not offered, and it says why. Later, its page lists
them (*Runs by itself*), **Make it** creating one off. Its results open the app; turning one on or
off is yours, on its page, as for any [automation](automations.md).

In `app.toml`:

```toml
[[automations]]                   # up to 5
description = "What's still open for you, weekdays at 9:00"
when = { at = "09:00", days = ["mon", "tue", "wed", "thu", "fri"] }
run = { job = "plan" }            # one of its [jobs]; or run = { call = "POST /api/archive" }
optional = true                   # off at install until you turn it on (default: on)
```

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
