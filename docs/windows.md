# Install on Windows

Handler runs on Windows inside **WSL 2** (Windows Subsystem for Linux): a Linux system that Windows
runs beside itself. Handler, its agents and their sandboxes live in that Linux; you open the web UI in
your usual Windows browser. This page goes from a Windows without WSL to your first session.
Already have WSL 2 with systemd? Jump to [step 3](#3-prepare-linux).

## What you need

- Windows 11, or Windows 10 version 2004 or later (build 19041). On Windows 10, *Windows on my
  screen* and some WSL settings below are not available.
- Virtualization turned on in your PC's firmware (most PCs have it on; if WSL says it is not,
  look for "Intel VT-x", "AMD-V" or "SVM" in its settings).
- An administrator account on Windows, once, to install WSL.
- About 1 GB of disk for Handler's images (more for each other agent program you use), besides Linux itself, and 8 GB of memory or more:
  WSL gives Linux half of your PC's memory.

## 1. Install WSL and Ubuntu

1. Open **PowerShell as administrator**: right-click the Start button → *Terminal (Admin)* (or
   search "PowerShell", then *Run as administrator*).
2. Install WSL with its default Linux distribution, Ubuntu:

   ```powershell
   wsl --install
   ```

3. **Restart your PC** when it asks.
4. Ubuntu opens by itself after the restart (else: Start menu → *Ubuntu*). It unpacks, then asks
   for a **user name and a password**: they are your Linux account's, not Windows'. Pick them
   freely; `sudo` asks for this password.

You now have an Ubuntu terminal. Every command below without "PowerShell" before it runs **in
Ubuntu**, not in Windows.

**WSL already installed?** In PowerShell, `wsl --update`, then `wsl -l -v`: the VERSION column of
your distribution must say `2` (WSL 1 cannot run containers). If it says `1`:
`wsl --set-version Ubuntu 2`. No distribution yet: `wsl --install -d Ubuntu`.

## 2. Keep Linux running when its window closes

WSL stops a distribution about 15 seconds after its last terminal window closes, and Handler with
it: your agents' sessions stop (Resume picks them up again). To keep Handler running while you work
in the browser, tell WSL not to stop it:

1. In Windows, open the file `.wslconfig` in your user folder (`C:\Users\<you>\.wslconfig`;
   create it if it does not exist), for example from PowerShell:

   ```powershell
   notepad $env:USERPROFILE\.wslconfig
   ```

2. Add these lines and save:

   ```ini
   [general]
   instanceIdleTimeout=-1
   ```

3. In PowerShell, `wsl --shutdown`, then open Ubuntu again.

