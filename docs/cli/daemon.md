# handler daemon

Check, install, remove and read the log of `handlerd`, the daemon that runs your agents, as a
user service started with your session: a systemd user service on Linux, a launchd agent on
macOS.

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
| `status` | `handlerd 0.3.0 up at http://127.0.0.1:…`; if it does not answer, the service's state (exit code 1). Without systemd: "no systemd here: handlerd's log is wherever you started it" |
| `install` | write the service (`~/.config/systemd/user/handler-ai.service`; on macOS `~/Library/LaunchAgents/ai.handler.handlerd.plist`), enable and start it. The service gets the variables of your shell that say where Handler keeps its files and listens (`HANDLER_PORT`, `HANDLER_CONFIG_DIR`…, the `XDG_…_HOME` folders, `HOME` when it is not your account's, `DOCKER_HOST`), and the folder of the `podman`, `docker` or `container` your shell finds: the service is then the `handlerd` your `handler` talks to. `--dry-run`: print it instead |
| `uninstall` | stop and disable it, remove the unit. Your configuration and state are kept |
| `log` | its last 200 log lines (`journalctl --user -u handler-ai`; on macOS `~/Library/Logs/handler-ai/handlerd.log`); `-f`, `--follow`: keep printing new ones. Without systemd, `handlerd`'s log is in the terminal you started it in |

## See also

[`setup`](setup.md)
