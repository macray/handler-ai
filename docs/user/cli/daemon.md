# handler daemon

Check, install, remove and read the log of `handlerd`, the daemon that runs your agents, as a
systemd user service started with your session.

## When to use it

- A command cannot reach the daemon: `handler daemon status`, then `handler daemon log`.
- After an update, to check the version running.
- To remove the service, or see the unit it writes.

[`setup`](setup.md) installs and starts the service already.

## Usage

```
handler daemon status
handler daemon install [--dry-run]
handler daemon uninstall
handler daemon log [-f]
```

## Subcommands

| Subcommand | |
|---|---|
| `status` | `handlerd 0.1.0 up at http://127.0.0.1:…`; if it does not answer, the service's state (exit code 1) |
| `install` | write the unit (`~/.config/systemd/user/handler-ai.service`), enable and start it. `--dry-run`: print the unit instead |
| `uninstall` | stop and disable it, remove the unit. Your configuration and state are kept |
| `log` | its last 200 log lines (`journalctl --user -u handler-ai`); `-f`, `--follow`: keep printing new ones |

## See also

[`setup`](setup.md)
