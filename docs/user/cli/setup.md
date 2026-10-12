# handler setup

Turn an installed `handler` into a working one: start the daemon, check the machine, build the
images.

## When to use it

- Right after installing.
- Whenever something seems wrong: it is safe to run again, and says what the machine lacks.

## Usage

```
handler setup [--no-build] [--yes]
```

It goes through, in order:

1. installs `handlerd` as a systemd user service and starts it ([`daemon install`](daemon.md));
2. checks the machine (rootless Podman, `passt`…): fix each `FAIL` line, then run it again;
3. builds the network filter if it is missing (about 240 MB, a minute or two);
4. builds the images if the base image is not built yet: the toolbox (about 2.5 GB), then one image
   per harness (a while; asks first);
5. prints where the web UI is.

## Options

| Option | |
|---|---|
| `--no-build` | skip the images; build them later with `handler image rebuild toolbox` |
| `--yes` | build the images without asking |

## See also

[`daemon`](daemon.md) · [`image`](image.md) · [`ui`](ui.md)
