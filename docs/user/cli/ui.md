# handler ui

Open the web UI in your browser.

## When to use it

Every time you want the web UI: the link it opens carries the UI's access token, so you are let in
(the bare address asks for the token). The token stays in the URL fragment, which browsers never
send to a server.

## Usage

```
handler ui [--print]
```

## Options

| Option | |
|---|---|
| `--print` | only print the link, e.g. to open it in another browser |
