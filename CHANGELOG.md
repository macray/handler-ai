# Changelog

What each release lets you do, grouped by what you do. One release is one commit in the public
repository ([`CONTRIBUTING.md`](CONTRIBUTING.md)).

## 0.2.0

- **Apps and sources**: Apps are now first-class (replacing mini apps), can be installed from git repositories (sources), run on Bun instead of Deno, and are fully managed by Handler
- **Security**: Multiple security fixes including message expiration, HTTPS-only remote gateways, and filtered network enforcement for plain HTTP
- **Chat**: Dedicated Chat feature for conversational agents, with voice input/output support
- **Project management**: Improved project workflow with agent export/import (agents files), and better organization
- **Agent improvements**: Agents now have a single model, can run as "model alone", support checks for validation, and improved session management
- **Configuration format change**: Configuration and state format changed from 0.1.0 - start fresh with empty config directories

## 0.1.0

The first public release (alpha, Linux only).

- **Agents in sandboxes.** Claude Code, Codex, Mistral Vibe and pi, each in its own rootless
  Podman container that sees only its project's folder, on your subscription, an API key,
  OpenRouter or a local model.
- **A network you can see.** No network, open, or filtered to the hosts you allow, changed live;
  *Learn hosts* shows what a project would need. Provider API keys and Claude Code tokens stay
  out of the sandbox: it holds a stand-in, and the network filter puts the real value into the
  requests to their hosts. Other secrets (a ChatGPT or Mistral login, addons' secrets) can be read
  inside it.
- **Projects, agents, sessions.** A project is a folder and its agents (roles with their models,
  instructions and settings); the daemon keeps each session, which you follow from the web UI,
  the terminal (`handler run`, `handler attach`, `handler terminal`), Zed (`handler acp`) or your
  phone.
- **Addons and skills.** Tools with their credentials and hosts (a browser, the Shopify CLI); a
  skill library with a reviewer that tells you what a skill would make your agents do.
- **Mini apps** an agent writes and you run locally, and **automations**: when a session stops
  or at a time, run your script, an agent or an app's route; results come to your inbox.
- **Phone access** through an end-to-end encrypted gateway you host.
