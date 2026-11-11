# Tools: installing and writing them

A **tool** teaches agents to use one kind of system (a Shopify
store, a browser, your company's API): the program they need, skills that say how to use it, the
hosts it reaches, what it keeps between sessions, and, when it asks for some, the settings and
secrets a **connection** fills for one account of that system. Nothing here needs the Handler
source code.

## Installing one

Three places a tool comes from:

| Source | How |
|---|---|
| a [source](sources.md): Handler's offers `github`, `playwright`, `lightpanda` and toolchains (`go`, `java`, `rust`, `bun`); one you added, its own | Library → Tools → Get more → github → Install, or `handler tool add github` (`--from SOURCE` for one you added) |
| a folder on this machine | Library → Tools → Get more → From a folder or an archive, or `handler tool add ./my-tool` |
| an `https://…tar.gz` archive (a forge's archive of a tool's repository works) | the URL, or `handler tool add https://…/archive/main.tar.gz` |

Before anything is installed you see what it brings: the hosts its agents may reach, the secrets
and settings it asks for, the env it sets, its commands, the MCP server it gives every session,
its skills, and whether it has an image (its `Containerfile` then runs code on this machine when
the image is built). It also says what it needs from the **toolbox**, the system every agent
works in: what the toolbox already gives, and what installing it adds there: a **system
package** (Chromium for a browser, a C compiler for Rust), with its install script, which runs as
root when the toolbox is built so that every agent gets what it installs. A system package comes
from Handler, from your own folder, or from the tool's source, installed with it. Install takes
exactly that content, and adds those system packages: if any of it changed since, Handler refuses
and shows it again.

An installed tool goes to `~/.config/handler-ai/tools/<name>/` and is recorded, with where it came
from, in `~/.config/handler-ai/tools.lock.toml`. When it added system packages, the toolbox is
rebuilt with them first; then its program is built and checked (Settings → Expert → Sandboxes). Library →
Tools shows where each one is in a word: *Preparing* while that runs, *Broken* when its build
failed (**Fix** shows the build's error), *Not ready* with what it lacks (a command no system package gives: add it to your own lines of
the toolbox, Settings → Expert → Sandboxes, then apply them). You give it to an agent in the agent's
settings, or to every agent of a project in the project's: by its name, or, when it asks for
settings or secrets, through a **connection** to it (its page, Library → Tools → its name,
opens **Connect** right after the install; until then the shelf says *Not set up*). A tool's program missing (a built-in tool, a build that
failed), Handler builds it as soon as an agent uses the tool; until it is built, that agent's
sessions do not start: the session says what it needs, with **Prepare now** (or follows the
build already running), and starts by itself once it is built, with the request you typed.

- Update: when the source a tool came from holds a newer one, its page's ⋯ says *See the
  update*, which shows it again before installing it. A tool from a folder or a URL: ⋯ →
  *Install it again* looks at its source again. Its connections stay; one the update made
  invalid says *Broken*, and is fixed in its Edit.
- Remove: its page's ⋯ → Uninstall, or `handler tool rm NAME` (refused while an
  agent, a project or a connection uses it). The system packages it added stay in the toolbox:
  turn them off in Settings → Expert → Sandboxes.
- `handler tool list` lists them all with where each comes from; `handler source list` what the sources offer.

Built-in tools (`app-builder`) come with Handler and need no install. A tool of yours with a built-in
one's name replaces it.

## Writing one

A tool is a folder named after it:

```
my-tool/
├── tool.toml        the manifest (handler.tool/v1, below)
├── Containerfile     only if it brings a program (`image` in the manifest)
├── skills/<skill>/   skills, each with a SKILL.md, given to the agents that have the tool
└── PROVISIONING.md   for people: how to create the least-privilege account a connection needs
```

`tool.toml`:

```toml
apiVersion = "handler.tool/v1"
name = "my-tool"                       # = the folder's name
description = "what agents can do with it"
image = "localhost/handler-ai-tool-my-tool"  # only with a program: built from the Containerfile
commands = ["mytool"]                   # exactly what the image's bin/ holds
check = ["mytool", "--version"]         # run when the image is built: must exit 0
needs = ["cc"]                          # commands it runs from the toolbox (a system package
                                        # gives them, added when the tool is installed)
egress = ["api.example.com:443"]        # hosts its agents may reach

[[caches]]                              # what its program keeps between sessions
target = "~/.mytool"
about = "mytool: its downloads"         # its name in Settings → Expert → Caches, then more
bin = "bin"                             # its commands folder, on PATH (optional)

[env]                                   # set as is in agents' sandboxes
MYTOOL_NO_TELEMETRY = "1"

[settings.region]                       # filled by each connection, given to agents as this env
env = "MYTOOL_REGION"
required = true
description = "the account's region"

[secretSlots.token]                     # a secret each connection gives (handler's secret store)
env = "MYTOOL_TOKEN"
required = true
description = "an API token with read access only"
hosts = ["api.example.com:443"]         # where it goes: some of egress (default: all of them)
```

Agents get a stand-in, and Handler puts the value in their requests to its `hosts`; this is not
yet checked with each tool's program, so count a tool's secrets as readable by the agent
([known limitations](known-limitations.md#stand-ins-claude-code-tokens-and-api-keys-only)). A
tool that signs its requests with the secret, or speaks something else than HTTP, needs the value
itself: `delivery = "env"` (Settings → Expert → Secrets then says agents can read it).

An MCP server it gives every session: `[mcp] command = ["mytool", "mcp"]` (its first word one of
`commands`). Every key, for reference: its schema,
[`handler.tool.v1`](../schemas/handler.tool.v1.schema.json).

The `Containerfile`, when there is a program: built in your toolbox (its compilers and runtimes),
shipped as only the installed tree. Handler copies that tree into a folder of its own and mounts
it read-only at `/opt/tools/<name>` in every agent that uses the tool, with its `bin/` added to
their `PATH`.

```dockerfile
ARG TOOLBOX_IMAGE
FROM ${TOOLBOX_IMAGE} AS build
ARG PREFIX=/opt/tools/my-tool
RUN npm install --prefix "$PREFIX" --no-fund --no-audit mytool \
    && mkdir -p "$PREFIX/bin" \
    && ln -s ../node_modules/.bin/mytool "$PREFIX/bin/mytool" \
    && echo "mytool $(jq -er .version "$PREFIX/node_modules/mytool/package.json")" > "$PREFIX/version"
FROM scratch
COPY --from=build /opt/tools/my-tool /
```

It must write one line to `version` (shown in Settings → Expert → Sandboxes), and fail if it cannot. When it
is built, Handler checks it as agents get it (your user, no network): `bin/` holds exactly `commands`,
none of them is already a toolbox command, every `needs` is in the toolbox, `version` is readable,
`check` exits 0.

A source may also hold the system packages its tools need, in `system-packages/<name>/`: a
`package.toml` (what it provides), an `install-fedora.sh` (run as root when the toolbox is built)
and a `check.sh`. Every key of `package.toml`, for reference: its schema,
[`handler.system-package.v1`](../schemas/handler.system-package.v1.schema.json).

Try it while writing: `handler tool add ./my-tool --yes` (again after each change), then a connection
to it and an agent. Share it as a folder, or as a repository whose archive URL others install.
