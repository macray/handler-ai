# handler app

Manage apps: small web apps an agent writes for you (a tracker, a dashboard), run by the
daemon on demand, each at its own address (`http://<name>.localhost:<port>/`).

## When to use it

- An app needs a folder or an agent of yours: give it one (`folder`, `agent`; `show` says what it
  needs).
- An agent changed an app's folder: give Handler its new code (`add`), put it live (`deploy`), or
  undo it (`rollback`).
- Share an app, or keep a copy: its code as one file (`export`), installed elsewhere with `add`.
- Open an app like a desktop program.
- Find why an app fails (`log`).

## Usage

```
handler app list
handler app add [PATH]
handler app add NAME --from SOURCE
handler app export NAME [-o FILE]
handler app show NAME
handler app folder NAME NEED PATH [--new]
handler app agent NAME NEED AGENT_ID
handler app deploy NAME [--yes]
handler app rollback NAME
handler app open NAME [--print]
handler app stop NAME
handler app log NAME
handler app secret NAME SECRET [--unset]
handler app uninstall NAME [--yes]
```

## Subcommands

| Subcommand | |
|---|---|
| `list` | your apps, their versions and state |
| `add [PATH]` | give Handler an app's code: an app file (a `.zip`, an export) or the folder holding its `app.toml` (default: the current folder), zipped without `.git` and `node_modules`. A new app, or the next version of one you have; then say what it needs. Handler keeps its own copy: changing the folder afterwards changes nothing until you `add` it again. With `--from SOURCE`: the app NAME a [source](source.md) offers (`official`: Handler's) |
| `export NAME` | its code as one file, `NAME-VERSION.zip` in the current folder (`-o FILE`: elsewhere). Never its data, what you gave it, its secrets or its runs |
| `show NAME` | what it needs, in its own words, and what you gave it: its folders, its agents (with those of yours that fit, by id), its secrets |
| `folder NAME NEED PATH` | give one of its folder needs a folder of yours (`--new`: make it). Its backend restarts with it |
| `agent NAME NEED AGENT_ID` | give one of its agent needs one of your agents that fits it (`show` lists them). A new one, set up from the app's own definition, is made in the web UI (the app's page) |
| `deploy NAME` | install its code as last added: run its tests and a health check on a copy of its data, then switch. Asks first when the new version may reach more than the old one; `--yes` does not ask |
| `rollback NAME` | back to the previous version, and its data as it was then |
| `open NAME` | open it in its own window by a one-time link: Firefox with a `handler-apps` profile, else Chromium's app mode, else the default browser (`HANDLER_APP_BROWSER=firefox\|chromium\|default` forces one). `--print`: only print the link |
| `stop NAME` | stop its backend now; it starts again when used |
| `log NAME` | its last deploys and its backend's output |
| `secret NAME SECRET` | set a secret the app declares (asked for, or from stdin); its backend restarts with it. `--unset` removes it |
| `uninstall NAME` | delete it: its code, the data it keeps for itself, its agents and what runs them; your folders stay. Says what goes and asks first; `--yes` does not ask |

## Examples

```bash
cd ~/apps/planner && handler app add   # says it needs a folder "tasks" and an agent "planner"
handler app add recipes-1.2.zip        # an app someone exported
handler app add planner --from official  # Handler's Planner
handler app folder planner tasks ~/planner --new
handler app agent planner planner 3f2a91c04b1e
handler app deploy planner
handler app open planner
handler app rollback planner            # the last deploy broke something
handler app export planner              # planner-0.3.1.zip, to send
```

## See also

[apps](../apps.md) · [`inbox`](inbox.md) (apps' notifications)
