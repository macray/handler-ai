# handler ui

Open the web UI in your browser, signed in.

## When to use it

The first time, in each browser you use Handler in: the link it opens signs that browser in, and
it stays signed in (for a year), so a bookmark of `http://127.0.0.1:7430` (the port: `HANDLER_PORT`) opens Handler from then
on, in any tab, after a restart too. Run it again when a browser asks you to (another browser, a
new profile, after clearing its cookies).

The link works once, within two minutes; the daemon's access token itself never reaches the
browser.

## Usage

```
handler ui [--print]
```

## Options

| Option | |
|---|---|
| `--print` | only print the link, e.g. to open it in another browser |
