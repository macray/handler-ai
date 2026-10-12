# toolbox — `localhost/handler-ai-toolbox:latest`

The development environment agents work in, **independent of the harness**: every harness
and addon image is built `FROM` it, so all agents get the same tools. This folder is yours: handlerd
copied it to `~/.config/handler-ai/toolbox/` from its default on first start and never changes it
afterwards.

Default contents (Arch Linux): base-devel, gcc, pkgconf, git, JDK 25 + Maven, Python + pip + uv,
Node + npm, Bun, rustup + sccache, ripgrep, fd, jq, curl, Chromium, wl-clipboard (the display's
clipboard, contract A.6), podman.

- Add a tool to `Containerfile`, then `handler image rebuild toolbox` (or **Rebuild** in the web UI): it
  also updates the system packages, rebuilds every harness and addon image on top, checks them,
  then switches them all, or none.
- Toolchain *state* is not baked in: `toolbox.toml` declares the caches (`~/.cargo`, `~/.rustup`,
  `~/.bun`, `~/.m2`, `~/.npm`, `~/.cache`, `~/.local`, inner podman's image store) mounted at
  runtime, kept per project or global as each project chooses (contract D.8). A new toolchain with state to keep adds its table there
  (`target`, `about`, `general` for a folder any tool writes to), or Settings → Caches does.

What Handler needs from it (contract B.6): a glibc system with `sh`; what the harness and addon
recipes install with (`npm`, `uv`, `jq`); `python3` for harnesses whose MCP servers run through
`handler-sandbox-env`; `chromium` for the playwright addon; podman with setcap'd
`newuidmap`/`newgidmap` only for agents with `confinement = "nested"`. Something missing shows as
a failed rebuild: nothing switches.
