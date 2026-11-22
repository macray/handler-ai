# Ask

Say what you want, in your words: Handler picks which of your apps does it, runs it, and tells
you how it went.

> *I drank 2 glasses of water* → **tracker · Log something I did or had** → *Logged 2 glasses on
> Water: 6 of 8 glasses today.*

**Ask** is the **Ask** tab of Chat's page (and `handler ask "…"` in a terminal). It has a box of
its own: Chat's **Talk** tab is for talking with someone; Ask hands what you say to one of your
apps. You can also [speak](#speaking) instead of typing.

## What it can do

Only what your apps say you can ask them: each app's page lists it under **What you can ask
it**, and the Ask tab lists them all below its box. [Tracker](apps.md), one
of Handler's apps, can be asked to log something, say where your trackers are today, and look
at your days and weeks; Notes, to take a note, say what is still open, and answer from your
notes. Ask never does anything itself, never chains several things, and never invents an
app: when none does what you said, it says so, and **Start a chat about it** opens Chat's Talk tab
with your words in its box (or asks you who to talk to first, when you have no one yet). On your
phone it opens a new session on Chat, your words typed, the one you talked to last picked.

- **Instant** actions are done by the app's code: the answer comes at once.
- **Takes a while** actions are done by one of the app's jobs: Ask says it is on it, and the answer
  comes when it ends, here and in your [inbox](automations.md).
- When it needs to know more ("which day?"), it asks you: answer in the same box.
- **Not this** opens another action, its form filled with what Ask understood, to run it instead.

Each of an app's actions (what you can ask it) is offered to Ask unless you switch it off under
**In Ask** on the app's page; the box above the switches puts all of them in, or takes all of
them out. An action out of Ask is still tried there (**Try**), and still opened by the app's
nudges.

## Its router

Ask understands you with a model: its **router**, one of Handler's own agents, on the model
alone (one call, no file, no tool). The first time, the Ask tab shows its card: choose a model on a
[provider](configuration.md) (an API key, or a model on this computer), then **Turn on**. A
subscription is listed greyed: it cannot be called this way (*needs an API key*). Its instructions are yours to change, like any agent's; each question is one
run of it, which you can open to see how it decided.

What you ask is sent to that model with the list of what your apps can be asked; the answer
itself comes from the app, on your computer.

## What you asked

Under its box, the Ask tab lists what you asked, from anywhere: this page, your phone, the
terminal (`handler ask`) or a key ([below](#from-a-key-a-stream-deck)), by day, newest first.
Each ask shows what Handler received (the words it wrote down, with a microphone when you
spoke, and where it came from), which app and action it went to, how it ended (the app's
answer; for one that takes a while, once it ends), **Open** the app, and **How it decided** (the
router's run). An ask made elsewhere shows up at once. `handler ask --history` lists the same in a
terminal.

An ask that failed (Handler could not answer, nothing could be written down, the app's action
failed) or that no app does also goes to your [inbox](automations.md), with what you said and
why: silence never means it worked.

Handler keeps the words only, never the sound: the last 200 asks, 30 days at most. Delete one
with its **×**, all of them with **Clear**; **Stop keeping** turns the history off and empties it
(the tab then shows only what you ask on it, kept nowhere), **Keep a history** turns it back on.

## Speaking

Press the microphone of the Ask box, speak, and press it again (Esc drops it); on your phone,
hold it while you speak and let go to send (slide away to drop it). What you said is written
down and sent at once, marked with a microphone; if it was misheard, use **Not this** or say it
again. The answer is read aloud by your device's own voice when you spoke (and, if you like, when
you typed too). Up to a minute at a time. When nothing could be written down, that is in
[what you asked](#what-you-asked) too.

Something has to write down what you say: choose it in **Settings → Expert → Voice**, one of your
providers' **speech models**. That can be a vendor's (Mistral's Voxtral, OpenAI, Groq: what you
say goes to their servers, and the page says so) or a server on this computer that speaks the
same API (vLLM, whisper.cpp's server, speaches): then nothing leaves your machine. The provider
templates *Mistral API*, *OpenAI API* and *Speech to text on this computer* include one; on
another provider, add the **Speech to text (Voice)** endpoint and tick **speech** on its model.
A speech model is never offered to agents. Until you choose one, the microphone leads to
Settings → Expert → Voice: nothing listens. Handler never keeps the sound; the words, only in
[what you asked](#what-you-asked).

### From a key (a Stream Deck)

`handler ask --listen --toggle` lets a key ask by voice: press it, speak, press it again. You
hear a short beep when it listens, a short "got it" when the second press stops it, then how it
went; the notification names the app, the action and what was heard ("Heard: …"), so a word
misheard shows at once:

| You hear | And see |
|---|---|
| a rising beep | nothing: it listens (30 seconds at most) |
| a short falling blip | nothing yet: got it, Handler is on it |
| two rising notes | done: the app's answer; for an action that takes a while, that its job is on it (its answer comes to your inbox) |
| two same notes | done, with something to read (a clash, "which one?") |
| a question-like pair | Handler asks you something: press again, say the answer, press again (within two minutes) |
| two falling notes | why it did not work: nothing heard, no app does that, voice is off, no router, Handler not answering, the listener failing |

Each ask Handler received is in [what you asked](#what-you-asked) (and in `handler ask
--history`), with how it ended. What went wrong before Handler answered (no recorder, Handler not
running, the listener failing) is a line of `~/.local/state/handler-ai/listen.log` instead, never
with what you said.

Run `handler ask --listen --check` first: it says what this computer is missing (on Linux, a
recorder: PipeWire's `pw-record`, PulseAudio's `parecord` or ALSA's `arecord`; for notifications,
`notify-send`). Give it to the key once too: run by the key, it answers with a sound and a
notification, for the key's own setup (a Flatpak's, say) is not your terminal's. Nothing runs
between presses, and the key writes nothing you say to disk: the sound is sent to your speech
model and dropped, a question's exchange stays in memory until it ends, and only Handler keeps
the words, in [what you asked](#what-you-asked).

- **StreamController** (Linux): a key with the *Run Command* action, its command
  `handler ask --listen --toggle` (the full path, as `command -v handler` gives it, when the key
  does not find it). StreamController installed as a Flatpak runs it outside its sandbox with
  `flatpak-spawn --host handler ask --listen --toggle` (allow it to talk to
  `org.freedesktop.Flatpak`, in Flatseal for instance).
- **Elgato's Stream Deck app** (macOS): a key that runs the same command, through a small script
  it opens. The first time, macOS asks whether the app that runs it may use the microphone.
  Not tried yet on a Mac.
- **WSL** (Elgato's app on Windows, `wsl.exe -e handler ask --listen --toggle`): written, not
  tested; sounds through WSLg, no notification.
