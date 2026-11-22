# handler ask

Say what you want, in your words: Handler picks which of your apps does it (one of what you can
ask them), runs it, and says how it went. The same as the web UI's [Ask](../ask.md).

## When to use it

- To add something to your calendar, or ask what is planned, from a terminal.
- To try what an app can be asked, the way the assistant understands it.

## Usage

```
handler ask WORDS...
handler ask --listen [--toggle]
handler ask --listen --check
handler ask --history
```

```
$ handler ask Tomorrow I call the bank at 10
→ planner · add  (a call on a day)
Added Wednesday 21 October at 10:00: Call the bank.
```

When it needs to know more, it asks you: answer, or press Enter to stop. An app's job that
takes longer is waited for two minutes; after that its answer is in your inbox (`handler
inbox`). Ask's router is set up once, in the web UI: Chat → Ask.

## By voice

`--listen` records what you say instead: speak, press Enter (at most 30 seconds), and what was
heard is asked the same way. It needs a speech model (Settings → Expert → Voice) and the
computer's own recorder.

```
$ handler ask --listen
Listening… Enter to stop (at most 30 s).
you said: move the dentist to Monday 10:00
→ planner · move
Moved Dentist to Monday 23 November at 10:00.
```

`--toggle` is for a key, such as a Stream Deck's: a first press records, the next one stops it,
and how it went is a sound and a notification naming what was heard; what went wrong before
Handler answered is also a line of `~/.local/state/handler-ai/listen.log`. When Handler asks something back, the next press
records your answer (within two minutes). [Ask from a key](../ask.md#from-a-key-a-stream-deck)
says how to set the key up.

`--check` says what this computer will use to record, play the sounds and show notifications,
what is missing, and whether a speech model and Ask's router are set; it ends in failure when
something `--toggle` needs is missing. Run without a terminal (by a key), it also answers with a
sound and a notification.

## What you asked

`--history` lists your last asks, from anywhere (the web UI, your phone, here, a key), newest
first: when, from where, what Handler received, the app and action it went to, how it ended.
The same as the Ask tab's [what you asked](../ask.md#what-you-asked).

```
$ handler ask --history
2026-11-20 09:12  key       “add call the bank tomorrow”
                    → planner · add  ✓ Added Call the bank, Friday 21 November.
2026-11-20 09:10  key       “(nothing heard)”
                    ✕ Nothing was written down: the provider did not answer
```

## See also

[`app`](app.md) · [`inbox`](inbox.md)
