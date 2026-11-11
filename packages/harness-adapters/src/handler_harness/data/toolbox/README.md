# toolbox — `localhost/handler-ai-toolbox:latest`

The system agents work in, **independent of the harness**: every harness and tool image is
built `FROM` it. Handler generates its recipe from three owners' parts (contract B.7):

- **Handler's base** for the distro, `distros/<distro>/`: `base.containerfile` (what Handler and
  the harness recipes rely on, and the usual command-line tools) and `distro.toml` (the commands
  it gives, its caches). Fedora only, x86_64 and arm64.
- **System packages**, `system-packages/<name>/`: a piece of the system, what only root or the
  package manager can put in place (podman with its capabilities and configuration, chromium,
  gcc, wl-clipboard). Each has `package.toml` (`handler.system-package/v1`: what it provides, its
  caches), `install-<distro>.sh` (run as root at the build, its folder bind-mounted: nothing of
  it stays in the image) and `check.sh` (run in the built toolbox, as agents get it). The user's
  own are in `~/.config/handler-ai/system-packages/`, one named as a built-in one replacing it.
- **The user's lines**, `~/.config/handler-ai/toolbox/custom.containerfile`, appended last.

`toolbox.toml` here is the default handlerd writes to `~/.config/handler-ai/toolbox/` on its first
start: the distro and the system packages on (podman and wl-clipboard: what `nested` and
`display` sandboxes need). Afterwards Handler writes it on the user's actions (Settings → Sandboxes,
`handler toolbox`); the user's own caches are there too.

A toolbox build (`handler image rebuild toolbox`, or Settings → Sandboxes) applies a change with the
build cache, or updates the system (`--update`: pull, no cache); then each system package's
check, the commands the toolbox gives (the record), every need in use among them (Handler's, the
harnesses', the abilities of saved agents), then every harness and tool image rebuilt on it and
checked: all switch, or none.
