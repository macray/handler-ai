# handler provider

Add and remove providers: an API and its key, or a model server on this computer.

## When to use it

- To use an API key (Anthropic, OpenAI, Mistral, OpenRouter) instead of a subscription: for
  agents that run on their own (automations, apps), or for others than you.
- To use a local model (llama.cpp, Ollama).

A subscription is an [account](account.md) instead.

## Usage

```
handler provider list
handler provider templates
handler provider add NAME --from TEMPLATE [--key] [--endpoint PROTOCOL=URL …] [--model ID …]
                     [--context CONTEXT …] [--description TEXT]
handler provider rm NAME
```

A provider starts from a template that knows the endpoints, the models and how each harness
talks to it. Its key goes to Handler's secret store and is never shown again.

## Subcommands

| Subcommand | |
|---|---|
| `list` | the providers: status (ready, or what is missing), protocols, models, where the key is, contexts, agents using it |
| `templates` | what a provider can start from, whether it needs a key, its endpoints |
| `add NAME --from TEMPLATE` | a provider from that template, named NAME (what agents and commands use) |
| `rm NAME` | the provider and its key. Agents using it cannot start until given another |

## Options of `add`

| Option | |
|---|---|
| `--key` | ask for its key (hidden, or read from stdin). Required for a hosted API |
| `--endpoint PROTOCOL=URL` | another URL for a protocol, e.g. a server on another port: `openai-chat=http://host.containers.internal:8080/v1`; repeatable |
| `--model ID` | the models it offers, instead of the template's (a template's model keeps its details); repeatable |
| `--context CONTEXT` | a project context it is made for (`Work`, `Personal`…: made in the web UI, Settings → Contexts; or `any`); repeatable. None: refused in every project that has a context |
| `--description TEXT` | shown with it (default: the template's) |

Models' details (context window, reasoning…) are edited in the web UI (Settings → Model access)
or in `~/.config/handler-ai/providers/NAME.toml`.

## Examples

```bash
handler provider templates
handler provider add anthropic --from anthropic-api --key --context any
pass show openrouter | handler provider add openrouter --from openrouter --key --context Personal
handler provider add local --from llamacpp --model qwen3-coder --context any

handler run local --harness pi        # a provider: say which harness, when several speak it
```

## See also

[`account`](account.md) · [`secret`](secret.md) · [where things are kept](../configuration.md)
