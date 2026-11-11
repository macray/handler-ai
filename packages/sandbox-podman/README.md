# sandbox-podman — `handler-sandbox-podman`

**Implements:** contract A (sandbox), isolation `container`, on rootless podman, and its images
(A.7): the only block that calls podman (`tests/architecture`).
**Depends on:** `handler_contracts`, `handler_sandbox_kit` (the executable, the launch, the network filter); podman at runtime.
**Used by:** the control plane, **through the executable only** (never imported); the CLI runs
`attach`, the command handlerd gives it (D.16).

```
handler-sandbox-podman launch 3< spec.json  # stdio = the agent's stdio; stderr = logs + egress events
handler-sandbox-podman attach NAME          # a `tty` sandbox's process on this terminal (D.16)
handler-sandbox-podman set-egress NAME enforce|log-only
handler-sandbox-podman sweep
handler-sandbox-podman image build|inspect|read|tag|remove|pull …  # A.7
handler-sandbox-podman check                                   # A.8: can this host run sandboxes
handler-sandbox-podman cache size|clear …                      # A.9: cache folders, inner ids' files too
```

| File | Role |
|---|---|
| `cli.py` | the executable: the kit's `runtime_cli.main` given `Podman`, `images`, `caches` and `check.check` |
| `launch.py` | `Podman`, the kit's `Runtime` (`sweep` too: podman's leftovers of dead launchers): each need its podman way (one method each), and podman's verbs; the launch itself (refuse, create, run, clean up) is the kit's |
| `images.py` | the `image` verbs (A.7): build (id to a file), inspect, read a file without running the image, tag, remove (refused while a container mounts it), pull |
| `caches.py` | the `cache` verbs (A.9): sizes and emptying through `podman unshare` (inner podman's files are of subordinate ids); emptying refused while a sandbox mounts the folder or one inside it, or when it is a mount point here |
| `check.py` | the host check (A.8): rootless, subordinate ids, network backend, cgroups v2, /dev/fuse, WSL |
| `podman.py` | thin podman CLI helpers, labels, user namespace (keep-id) |
| (the filter) | in `handler_sandbox_kit` (`egress/`): this runtime runs it as a container on the sandbox's network, its image `localhost/handler-ai-proxy:2` built by `image build-proxy` (A.7), never by a launch |

Conformance: `tests/sandbox/conformance/` (what every runtime must do, run against this one as
`[podman]`); this runtime's own choices: `tests/sandbox/podman/`.
