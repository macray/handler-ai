# Handler and OpenClaw

[OpenClaw](https://docs.openclaw.ai/) is the best-known personal assistant you host yourself:
"your AI assistant, on your own hardware, in every chat app you already use". One service on your
computer or a server links WhatsApp, Telegram, Slack, Signal, iMessage and others to an agent
that can use tools, run commands, follow skills and work on a schedule.

Handler and OpenClaw both run on your own computer, with your own models. They differ in what
protects you: in OpenClaw the sandbox is an option, off by default, and when it is on, only the
agent's tools run in it; in Handler every agent is in a box, always, and what it may reach on the
network and which keys it sees are decided outside it.

The facts on OpenClaw come from its documentation, read on 2026-11-23.

## In short

- **Pick OpenClaw** for an assistant in the chat apps you already use, on every platform, with
  thousands of community skills and a large community, and you are ready to harden it yourself:
  its docs have a security audit command and hardened settings to copy.
- **Pick Handler** for agents that are contained without any setting to get right: the whole
  program in a box, the network filtered site by site, your API keys kept out, no way for the
  agent to run a command outside. And for apps you keep, each with its own screen and data, that
  ask you things in an inbox rather than in a chat. Fewer channels: Handler's web UI, the
  terminal, your editor and a phone gateway you host.

## Side by side

| | OpenClaw | Handler |
|---|---|---|
| **What it is** | One assistant service (the Gateway) linking chat apps to its agents; skills, tools, schedules | Agents on your coding programs (Claude Code, Codex, Mistral Vibe, pi), each in a box, plus [apps](../apps.md), [Ask](../ask.md) and [automations](../automations.md) |
| **The sandbox** | "Off by default." When turned on (Docker by default; Podman, SSH, OpenShell…), only tool execution moves into it, for helper agents only or for all; the Gateway stays on your computer | Always on: there is no agent outside a box. The whole program is inside: the agent, its file tools, its MCP servers, its commands |
| **Getting out of it** | `tools.elevated`, "an explicit escape hatch that runs `exec` outside the sandbox", limited by who may use it | None from inside. Loosening is a setting you change (the **nested** or **privileged** level, an open network), shown in amber |
| **Files** | Without the sandbox, your user's files; `workspaceOnly` options limit the file tools to the workspace. In the sandbox: none of your files, or the workspace read-only or read-write; extra folders you mount (dangerous ones refused) | Its project folder, its skills and its notes folders. Nothing else of your computer |
| **Network** | Without the sandbox, your computer's. In it: none, or the container's network; no list of allowed sites | Per agent: no network, filtered (the default) or open, with allowed and blocked sites; an unknown site held while you watch (**Allow** or **Keep blocked**); "Learn the sites it needs" |
| **Your keys** | Files under `~/.openclaw` (settings, credentials, databases), "assume anything under `~/.openclaw/` may contain secrets", protected by file permissions; skills in the sandbox get their keys as environment variables | API keys, the Claude token and tool secrets tied to their sites never enter the box: a stand-in, the real value added on the way out. Not yet for the Codex and Mistral Vibe logins. No box ever reads Handler's own files |
| **Who can talk to it** | Anyone you pair or allow in each chat app; groups behind a mention. "Not a hostile multi-tenant security boundary": one trust boundary per Gateway | You, from the web UI, the terminal, your editor and your phone; family members you pair reach the apps you share, never your agents |
| **Skills** | Thousands on ClawHub; hundreds of malicious ones were found there in 2026, and it now scans them | Skills you add or a source offers, checked before an agent gets one (programs, hidden characters, the sites it names), and read-only in the box |
| **Apps with their own screen** | None to keep. The agent can draw a screen for the session (Canvas, in the Mac and iOS apps); an MCP server can show its own views in a conversation (off by default, kept ten minutes, no data of their own); widgets in Discord and Telegram | [Apps](../apps.md) you install from a source or have an agent write: each kept, with its own page and window, its data in your folders, what you can ask it, its jobs, and everything it may reach shown before you install it. On the computer and the phone |
| **When it needs you** | A message in a chat app (an automation's result, a failure alert); a reminder tied to a topic ("standing intent") brought up in the agent's next reply, up to 3 times; notifications on the Mac | Your inbox, on the computer and the phone: an app's request stays at the top until done, with its form filled in as far as the app can (or by voice), nothing sent until you press **Send**; reminders you set, a time you can change, **Stop these nudges** |
| **On a schedule** | Cron jobs, hooks and webhooks | Automations: at a time or when a session stops, running an agent, an app's job or your script in a box |
| **Phone and chat** | WhatsApp, Telegram, Slack, Discord, Signal, iMessage, Teams, Matrix and more; apps for macOS, iOS and Android | A gateway you host, end-to-end encrypted; apps, Ask and your sessions from the phone. No chat apps |
| **Models** | Any provider, or local models | A subscription, an API key, or a model on your computer, per agent |
| **Platforms, licence** | macOS, Linux, Windows, WSL 2; MIT, by the OpenClaw Foundation | Linux; macOS and Windows (WSL 2) experimental; Apache-2.0 |

## Apps and the inbox

**OpenClaw** talks to you in your chat apps: what it did and what it needs come as messages, in
the conversation. Its agent can also draw a screen for the moment (Canvas), and an MCP server can
show its own views; neither is kept as an app of yours, with its own data.

**Handler** has apps: small web apps you install, or an agent writes for you, each with its page,
its window, its data in your folders, and the few things you can ask it (by [Ask](../ask.md),
typed or spoken). When an app needs you (what you did today, a choice to make), it comes to your
inbox as its own form, filled in as far as it can, and stays there until done; how often you are
reminded is yours to choose.

## Who controls what

**OpenClaw** gives you many switches: the sandbox mode, its scope, workspace access, tool allow
and deny lists, exec approvals, who may message it. Its documentation is frank that they are
yours to set: the defaults suit "a trusted operator", the sandbox "is not a perfect security
boundary", and a `security audit` command checks what you chose. Set well, it is much safer than
its defaults; set by most people, it runs on your computer, with your files, your network and
your keys.

**Handler** has fewer switches, and none of them is the box itself: it is always there, the
agent never holds your API keys, and the network is filtered until you say otherwise. What you
choose is how much to loosen it, per agent, and each loosening is shown. The price is a container
runtime to install, images to build, and fewer ways to talk to it.
