# Handler and Meta Muse

[Muse](https://about.fb.com/news/2026/09/introducing-muse-personal-ai-agent/) is Meta's personal
agent (September 2026): you ask it in a sentence, and it does the work, sending an email, booking
a table, filling a form, buying, over your connected apps or in a browser. It is not a coding
tool, and it is not a sandbox for one: it compares with Handler's [apps](../apps.md),
[Ask](../ask.md) and [automations](../automations.md), the part of Handler that does things for
you day to day.

The ideas are close: a box for the agent, a gate between it and the internet, a question before
it acts, a record of what it did. The difference is who holds them: Muse runs in Meta's cloud, on
Meta's model, with your data there; Handler runs on your computer, on your models, and does only
what your apps say.

The facts on Muse come from Meta's announcement and press coverage, read on 2026-11-23.

## In short

- **Pick Muse** for an assistant that does almost anything with no setup: forty connectors, a
  browser for sites without one, payments, apps for your phone and computer, WhatsApp. It decides
  how to do what you ask.
- **Pick Handler** to keep your data and the box on your own computer, choose the model (your
  subscription, an API key, a model on your machine), and know in advance what each thing may
  reach: an app does only what it was written to do, and you see what it may touch before you
  install it. Its apps are yours: their code, their data in your folders, and what they ask you
  comes to your inbox as a form. You need more setup, and an agent writes the apps you lack.

## Side by side

| | Meta Muse | Handler (apps, Ask, automations) |
|---|---|---|
| **What it is** | One agent that does what you ask, its own way | Apps you install or have an agent write (a tracker, a planner, a CV assistant), each doing a few things; **Ask** hands your sentence to the app that does it, and never invents one |
| **Where it runs** | A virtual machine per person in Meta's cloud, holding the agent and your data ("Muse Secure VM") | Your computer: each app and each of its jobs in a box of its own. Its data in your folders, as files you can read |
| **The gate on the internet** | "Sentinel", a second agent on the same machine, kept apart from Muse: nothing reaches the internet unless it approves; it asks you when needed | Fixed before it runs: an app reaches only the sites written in its `app.toml`, shown before you install it; a new version asking for more asks you first. By default, no network |
| **Before it acts** | Stops and asks before what is hard to undo: an email, a purchase | An app says what it may ask of you (a form, with **Send**); a job reaches only the folders and sites it declares. What changes in a folder can be seen and undone |
| **What you see after** | A running log of what it did and plans to do | Each app's runs (what started it, what it was asked, how it went, the run itself), what you asked Ask and where it went, the history of each folder it writes |
| **Things with their own screen** | Made by Muse in a conversation and kept in its **Library** (documents, spreadsheets, dashboards, interactive tools, per reviews); **Goals** it tracks with a to-do list; a **Feed** of briefs it writes for you (news, your schedule, mail). Inside Muse, on Meta's side; what each may reach is Muse's | [Apps](../apps.md) you install from a source or have an agent write: each kept, with its own page and window, its data in your folders, what you can ask it, its jobs, and everything it may reach shown before you install it. On the computer and the phone |
| **When it needs you** | Its approvals queue, beside what is coming up (**Upcoming**): allow once, for the task, for a while or always; it comes back when a goal needs a decision, and checks in on its own on long goals | Your inbox, on the computer and the phone: an app's request stays at the top until done, with its form filled in as far as the app can (or by voice), nothing sent until you press **Send**; reminders you set, a time you can change, **Stop these nudges** |
| **Your accounts** | About forty connectors (Google Workspace, Dropbox, Notion…) and Zapier; read-only or full access each; a browser for the rest; logins kept away from the agent, 1Password coming | What an app declares: its sites, its folders, its secrets, which you enter on its page; the agent that writes an app never sees them. Fewer services today; agents also get [tools](../tools.md) (a Shopify store, a browser) |
| **Paying** | Purchases through Link by Stripe, card details hidden | None |
| **Memory** | Learns your preferences, which you can tell it to forget | [Notes](../notes.md): plain markdown folders of yours, read by the apps and agents you choose |
| **The model** | Meta's (Muse Spark) | Yours: a subscription, an API key, or a model on your computer, chosen per app or job |
| **On its own** | Keeps working in the background, and comes back when something changes | Runs when you ask or when an automation you turned on says so (every weekday at 9:00): never on its own |
| **Phone** | Apps for iPhone and Android, the web, a Mac app, WhatsApp | A gateway you host, end-to-end encrypted: it cannot read what it relays; apps and Ask from the phone, and family members you pair (apps only) |
| **Your data and Meta** | Not used for ads; use for training unless you opt out; a VM encrypted with your own key announced | No company in the middle: open source (Apache-2.0), on your computer |
| **Cost, where** | Free with limits; paid plans (reported from $16 to $100 a month); US and Canada | Free; you pay your model, if any. Linux; macOS and Windows (WSL 2) experimental |

## Apps and the inbox

**Muse** makes things as you talk to it: a document, a dashboard, a training plan, a tool, kept
in its Library; goals it follows and checks in on; a feed of briefs. They live inside Muse, on
Meta's side, and work through Muse: what each may reach is what Muse may reach. When it needs you,
it is a question from Muse (an approval, a decision), in its queue.

**Handler** has apps: small web apps you install, or an agent writes for you, each with its page,
its window, its data in your folders, and the few things you can ask it (by [Ask](../ask.md),
typed or spoken). Each says what it may reach, and you see it before installing; a new version
asking for more asks you first. When an app needs you (what you did today, a choice to make), it
comes to your inbox as its own form, filled in as far as it can, and stays there until done; how
often you are reminded is yours to choose.

The facts on Muse's screens come from reviews of the app: Meta's help pages do not describe them.

## Who controls what

**Muse** decides how to do what you ask: which service, which site, what to click. Its limits are
its own: the Sentinel's judgment, the questions it chooses to ask you, the access you gave each
connector. It is fast to start, and it can do things nobody planned for; what it may do next is
for Meta's agents to decide, on Meta's computers.

**Handler** decides nothing beyond what is written. An app is code you can read, whose
`app.toml` lists every site, folder and secret it may use; a job that thinks reaches only what it
declares; Ask picks among what your apps say they do, and when none does, it says so. Nothing runs
unless you or an automation you turned on starts it. It is slower to start: an app does one kind
of thing, and for a new one, an agent writes it, in a box, and you install it. In exchange, what
it may do is known before it runs, and it all stays on your computer.
