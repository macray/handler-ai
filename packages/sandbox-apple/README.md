# sandbox-apple — `handler-sandbox-apple`

**Status: experimental**, checked on one Mac (Apple container 1.6.1, macOS 26): on another
version, run the conformance suite first (`HANDLER_TEST_RUNTIMES=apple uv run pytest
tests/sandbox/conformance`).

**Implements:** contract A (sandbox) on Apple's `container` (macOS 26, Apple silicon): a virtual
machine per sandbox. Not yet: `nested` and `privileged` confinement, a display (windows: cocoa-way),
addons' image mounts (A6: an image unpacked into a folder); a spec asking for them is
refused (A1, exit 64), and `check` says so (`supports`).
**Depends on:** `handler_contracts`, `handler_sandbox_kit` (the executable, the launch, the filter, the relay);
Apple's `container` at runtime.
**Used by:** the control plane, through the executable only, when chosen (`handler runtime use
apple`, D.2).

| File | Role |
|---|---|
| `cli.py` | the executable: the kit's `runtime_cli.main` given `Apple`, `images`, `caches` and `check.check` |
| `launch.py` | `Apple`, the kit's `Runtime` (`sweep` too: `container`'s leftovers of dead launchers): each need its Apple container way (one method each), and `container`'s verbs; the launch itself is the kit's. A filtered sandbox has no network (Apple's networks do not isolate): `handler-relay` runs its command and joins its proxy address to the host through a socket of the host mounted in the VM; the launcher's RelayHost joins it to the filter, a sandbox of its own reached the same way |
| `images.py` | the `image` verbs (A.7): BuildKit's progress as `STEP n/m`, a build's id from `image inspect` (no `--iidfile`; its tag kept, an image without a name being deleted), then old unused builds pruned; `read` from `image save`'s layers; `build-proxy` also exports `handler-relay` for the VMs' Linux |
| `check.py` | the host check (A.8): macOS and Apple silicon, the container service; `supports` |
| `caches.py` | the `cache` verbs (A.9): the user's own files, measured and emptied directly |
| `container.py` | thin `container` CLI helpers; `inspect` documents read by field name, an image's config from this Mac's variant (linux/arm64) |

Conformance: `tests/sandbox/conformance/` (as `[apple]`, where `container` runs); unit tests
here: `tests/`, `container`'s documents as each release writes them in `tests/recorded/<version>/`
(re-recorded on a new release).
