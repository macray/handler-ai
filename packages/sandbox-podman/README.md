# sandbox-podman — `handler-sandbox-podman`

**Implements:** contract A (sandbox), isolation `container`, on rootless podman, and its images
(A.7): the only block that calls podman (`tests/architecture`).
**Depends on:** `handler_contracts`; podman at runtime.
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
| `cli.py` | command line, reads the SandboxSpec from fd 3 |
| `launch.py` | the lifecycle: refuse (A1) → network → create → attach (with `tty`: wait for the client's `attach`) → clean up (A4) |
| `egress.py` | the proxy's settings (allow-list, enforcement) and arguments, its events → `handler-egress` lines |
| `images.py` | the `image` verbs (A.7): build (id to a file), inspect, read a file without running the image, tag, remove (refused while a container mounts it), pull |
| `caches.py` | the `cache` verbs (A.9): sizes and emptying through `podman unshare` (inner podman's files are of subordinate ids); emptying refused while a sandbox mounts the folder or one inside it, or when it is a mount point here |
| `check.py` | the host check (A.8): rootless, subordinate ids, network backend, cgroups v2, /dev/fuse |
| `podman.py` | thin podman CLI helpers, labels, user namespace (keep-id) |
| `proxy/Containerfile` | the egress proxy image (`localhost/handler-ai-proxy:2`: mitmproxy), built by `image build-proxy` (A.7), never by a launch |
| `proxy/addon.py` | what the proxy decides (mounted into it, self-contained: the image has no Handler): allowed, denied or unlisted per target, settings read again when they change |

Conformance: `tests/sandbox/test_podman.py`, `tests/sandbox/test_images.py`,
`tests/sandbox/test_caches.py`.
