# handler ask

Say what you want, in your words: Handler picks which of your apps does it (one of what you can
ask them), runs it, and says how it went. The same as the web UI's [Ask](../ask.md).

## When to use it

- To add something to your calendar, or ask what is planned, from a terminal.
- To try what an app can be asked, the way the assistant understands it.

## Usage

```
handler ask WORDS...
```

```
$ handler ask Tomorrow I call the bank at 10
→ planner · add  (a call on a day)
Added Wednesday 21 October at 10:00: Call the bank.
```

When it needs to know more, it asks you: answer, or press Enter to stop. An app's agent that
takes longer is waited for two minutes; after that its answer is in your inbox (`handler
inbox`). Ask's router is set up once, in the web UI's Ask page.

## See also

[`app`](app.md) · [`inbox`](inbox.md)
