# Addons: installing and writing them

An **addon** teaches agents to use one kind of system (a Shopify store, a browser, your company's
API): the program they need, skills that say how to use it, the hosts it reaches, and the settings
and secrets a **binding** fills for one account of that system. Nothing here needs the Handler
source code.

## Installing one

Three places an addon comes from:

| Source | How |
|---|---|
| a [source](sources.md): Handler's offers `shopify` and `playwright`; one you added, its own | Library → Addons → Install an addon → shopify, or `handler addon add shopify` (`--from SOURCE` for one you added) |
| a folder on this machine | Library → Addons → Install an addon → From a folder or an archive, or `handler addon add ./my-addon` |
| an `https://…tar.gz` archive (a forge's archive of an addon's repository works) | the URL, or `handler addon add https://…/archive/main.tar.gz` |

Before anything is installed you see what it brings: the hosts its agents may reach, the secrets
and settings it asks for, the env it sets, its commands, the MCP server it gives every session,
its skills, and whether it has an image (its `Containerfile` then runs code on this machine when
the image is built). Install takes exactly that content: if it changed since, Handler refuses and
shows it again.

An installed addon goes to `~/.config/handler-ai/addons/<name>/` and is recorded, with where it came
from, in `~/.config/handler-ai/addons.lock.toml`. Its image is then built and checked (Settings →
Images); agents get it through a **configuration** of it (Library → Addons opens its Configure
dialog right after the install: its settings and secrets; in the files, a binding) that you select
in the agent's settings. An addon's image missing (a built-in addon, a build that failed), Handler
builds it as soon as an agent uses the addon; until it is built, that agent's sessions do not
start: the session says what it needs, with **Prepare now**.

- Update: when the source an addon came from holds a newer one, Library → Addons says so ("update available"); a
  click shows it again before installing it. An addon from a folder or a URL: Details → Reinstall looks at its source again.
- Remove: Library → Addons → Details → Uninstall, or `handler addon rm NAME` (refused while a configuration
  uses it).
- `handler addon list` lists them all with where each comes from; `handler source list` what the sources offer.

Built-in addons (`app-builder`) come with Handler and need no install. An addon of yours with a built-in
one's name replaces it.

## Writing one

An addon is a folder named after it:

```
my-addon/
├── addon.toml        the manifest (handler.addon/v1, below)
├── Containerfile     only if it brings a program (`image` in the manifest)
├── skills/<skill>/   skills, each with a SKILL.md, given to the agents that have the addon
└── PROVISIONING.md   for people: how to create the least-privilege account a binding needs
```

`addon.toml`:

```toml
apiVersion = "handler.addon/v1"
name = "my-addon"                       # = the folder's name
description = "what agents can do with it"
image = "localhost/handler-ai-addon-my-addon"  # only with a program: built from the Containerfile
commands = ["mytool"]                   # exactly what the image's bin/ holds
check = ["mytool", "--version"]         # run when the image is built: must exit 0
egress = ["api.example.com:443"]        # hosts its agents may reach

[env]                                   # set as is in agents' sandboxes
MYTOOL_NO_TELEMETRY = "1"

[settings.region]                       # filled by each binding, given to agents as this env
env = "MYTOOL_REGION"
required = true
description = "the account's region"

[secretSlots.token]                     # a secret each binding gives (handler's secret store)
env = "MYTOOL_TOKEN"
required = true
description = "an API token with read access only"
hosts = ["api.example.com:443"]         # where it goes: some of egress (default: all of them)
```

Agents get a stand-in, and Handler puts the value in their requests to its `hosts`; this is not
yet checked with each addon's tool, so count an addon's secrets as readable by the agent
([known limitations](known-limitations.md#stand-ins-claude-code-tokens-and-api-keys-only)). A
tool that signs its requests with the secret, or speaks something else than HTTP, needs the value
itself: `delivery = "env"` (Settings → Secrets then says agents can read it).

An MCP server it gives every session: `[mcp] command = ["mytool", "mcp"]` (its first word one of
`commands`). Every key, for reference:
[contracts](../dev/contracts.md) §G.1.

The `Containerfile`, when there is a program: built in your toolbox (its compilers and runtimes),
shipped as only the installed tree, mounted read-only at `/opt/addons/<name>` with its `bin/` added
to agents' `PATH`.

```dockerfile
ARG TOOLBOX_IMAGE
FROM ${TOOLBOX_IMAGE} AS build
ARG PREFIX=/opt/addons/my-addon
RUN npm install --prefix "$PREFIX" --no-fund --no-audit mytool \
    && mkdir -p "$PREFIX/bin" \
    && ln -s ../node_modules/.bin/mytool "$PREFIX/bin/mytool" \
    && echo "mytool $(jq -er .version "$PREFIX/node_modules/mytool/package.json")" > "$PREFIX/version"
FROM scratch
COPY --from=build /opt/addons/my-addon /
```

It must write one line to `version` (shown in Settings → Images), and fail if it cannot. When it
is built, Handler checks it as agents get it (your user, no network): `bin/` holds exactly `commands`,
none of them is already a toolbox command, `version` is readable, `check` exits 0.

Try it while writing: `handler addon add ./my-addon --yes` (again after each change), then a configuration
of it and an agent. Share it as a folder, or as a repository whose archive URL others install.
