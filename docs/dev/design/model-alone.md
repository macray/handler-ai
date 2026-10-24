# The model alone

An agent with no program: each turn is one model call, on a provider, in seconds. Normative:
[contracts §D.18](../contracts.md), *The model alone*.

## Why

Many agents need no program. A quick question, a draft from a form, a job that judges a text
("can this mail be sent as it is?") or pulls data out of one: a container, an agent program
starting in it and its tool loop are minutes of start and tokens for what one call answers.
Such an agent is also safer: with no files, no network and no tools, there is nothing it could
do on its own, whatever its input tells it.

## Choices

- **One of the programs, not a new kind of agent.** The editor already asks who works; the
  model alone is the other answer. Chat, Brief and Job stay what they are, so a model-alone job
  is run by an automation or an app like any job, and its result is checked the same way.
- **Per agent, not per model.** A session may run with another model than its agent's, each
  naming its own program. Had the model alone been one of them, what an agent may do (its page's
  *What it may do*) would depend on the session. So it is the agent's: every session of it has
  no sandbox.
- **handlerd's own ACP agent, behind the session's link.** A session talks ACP to what is
  behind its `AgentLink`: a sandbox's stdio, or `ModelAgent` in handlerd. Nothing else knows the
  difference: attachments, the event log, the policy pipeline, runs and their result, idle
  stops, the phone. The alternatives were a separate path for runs only (Chat and Brief
  would be missing) or a "harness" image calling the model (a sandbox for one HTTP call, and
  the key in it).
- **The key stays in handlerd.** The call is `llm.py`'s, the one scripts use (I.5): the
  provider's key is resolved by handlerd and never leaves it; an endpoint written for
  containers is called on the loopback.
- **Knowledge put into the call.** The agent's knowledge notes go into the system prompt at
  each call (192 KiB at most, refused when saved beyond): the model alone has no way to read a
  file. A lighter harness to read them was left out (keep it simple; a harness for one task may
  come later).
- **No tools, as a hard limit.** No request offers any, an answer calling one fails the turn,
  MCP servers are refused, and the model agent has no code that sends a client request; the
  architecture test keeps its imports to `llm`, `knowledge`, `services`, `settings`.
- **Providers only.** An account is a subscription its vendor's program signs in to; Handler
  calls APIs. `ProviderInfo.modelAlone` says which providers can serve it.

## Not built yet

- Streaming: the answer comes as one message (a call takes seconds).
- Images and other non-text content in a prompt.
- Plain connections (`handler acp` from an editor) and terminals: refused, there is nothing to
  drive.
