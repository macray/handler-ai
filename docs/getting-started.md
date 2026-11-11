# Getting started

From installing Handler to everyday use: the web UI, the terminal, an editor, then what you can give
an agent. What each word means: [`concepts.md`](concepts.md).

## 1. Install

On Linux, with rootless Podman (and `passt`), or Docker (below); a systemd user session keeps Handler's daemon
running (without one, start `handlerd` yourself, [`handler setup`](cli/setup.md)). To use a subscription:
for Claude, Claude Code on your computer, once, to make its token (§2); for ChatGPT and Mistral,
Handler runs the harness's own login on your computer (npx or uvx fetches it: Node.js with npm, and
uv).

```bash
curl -fsSL https://github.com/macray/handler-ai/releases/latest/download/install.sh | sh
handler setup   # in a new terminal: handlerd as a user service, checks this machine, builds the images
```

`install.sh` installs uv if you do not have it, then Handler with it; if you already use uv:
`uv tool install handler-ai` (or `pipx install handler-ai`). To update: `uv tool upgrade handler-ai`
(from 0.2.0, a few files are renamed by hand first: [upgrading from
0.2.0](configuration.md#upgrading-from-020)).
`handler setup` says what the machine lacks and can run again at any time. It builds
the network filter first (it checks where agents connect and adds your secrets to their requests:
a minute or two; handlerd builds it by itself when it is missing), then the images: it asks which agent
program you want first (Claude Code, Codex, pi or Mistral Vibe), and builds the toolbox and that
program only: about 1 GB, from a minute on a fast network to a quarter of an hour on a slow one.
It prints one line per image with a time estimate ("toolbox 1/2 · ~3 min") and writes the full log
to a file it names (`--verbose` shows the log instead). Each other agent program is built the
first time an agent needs it, or in Settings → Expert → Sandboxes. A session started before its agent's program is built waits: the
session says so, with what it will start with (your request is kept), follows the build running
(the toolbox build too) or offers **Prepare now**, and starts by itself once it is built.

Before the first build, `handler setup` also asks which engine agents that run containers use
inside their sandbox: Podman (the default) or Docker (`--engine docker`; later, `handler toolbox
add docker`).

### Docker instead of Podman

Agents can run in Docker containers instead: `handler setup --runtime docker`, or later `handler
runtime use docker` (or Settings → Expert → Sandboxes → *Change*). On Linux it is a rootful
Docker Engine: its check warns that an agent escaping its sandbox would be root on your computer,
and agents cannot be privileged there; a rootless Docker is refused. Docker Desktop, OrbStack and
Colima keep each sandbox in Docker's virtual machine. New, and less tested than Podman.

**Docker needs its buildx plugin**: Handler builds every image with BuildKit, and the runtime's
check fails without `docker buildx`. Docker's own packages install it (`docker-buildx-plugin`),
Docker Desktop and OrbStack have it; some distributions package it apart (on Arch,
`docker-buildx`).

### On a Mac (experimental)

On macOS 26 with Apple silicon, agents run with Apple's `container` (each sandbox a virtual
machine of its own); install it from [its releases](https://github.com/apple/container/releases)
before `handler setup`. When Docker Desktop or OrbStack runs, setup offers both before the first
build, Apple's first: Enter keeps it, `docker` switches (`handler setup --runtime NAME` chooses
without asking; Docker needs its buildx plugin, above). On macOS 15 or an Intel Mac, use Docker
Desktop or OrbStack. What does not work there yet: [known
limitations](known-limitations.md#linux-and-wsl-2-macos-experimental).

### On Windows (WSL 2)

Handler runs inside a WSL 2 Linux distribution, as on Linux, the web UI in your Windows browser.
From installing WSL to the first session, step by step: [install on Windows](windows.md).

### From a checkout

To run Handler from its source instead (it needs [uv](https://docs.astral.sh/uv/) and
[Bun](https://bun.sh), or Podman to run Bun's image):

```bash
git clone https://github.com/macray/handler-ai && cd handler-ai
uv sync
scripts/build-web-ui.sh   # the web UI
uv run handler setup      # handlerd as a user service running this checkout, images built
```

To use the checkout's `handler` everywhere: `ln -s "$PWD/.venv/bin/handler" ~/.local/bin/handler`.

## 2. Connect Claude Code to your Claude subscription

With a Claude Pro or Max plan, your agents run Claude Code on it, in the sessions you start and
follow yourself. Automations, which run with nobody watching, never use it: they need an API key.
Handler needs a token that you make yourself with Claude Code's own sign-in. Handler never signs in
for you and never sees your password.
No subscription? Skip this: in step 1 of §3 pick the provider *Anthropic API* and paste an API
key instead.

1. **Make the token**, in a terminal on your computer. Claude Code is only needed for this step (if you do not have it:
   `npm install -g @anthropic-ai/claude-code`, or Anthropic's installer
   `curl -fsSL https://claude.ai/install.sh | bash`):

   ```bash
   claude setup-token
   ```

   It opens Anthropic's sign-in page in your browser (or prints a link to open). Sign in with the
   account of the plan you want to use and approve. Back in the terminal it prints a token
   starting with `sk-ant-oat01-`: copy it. It lasts a year, for any number of sessions at once.
   Claude Code does not keep it anywhere: if you lose it, run the command again.

2. **Give it to Handler**: open the web UI (`handler ui`), Settings → Model access → *Connect a model*
   (once you have one: *Connect a subscription*, at the top of the page) → *Claude Pro or Max*.
   Handler suggests a name for the account (`claude`; change it, e.g. `claude-perso`: your agents
   refer to it by this name) and choose its plan (`pro` or `max`: Claude Code cannot read it from
   the token). Under its steps, the command to run (`claude setup-token`, with *Copy*), paste the
   token, then *Connect*. The account's line gets a green dot (its *Edit* says
   "Logged in · token kept by Handler · until …").

   Rather keep the token yourself? Under the token's field, open *Keep it elsewhere* and choose
   where Handler reads it each time an agent starts: an *Environment variable* of handlerd (its
   service's environment, not your shell's), a *File* (its first line), or a *Command* that prints
   it, e.g. `pass show claude-perso`. Handler then keeps only where the token is, not the token.

   From the terminal instead:

   ```bash
   handler account add claude-perso claude-code --plan max --token  # asks for the token (hidden)
   handler account add claude-pro claude-code --plan pro --token-command 'pass show claude-pro'
   handler account list
   ```

**Several accounts** (work and personal): repeat both steps, signing in with the other account in
step 1, and give each its own name. Agents and `handler run claude-pro` name the one they use; when you
create an agent with more than one account, the form asks which.

**After a year** the account warns a month before the token expires ("make a new one"): run
`claude setup-token` again, then on the account's line *Connect again* (or `handler account token
claude-perso`). *Edit* → *Forget login* removes it from Handler.

**Your own use only**: a subscription is for you. What you share with others (an app, a
family member's phone) runs on a provider (an API key) or a local model.

## 3. Your first session

```bash
handler ui              # opens the web UI and signs this browser in (then a bookmark works)
```

1. **Connect a model**: Settings → Model access. Claude Pro or Max: see §2. ChatGPT or Mistral:
   pick it, keep or change its name, *Connect*, and a terminal window opens with the harness's own login. Or pick a
   provider (Anthropic API, OpenAI, OpenRouter, a local llama.cpp or Ollama) and give its key.
   One is enough.

   **A model server on this computer** must listen where sandboxes reach it, not only on
   `127.0.0.1`: start llama-server with `llama-server --host 0.0.0.0 --jinja` (its own port,
   8080), Ollama with `OLLAMA_HOST=0.0.0.0`. In its form, *Test* asks the server for its models
   from where a sandbox would: it fills the models, and their context when the server says it
   (llama-server, vLLM). It is *ready* once it answered; *not reached* says why
   (`handler provider test NAME` from a terminal). When a session's model stops answering (a
   filtered agent's: three calls that could not connect in a turn, or 15 seconds after the
   first), Handler says so in the conversation: "The model at host.containers.internal:8080 does
   not answer (connection refused). Is the server listening on 0.0.0.0?", with a link to test it.
2. **New project**: choose a folder inside a work folder (`~/code` by default;
   Settings → Folders adds others; those changed last are listed first) and *Create the
   project*. Its page says *No agent yet* and offers one, "An agent to work with you here": *Add
   it* makes it, named *Assistant*, on the model you used last. It reaches only the sites it
   needs (its model's, its tools') and never asks before acting. *Set up an agent* opens the
   agent form instead, where everything it can do is one row each: its network (*No network*,
   *Only these sites*, *Any site*, with a meter: more bars, safer), then *Asks before acting*,
   *Runs containers*, *Windows on my screen*, *Privileged*. What weakens its sandbox shows
   amber, and saving it asks you to confirm.
3. **Ask**: type a request in the box on the project's page and press Enter. Under the request,
   chips say who works and what it may do: the program and what it runs on (your account or
   API key, and the model): another one picked there is for this session only, and *Make … the
   default* saves it to the agent; its tools; its network (more bars, safer), and an amber chip
   for each setting that weakens its sandbox. The session opens. Its network
   panel shows each host the agent reaches, and offers the blocked ones one click each to allow.
   When a project needs many hosts, *Learn the sites it needs* lets everything through and marks what would be
   blocked; *Allow N hosts and block the rest* then allows them all and enforces again. It applies
   at once, while the agent works. Under the prompt, next to its mode and model, *context* says
   how full the agent's context is (`85% · 170k / 200k` tokens), when its harness tells it
   (Claude Code, Mistral Vibe and pi do); it stays when you resume the session.

The agent keeps running when you close the tab. The **bell** at the top of the menu counts what
waits for you in every project and app: a session asking you something (*Allow* or *No* right in
its list), a run or a plan that failed; its list shows what runs too, and the browser tab's title
says the count, `(1) Handler`. A pinned project's dot says what its sessions do, and the
project's page lists them (its **Sessions** tab, its agents as tabs above the box; its
**Plans**, **Automations** and **Settings** are the other tabs, and its **⋯** exports its agents or
adds some from a file): open one, or Resume a stopped one (it goes on where it was). A
session's header holds its buttons (its files, its sandbox and network, the phone, End…).

**Work and personal apart.** In Settings → Expert → Areas, make one area per side of your life (for
example *Work* and *Personal*), each with its colour. Give each project its area, and say for
each account and provider which areas it may be used for (a local model: any; from the
terminal, `--area` on `account add` and `provider add`). A project then runs only the
accounts and providers of its area: the web UI does not offer the others, and `handler run`
and `handler terminal` refuse them in that project's folder. So your employer's Claude account
never touches your side projects, and your personal subscription never works on your employer's
code. A project without an area can use any account or provider.

## 4. From a terminal

The folder decides the project: in a project's folder (or below), `handler run` and `handler terminal`
use that project's agents (`handler run reviewer`: the agent named reviewer; `handler run
claude-perso`: its default agent on that account, for this session). An account not made for the project's area
(Settings → Expert → Areas)
is refused, so a work account never works on a personal repository (`--anyway` runs it there
anyway, outside the project, once you type `yes`). Elsewhere, name an account or a provider: Handler makes an **ad-hoc
agent** for that folder (one
per folder and `--name`: the next `handler run` there finds it again, with any account). An option
that differs from the agent's settings is saved to it once you say yes, never ignored.

```bash
cd ~/code/my-app && handler run                                  # the project's default agent
cd ~/code/my-app && handler run reviewer -p "review the last commit" # another agent of the project
cd ~/code/scratch && handler run claude-perso -p "what does this do?" # ad-hoc: this folder, no project
handler session list && handler attach s_…                         # sessions; back to one
```

The session runs in the daemon, so the web UI and a paired phone show the same one. Ctrl-C
cancels the turn (or detaches), Ctrl-D detaches, `handler attach` comes back, even once the
session stopped. Every command: [`docs/cli/index.md`](cli/index.md).

**The harness's own UI.** `handler terminal` runs Claude Code's own terminal UI in the sandbox the
agent gets (not a session: the web UI shows it to change its network, not its conversation);
restarting Handler leaves it running. To keep typing `claude`, add to your shell:

```bash
claude() { handler terminal claude-perso -- "$@"; }  # claude, claude --resume
```

`HANDLER_ACP_CLIENT='toad acp "{bridge}"'` uses another ACP client than the built-in one (`{bridge}`:
`handler attach --stdio <session>`, a session as a stdio ACP agent).

## 5. From an editor (Zed)

The agent runs in the sandbox; Zed only sees ACP. In `~/.config/zed/settings.json` (the
`command` is the full path of `handler`, `which handler`):

```json
{
  "agent_servers": {
    "handler · claude-perso": {
      "type": "custom",
      "command": "/home/you/.local/bin/handler",
      "args": [
        "acp",
        "claude-perso"
      ]
    }
  }
}
```

`handler acp` uses the folder Zed opened. In a project's folder it uses the project's agent of that
name, or the one using that account or provider: each Zed thread is a session of that agent,
listed in the web UI (and shareable with a phone). Elsewhere it is an account or a provider (`--harness` for a
provider), one sandbox per connection.

## 6. What you can give an agent

All in the agent's form (its project's page → the agent's tab → Edit).

**Tools**: programs, the skills that explain them and the hosts they need, for one kind of system,
without growing the toolbox image. Installed from a [source](sources.md) (Handler's, or one you added),
a folder or an archive (Library → Tools → Get more, or `handler tool add`); each shows what it brings (hosts,
secrets,
commands, MCP server, image, what it adds to the toolbox) before you install it. An agent gets an
tool by its name, or, when it asks for settings and secrets, through one of its
**connections** (Library → Tools → its name → Connect; the secrets go to Handler's secret store); a
project can give tools to all its agents. Writing one: [`tools.md`](tools.md).

```bash
handler tool add github                                 # see what it brings, install it
cd ~/code/my-app && handler run claude-perso --tool github=github-agent
```

Its connection `github-agent` is made in Library → Tools → github → *Connect*: that name and a
token of the account the agent works as (its `PROVISIONING.md` says which), then *Save*.

**A web browser**: the `playwright` tool (Playwright MCP, Chromium). Headless by default; with **Windows on my
screen** (`--display`) the window opens on your Wayland
desktop, the sandbox getting nothing else of it but the clipboard. See
[a browser for your agents](browser.md).

```bash
handler tool add playwright    # then Library → Tools → playwright → Connect: name it browser, Save
cd ~/code/my-theme && handler run claude-perso --tool playwright=browser --display
```

**Skills**: folders with a `SKILL.md` (the Agent Skills format every harness reads), in
Library → Skills: written there, imported from a `.skill`/`.zip` archive or a URL, or by hand in
`~/.config/handler-ai/skills/`. A project gives skills to all its agents (its Settings tab: *Add
skill*, or a skill's page: who gets it); each agent picks its own besides. A skill's page shows what Handler found in
its files (scripts, hosts, hidden characters), its
reviews (*Review with…* the built-in skill reviewer) and *Edit with an agent* (the built-in skill
creator).

**Notes** (notes folders): notes an agent reads, folders under the notes root (Library →
Notes, `~/.local/share/handler-ai/notes` until you **Change** it, made by Handler), mounted
read-only at `/notes/<name>`; each agent's settings pick its folders. A skill can teach it
how to read them. See [notes folders](notes.md).

```bash
handler notes list                                   # the folders that can be selected
cd ~/code/my-theme && handler run claude-perso --notes me --notes projects/my-theme
```

**Containers**: an agent may run containers itself (**Runs containers**,
`--containers`), with the toolbox's engine (Podman, or Docker: `handler toolbox add docker`, each
such sandbox starting its own rootless Docker), which keeps the capabilities it needs in that
sandbox only; as a last resort
an agent can run `privileged`. Widening what an agent may do is confirmed, and the web UI flags
every agent that is not strictly confined.

## 7. From your phone

Pair a phone in Settings → Your phone, through a gateway you host (Tailscale or a reverse proxy): it
relays end-to-end encrypted messages and Handler only polls it outbound. A session is reachable from
the phone while its phone button (in the session's header) is on. See [your phone](phone.md).
