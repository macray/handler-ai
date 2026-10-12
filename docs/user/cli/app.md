# handler app

Manage mini apps: small web apps an agent writes for you (a tracker, a dashboard), run by the
daemon on demand, each at its own address (`http://<name>.localhost:<port>/`).

## When to use it

- An agent changed an app: put the new version live (`deploy`), or undo it (`rollback`).
- Open an app like a desktop program, or from a keyboard shortcut.
- Find why an app fails (`log`).

## Usage

```
handler app list
handler app add [DIR]
handler app deploy NAME [--yes]
handler app rollback NAME
handler app open NAME [--print]
handler app shortcut NAME KEYS | --none
handler app stop NAME
handler app log NAME
handler app secret NAME SECRET [--unset]
handler app rm NAME
```

## Subcommands

| Subcommand | |
|---|---|
| `list` | registered apps, their versions and state |
| `add [DIR]` | register the app whose `app.toml` is in DIR (default: the current folder) |
| `deploy NAME` | install what its folder holds now: run its tests and a health check on a copy of its data, then switch. Asks first when the new version may reach more than the old one; `--yes` does not ask |
| `rollback NAME` | back to the previous version, and its data as it was then |
| `open NAME` | open it in its own window by a one-time link: Firefox with a `handler-apps` profile, else Chromium's app mode, else the default browser (`HANDLER_APP_BROWSER=firefox\|chromium\|default` forces one). `--print`: only print the link |
| `shortcut NAME KEYS` | a GNOME keyboard shortcut that opens it, e.g. `"<Super>n"`; `--none` removes it |
| `stop NAME` | stop its backend now; it starts again when used |
| `log NAME` | its last deploys and its backend's output |
| `secret NAME SECRET` | set a secret the app declares (asked for, or from stdin); its backend restarts with it. `--unset` removes it |
| `rm NAME` | unregister it; its data folder is kept |

## Examples

```bash
cd ~/apps/tracker && handler app add
handler app deploy tracker
handler app open tracker
handler app shortcut tracker "<Super>t"
handler app rollback tracker            # the last deploy broke something
```

## See also

[mini apps](../mini-apps.md) · [`inbox`](inbox.md) (apps' notifications)
