# sandbox-docker — `handler-sandbox-docker`

**Implements:** contract A (sandbox), isolation `container`, on Docker (a rootful engine on Linux,
or one in a VM: Docker Desktop, OrbStack, Colima), and its images (A.7): the only block that
calls docker (`tests/architecture`). A rootless engine on Linux is refused: its containers' uid 0
is the host user, so the agent would run as root or write files that are not the user's (A3).
**Depends on:** `handler_contracts`, `handler_sandbox_kit` (the executable, the launch, the network filter); docker at runtime.
**Used by:** the control plane, **through the executable only** (never imported), once chosen
(`handler runtime use docker`); the CLI runs `attach`, the command handlerd gives it (D.16).

```
handler-sandbox-docker launch 3< spec.json  # stdio = the agent's stdio; stderr = logs + egress events
handler-sandbox-docker attach NAME          # a `tty` sandbox's process on this terminal (D.16)
handler-sandbox-docker set-egress NAME enforce|log-only
handler-sandbox-docker sweep
handler-sandbox-docker image build|inspect|read|extract|tag|remove|pull …  # A.7
handler-sandbox-docker check                                   # A.8: which engine, what it gives
handler-sandbox-docker cache size|clear …                      # A.9: as root in a container
```

| File | Role |
|---|---|
| `cli.py` | the executable: the kit's `runtime_cli.main` given `Docker`, `images`, `caches` and `check.check` |
| `launch.py` | `Docker`, the kit's `Runtime` (`sweep` too: Docker's leftovers of dead launchers): each need its Docker way (one method each; where Docker differs from Podman, said there), and Docker's verbs; the launch itself is the kit's |
| `images.py` | the `image` verbs (A.7): build (BuildKit's steps as `STEP n/m` lines, id to a file; an image id given as a build argument named for the build, the name kept: BuildKit's `FROM` takes names only), inspect, read and extract without running the image, tag, remove, pull |
| `caches.py` | the `cache` verbs (A.9): `du` and `find` as root in a container of the filter's image (an inner engine's files are other ids'); emptying refused while a sandbox mounts the folder |
| `check.py` | the host check (A.8): the engine's kind (rootful, VM, rootless), limits, the display, the devices of `nested`; the abilities each kind gives |
| `docker.py` | thin docker CLI helpers, labels, the engine's kind, the user and subordinate ids |
| (the filter) | in `handler_sandbox_kit`: run as a container on Docker's bridge and the sandbox's `--internal` network, reaching the host as `host-gateway`; its image `localhost/handler-ai-proxy:2` built by `image build-proxy` |

Development only: `HANDLER_SANDBOX_DEV_ROOTLESS_DOCKER=1` uses a rootless engine anyway, the agent
as the container's root (the host user outside), where no other engine exists (an agent's own
sandbox). Never on a real host.

Conformance: `tests/sandbox/conformance/` (what every runtime must do, run against this one as
`[docker]` when an engine answers, or with `HANDLER_TEST_RUNTIMES=docker`); unit tests in
`tests/` here.
