# Getting started

From installing Handler to everyday use: the web UI, the terminal, an editor, then what you can give
an agent. What each word means: [`concepts.md`](concepts.md).

## 1. Install

On Linux, with rootless Podman (and `passt`) and a systemd user session. To use a subscription:
for Claude, Claude Code on your computer, once, to make its token (§2); for ChatGPT and Mistral,
Handler runs the harness's own login on your computer (npx or uvx fetches it: Node.js with npm, and
uv).

```bash
uv tool install handler-ai   # or: pipx install handler-ai
handler setup   # handlerd as a user service, checks this machine, builds the images
```

Without uv: `curl -fsSL https://github.com/macray/handler-ai/releases/latest/download/install.sh | sh`
installs uv, then Handler with it. To update: `uv tool upgrade handler-ai`. `handler setup` says what the machine lacks and can run again at any time. It builds
the network filter first (it checks where agents connect and adds your secrets to their requests:
a minute or two; handlerd builds it by itself when it is missing), then the images: the toolbox,
about 2.5 GB, then one image per harness, which takes a while.

From a checkout instead: [development](../dev/development.md#from-a-checkout).

## 2. Connect Claude Code to your Claude subscription

With a Claude Pro or Max plan, your agents run Claude Code on it, in the sessions you start and
follow yourself. Automations, which run with nobody watching, never use it: they need an API key.
Handler needs a token that you make yourself with Claude Code's own sign-in. Handler never signs in
for you and never sees your password.
No subscription? Skip this: in step 1 of §3 pick the provider *Anthropic API* and paste an API
key instead.

1. **Make the token**, in a terminal on your computer. Claude Code is only needed for this step
   (if you do not have it: `npm install -g @anthropic-ai/claude-code`, or Anthropic's installer
   `curl -fsSL https://claude.ai/install.sh | bash`):

   ```bash
   claude setup-token
   ```

   It opens Anthropic's sign-in page in your browser (or prints a link to open). Sign in with the
   account of the plan you want to use and approve. Back in the terminal it prints a token
   starting with `sk-ant-oat01-`: copy it. It lasts a year, for any number of sessions at once.
   Claude Code does not keep it anywhere: if you lose it, run the command again.

2. **Give it to Handler**: open the web UI (`handler ui`), Settings → Model access → *Connect a model*
   (once you have one: *Add an account*) → *Claude Pro or Max*. Name the account (e.g. `claude-perso`; your agents refer to it by this name)
   and choose its plan (`pro` or `max`): Claude Code cannot read the plan from the token. Then
   *Create*. The dialog goes on to its login: under "Run this yourself" (`claude setup-token`),
   keep *Paste it*, paste the token, *Save*. The account's line says "token in Handler, until …".

   Rather keep the token yourself? Instead of *Paste it*, choose where Handler reads it each time an
   agent starts: an *Environment variable* of handlerd (its service's environment, not your
   shell's), a *File* (its first line), or a *Command* that prints it, e.g. `pass show
   claude-perso`. Handler then keeps only where the token is, not the token.

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
`claude setup-token` again, then on the account's line *New token* (or `handler account token
claude-perso`). *Edit* → *Forget login* removes it from Handler.

**Your own use only**: a subscription is for you. What you share with others (an app, a
family member's phone) runs on a provider (an API key) or a local model.

## 3. Your first session

```bash
handler ui              # opens the web UI (it carries the UI's access token: open it this way)
```

1. **Connect a model**: Settings → Model access. Claude Pro or Max: see §2. ChatGPT or Mistral:
   pick it, name the account, and a terminal window opens with the harness's own login. Or pick a
   provider (Anthropic API, OpenAI, OpenRouter, a local llama.cpp or Ollama) and give its key.
   One is enough.
2. **Open a folder**: New project, choose a folder inside a work folder (`~/code` by default;
   Settings → Folders adds others), name its first agent ("Dev") and choose how it starts:
   - *Locked down*: no network, asks before acting.
   - *Guarded* (the default): only the hosts it is allowed (those its model and addons need are
     allowed for you), never asks.
   - *Open*: any host, never asks.
3. **Ask**: type a request on the project's page and press Enter. The session opens. Its network
   panel shows each host the agent reaches, and offers the blocked ones one click each to allow.
   When a project needs many hosts, *Learn hosts* lets everything through and marks what would be
   blocked; *Allow N hosts and block the rest* then allows them all and enforces again. It applies
   at once, while the agent works.

The agent keeps running when you close the tab. Your open sessions are at the foot of the menu,
those that ask you something or replied under **waiting for you**, then the others. The dot before each says where it is: filled when it waits for you or
replied, a green ring tinted inside while its agent runs (spinning while it works), an empty gray
ring when it is stopped (open it and Resume: it goes on where it was), an empty red ring struck
through when it failed to start. The one you are in unfolds there with its sandbox, its folder
and its buttons (its files, its sandbox and network, End…).

**Work and personal apart.** In Settings → Areas, make one area per side of your life (for
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
claude-perso`: its default agent on that account, for this session). An account not made for the project's area (Settings → Areas)
is refused, so a work account never works on a personal repository (`--anyway` runs it there
anyway, outside the project, once you type `yes`). Elsewhere, name an account or a provider: Handler makes an **ad-hoc agent** for that folder (one
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
session stopped. Every command: [`docs/user/cli/index.md`](cli/index.md).

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
{ "agent_servers": { "handler · claude-perso": {
    "type": "custom",
    "command": "/home/you/.local/bin/handler",
    "args": ["acp", "claude-perso"] } } }
```

`handler acp` uses the folder Zed opened. In a project's folder it uses the project's agent of that
name, or the one using that account or provider: each Zed thread is a session of that agent,
listed in the web UI (and shareable with a phone). Elsewhere it is an account or a provider
(`--harness` for a provider), one sandbox per connection.

## 6. What you can give an agent

All in the agent's form (its project's page → the agent → Edit).

**Addons**: programs, the skills that explain them and the hosts they need, for one kind of system,
without growing the toolbox image. Installed from a [source](sources.md) (Handler's, or one you added),
a folder or an archive (Library → Addons → Install an addon, or `handler addon add`); each shows what it brings (hosts, secrets,
commands, MCP server, image) before you install it. An agent gets an addon through one of its
**configurations**, its settings and secrets (Library → Addons → Configure; the secrets go to
Handler's secret store). Writing one: [`addons.md`](addons.md).

```bash
handler addon add shopify                                # see what it brings, install it
cp examples/bindings/shopify-dev-shop.toml ~/.config/handler-ai/bindings/  # or by hand: store, token
cd ~/code/my-theme && handler run claude-perso --binding shopify-dev-shop
```

**A web browser**: the `playwright` addon (Playwright MCP, Chromium). Headless by default; with
**Show windows on my screen and paste images** (`--display`) the window opens on your Wayland
desktop, the sandbox getting nothing else of it but the clipboard. See
[a browser for your agents](browser.md).

```bash
handler addon add playwright && cp examples/bindings/browser.toml ~/.config/handler-ai/bindings/
cd ~/code/my-theme && handler run claude-perso --binding browser --display
```

**Skills**: folders with a `SKILL.md` (the Agent Skills format every harness reads), in the
Skills page: written there, imported from a `.skill`/`.zip` archive or a URL, or by hand in
`~/.config/handler-ai/skills/`. A project gives skills to all its agents (its Settings: *Add
skill*, or a skill's page: who gets it); each agent picks its own besides. A skill's page shows what Handler found in its files (scripts, hosts, hidden characters), its
reviews (*Review with…* the built-in skill reviewer) and *Edit with an agent* (the built-in skill
creator).

**Knowledge folders**: notes an agent reads, folders under the knowledge root (Knowledge page,
default `~/knowledge`), mounted read-only at `/knowledge/<name>`. A skill can teach it
how to read them. See [knowledge folders](knowledge.md).

```bash
handler knowledge list                                   # the folders that can be selected
cd ~/code/my-theme && handler run claude-perso --knowledge me --knowledge projects/my-theme
```

**Containers**: an agent may run podman itself (**Runs containers**,
`--containers`), which keeps the capabilities podman needs in that sandbox only; as a last resort
an agent can run `privileged`. Widening what an agent may do is confirmed, and the web UI flags
every agent that is not strictly confined.

## 7. From your phone

Pair a phone in Settings → Remote, through a gateway you host (Tailscale or a reverse proxy): it
relays end-to-end encrypted messages and Handler only polls it outbound. A session is reachable from
the phone while its **Remote** switch is on. See [your phone](phone.md).
