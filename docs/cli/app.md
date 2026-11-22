# handler app

Manage apps: small web apps an agent writes for you (a tracker, a dashboard), run by the
daemon on demand, each at its own address (`http://<name>.localhost:<port>/`).

## When to use it

- An app needs a folder of yours: give it one (`folder`; `show` says what it needs). Who works
  on its jobs is chosen on its install page or its page in the web UI.
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
handler app deploy NAME [--yes] [--automation AUTOMATION]...
handler app update NAME [--yes]
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
| `list` | your apps, their versions and state, and where each comes from (`FROM`): a [source](source.md)'s id, or `yours` (added from a file or a draft: no source offers it a new version, `add` its next one) |
| `add [PATH]` | give Handler an app's code: an app file (a `.zip`, an export) or the folder holding its `app.toml` (default: the current folder), zipped without `.git` and `node_modules`. A new app, or the next version of one you have; then say what it needs. Handler keeps its own copy: changing the folder afterwards changes nothing until you `add` it again. With `--from SOURCE`: the app NAME a [source](source.md) offers (SOURCE: its id, `official` for Handler's, or its URL) |
| `export NAME` | its code as one file, `NAME-VERSION.zip` in the current folder (`-o FILE`: elsewhere). Never its data, what you gave it, its secrets or its runs |
| `show NAME` | what it needs, in its own words, and what you gave it: its folders, its secrets |
| `folder NAME NEED PATH` | give one of its folder needs a folder of yours (`--new`: make it). Its backend restarts with it |
| `deploy NAME` | install its code as last added: run its tests and a health check on a copy of its data, then switch. Asks first when the new version may reach more than the old one; `--yes` does not ask. Installing it (no version installed yet), it lists the automations the app suggests and turns on none unless you say so: on a terminal it asks for each (`Turn on NAME: WHEN, runs its job JOB? [y/N]`); otherwise only those named with `--automation NAME` (repeatable) are made and turned on, once the deploy succeeded. One that cannot be turned on (its Who works' account's terms refuse runs nobody follows, say) is not offered and it says why; named, it is an error before deploying. The others: make one later from the app's page in the web UI |
| `update NAME` | an app from a [source](source.md): the version its source offers (`show` says it, with what it changes), taken as `add --from` takes it, then deployed as `deploy` does. Asks first when it may reach more than the installed version; `--yes` does not ask. If the deploy fails, the installed version runs on and the one taken waits, ready to `deploy` |
| `rollback NAME` | back to the previous version, and its data as it was then |
| `open NAME` | open it in its own window by a one-time link: Firefox with a `handler-apps` profile, else Chromium's app mode, else the default browser (`HANDLER_APP_BROWSER=firefox\|chromium\|default` forces one). `--print`: only print the link |
| `stop NAME` | stop its backend now; it starts again when used |
| `log NAME` | its last deploys and its backend's output |
| `secret NAME SECRET` | set a secret the app declares (asked for, or from stdin); its backend restarts with it. `--unset` removes it |
| `uninstall NAME` | delete it: its code, the data it keeps for itself, its jobs' runs and the automations running them; your folders stay. Says what goes and asks first; `--yes` does not ask |

## Examples

```bash
cd ~/apps/planner && handler app add   # says it needs a folder "tasks"
handler app add recipes-1.2.zip        # an app someone exported
handler app add tracker --from official  # an app Handler's source offers
handler app folder planner tasks ~/planner --new
handler app deploy planner              # asks for each automation it suggests
handler app deploy planner --automation planner-what-to-do-next  # a script: that one on
handler app open planner
handler app update tracker             # the version its source offers now
handler app rollback planner            # the last deploy broke something
handler app export planner              # planner-0.3.1.zip, to send
```

## See also

[apps](../apps.md) · [`inbox`](inbox.md) (apps' notifications)