Linux then runs until you shut Windows down or run `wsl --shutdown`. The *WSL Settings* app (Start
menu) changes the same file. There too, *Memory size* sets how much memory Linux may take (the
default: half of your PC's).

## 3. Prepare Linux

In Ubuntu:

1. **Update it** and install what Handler uses: Podman (the containers agents run in) and `passt`
   (their network):

   ```bash
   sudo apt update && sudo apt upgrade -y
   sudo apt install -y podman passt curl
   ```

   On another distribution, its own packages (`sudo dnf install podman passt` on Fedora).

2. **Check that systemd runs** (it starts Handler's service). Ubuntu turns it on by itself:

   ```bash
   ps -p 1 -o comm=   # prints: systemd
   ```

   If it prints something else (`init`), turn it on: `sudo nano /etc/wsl.conf`, add

   ```ini
   [boot]
   systemd=true
   ```

   save, run `wsl --shutdown` in PowerShell, and open Ubuntu again.

3. **Let Handler's service run without a terminal open**, and start with Linux:

   ```bash
   sudo loginctl enable-linger $USER
   ```

4. **Optional, for a ChatGPT or Mistral subscription**: their logins run with Node.js and uv in
   this Linux (`sudo apt install -y nodejs npm`; uv comes with Handler below).

## 4. Install Handler

Still in Ubuntu:

```bash
curl -fsSL https://github.com/macray/handler-ai/releases/latest/download/install.sh | sh
```

It installs [uv](https://docs.astral.sh/uv/), then Handler with it, in `~/.local/bin`, and
changes nothing else (read it first if you prefer: it is attached to each
[release](https://github.com/macray/handler-ai/releases)). If it says this terminal does not find
`handler` yet, close Ubuntu's window and open it again (or run the full path it prints). Already have uv: `uv tool install handler-ai`.

Then:

```bash
handler setup
```

It starts Handler's service, checks this Linux and builds the images, the first time: the toolbox
and the agent program you choose, from a minute on a fast network to a quarter of an hour on a
slow one. Each `FAIL` line says what to fix; fix it and run
`handler setup` again. On WSL its check has a `WSL 2` line, a reminder to keep projects in Linux
(step 6).

## 5. Open the web UI

```bash
handler ui
```

It opens the web UI in your Windows browser (WSL passes `http://localhost:7430` on to Windows).
The link it opens signs this browser in, once (it works for two minutes, one time); from then on
the browser stays signed in, so a bookmark opens Handler. No browser opened? Copy the link it
prints into your browser.

Then follow [getting started](getting-started.md#2-connect-claude-code-to-your-claude-subscription)
from its step 2: connecting a model, then your first session. Run every command it shows (`claude
setup-token`, `handler run`…) in Ubuntu.

- **Claude Pro or Max**: install Claude Code in Ubuntu (`curl -fsSL https://claude.ai/install.sh
  | bash`), then `claude setup-token` there. It opens Anthropic's sign-in page, or prints a
  link to open in your browser.
- **ChatGPT or Mistral**: on Linux the web UI opens the login in a terminal window. WSL has none to
  open, so the web UI says *cannot open a terminal*: run the command it shows, `handler account
  login <name>`, in Ubuntu.

## 6. Where to keep your projects

Keep your projects **in Linux**, in your Linux home (`~/code/…`, Handler's default work folder),
not on a Windows drive (`/mnt/c/…`): agents read and write files there many times more slowly.

To reach them from Windows:

- **File Explorer**: *Linux* → *Ubuntu* in the sidebar, or the address
  `\\wsl.localhost\Ubuntu\home\<you>\code`.
- **An editor**: one that opens WSL folders works on the Linux files directly, e.g. VS Code
  with its WSL extension (`code .` in Ubuntu).
- **Git**: clone into `~/code` from Ubuntu (`git clone …`), not into `C:\`.

Moving a project from Windows: `cp -r /mnt/c/Users/<you>/code/my-app ~/code/`.

## What is different on Windows

- **Pasting an image** into `handler terminal` (Ctrl+V): the image you copied in Windows.
- **Windows on my screen** (an agent's browser on your screen): through WSLg, the windows of
  Linux on Windows 11. Not verified yet ([known limitations](known-limitations.md#linux-and-wsl-2-macos-experimental)).
- **Notifications** do not reach Windows: what an agent tells you is in the Inbox page and on a
  paired phone.
- **After restarting Windows**, Linux starts when something opens it: open Ubuntu once (or
  `wsl --exec true` in PowerShell), and Handler starts with it.

## Update and remove

- Update Handler: `uv tool upgrade handler-ai` in Ubuntu, then `handler setup` (from 0.2.0, a few
  files are renamed by hand first: [upgrading from 0.2.0](configuration.md#upgrading-from-020)). Update WSL itself:
  `wsl --update` in PowerShell.
- Remove Handler: `handler daemon uninstall`, then `uv tool uninstall handler-ai` (your settings
  stay in `~/.config/handler-ai` and `~/.local/state/handler-ai`; delete them to remove them too).
- Remove all of Ubuntu, **with every file in it**, your projects there included:
  `wsl --unregister Ubuntu` in PowerShell. Copy what you keep first.

## When something goes wrong

| What you see | What to do |
|---|---|
| `wsl --install` shows WSL's help | WSL is installed already: `wsl --install -d Ubuntu` |
| "Please enable the Virtual Machine Platform" or "virtualization" | turn virtualization on in your PC's firmware, then restart |
| `handler: command not found` | close Ubuntu's window and open it again (`~/.local/bin` goes on PATH at login) |
| `handler setup`: systemd failed | systemd is off: [step 3](#3-prepare-linux), item 2 |
| `podman` line FAIL: WSL 1 | in PowerShell: `wsl --set-version Ubuntu 2` |
| `subordinate ids` warn | for agents that run containers and for apps: run the command its line shows |
| the web UI stops answering a while after closing Ubuntu | [step 2](#2-keep-linux-running-when-its-window-closes) |
| `localhost:7430` does not open in Windows | `handler daemon status` in Ubuntu; in WSL Settings → Networking, *localhost forwarding* must stay on |
| sessions slow on a project | is it under `/mnt/c`? Move it to `~/code` ([step 6](#6-where-to-keep-your-projects)) |

Anything else: `handler daemon log` shows what Handler's service says.
