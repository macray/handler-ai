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
- **Takes a while** actions are done by the app's agent: Ask says it is on it, and the answer
  comes when it ends, here and in your [inbox](automations.md).
- When it needs to know more ("which day?"), it asks you: answer in the same box.
- **Not this** opens another action, its form filled with what Ask understood, to run it instead.

An app's actions (what you can ask it) are offered to Ask unless you untick **Offered in Ask** on its page: then you only
try them there.

## Its router

Ask understands you with a model: its **router**, one of Handler's own agents, on the model
alone (one call, no file, no tool). The first time, the Ask tab shows its card: choose a model on a
[provider](configuration.md) (an API key, or a model on this computer), then **Turn on**. A
subscription is listed greyed: it cannot be called this way (*needs an API key*). Its instructions are yours to change, like any agent's; each question is one
run of it, which you can open to see how it decided.

What you ask is sent to that model with the list of what your apps can be asked; the answer
itself comes from the app, on your computer. Today's asks stay on the Ask tab in this browser;
older ones are in their app and your inbox.

## Speaking

Press the microphone of the Ask box, speak, and press it again (Esc drops it); on your phone,
hold it while you speak and let go to send (slide away to drop it). What you said is written
down and sent at once, marked with a microphone; if it was misheard, use **Not this** or say it
again. The answer is read aloud by your device's own voice when you spoke (and, if you like, when
you typed too). Up to a minute at a time.

Something has to write down what you say: choose it in **Settings → Expert → Voice**, one of your
providers' **speech models**. That can be a vendor's (Mistral's Voxtral, OpenAI, Groq: what you
say goes to their servers, and the page says so) or a server on this computer that speaks the
same API (vLLM, whisper.cpp's server, speaches): then nothing leaves your machine. The provider
templates *Mistral API*, *OpenAI API* and *Speech to text on this computer* include one; on
another provider, add the **Speech to text (Voice)** endpoint and tick **speech** on its model.
A speech model is never offered to agents. Until you choose one, the microphone leads to
Settings → Expert → Voice: nothing listens. Handler keeps neither the sound nor its text.
