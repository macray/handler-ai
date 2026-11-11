# sandbox-kit — `handler_sandbox_kit`

**Implements:** the parts of contract A every sandbox runtime shares, in three parts: the runtime
framework (its executable: every verb, `runtime_cli.main`; the launch, `attach` and `sweep`; the
interfaces a runtime implements: `Runtime`, `Images`, `Caches`; a launcher's identity), the network
filter (`egress/`: A.3, A.4), and the relay (`relay/`: a sandbox's streams to the host where it
has no route to it, Apple container). The instance folder (`<XDG_RUNTIME_DIR>/handler-ai/sandboxes/<name>/`)
is the kit's alone (its names start with `_`): a runtime has `Instance.dir` for what its needs
prepare, `Instance.filter_dir` for its filter, `runtimes_dir()` for its own folders beside the
instance folders.
**Depends on:** `handler_contracts`.
**Used by:** the sandbox runtimes (`handler_sandbox_podman`, `handler_sandbox_docker`, `handler_sandbox_apple`), **by import**, and by nothing else
(`tests/architecture`): the control plane still reaches a runtime through its executable only.
How a runtime connects a sandbox to its filter (networks, sockets) stays the runtime's.

| File | Role |
|---|---|
| **the runtime framework** | |
| `runtime_cli.py` | every `handler-sandbox-<name>`: `main`, given the runtime's `Runtime`, its `images` and `caches` modules (the `Images`, `Caches` protocols: A.7, A.9, checked by `ty`) and its `check` (A.8); its verbs, their arguments and help, the spec on fd 3, `set-egress`/`set-allow` on a running sandbox's filter settings (A.4, the filter's folder from `launch.running_filter`) |
| `launch.py` | the launch every runtime shares: refuse (A1: the abilities, then the runtime's own refusals) → the instance folder → each need by the runtime's method → create → run (`tty`: wait for `attach`) → clean up (A4); `attach` (a `tty` sandbox's process on this terminal, the runtime's `start` and `stop`), `sweep` (the engine's leftovers by the runtime's `sweep`, then the instance folders); `Runtime`, the interface a runtime implements: one method per need (the arguments it adds to its engine's `create`), its engine's verbs; what the runtimes' needs share: `labels` (on what they create), `Instance.new_file`, `Instance.home_folder` |
| `launcher.py` | which launcher made a resource (`<pid>:<start time>`) and whether it still runs, for `sweep`: from /proc, or `ps` where there is none (macOS); the labels every runtime puts on what it creates |
| `caches.py` | the `cache` verbs (A.9) of an engine with Docker's CLI (Podman, Docker): `size`, and `clear` refused under a sandbox or a mount point; the runtime gives how `du` and `find` run where the inner ids' files are its own |
| `display.py` | the person's display a sandbox asking for one gets (A.6): the Wayland socket of the session the runtime runs in (`HANDLER_WAYLAND_SOCKET`, `WAYLAND_DISPLAY`, the only `wayland-*`); `check` declares `display` only where it finds one |
| `image_archive.py` | an OCI image archive (`image save`): its layers' files, and an image's folder unpacked from them, whiteouts applied (A.7 `extract` on Docker and Apple container) |
| **the network filter**: `egress/` | |
| `egress/__init__.py` | its host side: the filter's settings (allow-list, enforcement), secrets and arguments; its events → `handler-egress` lines on stderr; `proxy_dir()`, its own files below |
| `egress/proxy/Containerfile` | the filter's image (mitmproxy); its name and how it is built are the runtime's (A.7 `build-proxy`) |
| `egress/proxy/addon.py` | what the filter decides (mounted into it, self-contained: the image has no Handler): allowed, denied or unlisted per target, how each connection let through went (reached, or unreached and why), secret injections and leaks, settings read again when they change; `host.containers.internal` sent to `HANDLER_HOST_ADDRESS` when the runtime gives one |
| `egress/proxy/front.py` | in a filter's own sandbox the host reaches through a Unix socket only (Apple container): that socket, joined to the proxy's port |
| **the relay**: `relay/` | |
| `relay/__init__.py` | `handler-relay`'s host side: joins each stream to its target (a Unix socket here); `source_dir()`, its source and recipe |
| `relay/main.go` | `handler-relay`, in a sandbox with no route to the host but one socket the host connects to (Apple container): its listeners (the filter's proxy, handlerd's socket for an app) lead to the host, a connection per stream, asked for on a control connection; also runs the sandbox's command (signals, exit code). A static Go binary: it runs in any image |
| `relay/Containerfile` | builds it for the runtime's own Linux (a FROM scratch image holding `/handler-relay`, which the runtime exports to the host) |

Tests: `tests/` (decisions, events, injections; no container needed). The filter running in a
sandbox is tested by each runtime's conformance suite (`tests/sandbox/`).
