# Handler — Services

Status: **proposal** (2026-10-02). Implemented (2026-10-06): the first interface, `llm/v1`, its
built-in connector and the router, for automations' scripts (contracts §I.5); connectors in
their own sandboxes, bindings of connectors, selection on agents and `handler-service` are not.
Companion to `addons.md` (tools inside the sandbox) and `miniapps.md` (whose runtime connectors
reuse). Once accepted, the normative part moves to a new section of `contracts.md`.

**As built (`llm/v1`).** The interface is data in `handler_control/data/interfaces/llm/v1/`
(`interface.toml`: its limits and its errors `refused`, `limit`, `unavailable`; `tools.json`: one
tool, `llm_complete`, whose schemas are the contract models `LlmRequest` and `LlmResponse`),
checked by `services.py` (S2 closed records, S3 errors, S5 names). The router
(`service_router.py`) listens on a unix socket handlerd mounts in the caller's sandbox and speaks
**MCP: JSON-RPC 2.0, one message per line** (`initialize`, `ping`, `tools/list`, `tools/call`;
decided 2026-10-06: the agents' side reaches the same router through a stdio bridge with no
translation). It validates each call's input and output against the tool's schemas (an invalid
input: JSON-RPC -32602; an output that does not match: `unavailable`), enforces the caller's
selection (the models it may call) and limits (120 s per call, one at a time, 50 per run), logs
each call without its payload, and dispatches to the connector built into handlerd (`llm.py`: the
provider's `openai-chat` or `anthropic` endpoint, its key from the secret store). Its command-line
client is `handler-llm` (`handler_control/data/automation/bin/`).

2026-10-06: services are what Handler offers to **whatever it runs**: agents,
scripts (automations, contracts §I) and apps all call the same router. The first interface is
`llm/v1` (a model call, for automations' scripts through `handler-llm`, I.5); its connector is built
into handlerd and its bindings are the providers. **Calling an agent** is one generic service ("run
agent X with this input": a status and a result, asynchronous), not one interface per agent; an
interface of its own is only for a capability worth sharing or swapping. A part of a job that
needs other privileges (a secret, network) is called as a service and runs in its own sandbox.

## 1. Goal

Let an agent (or a script, or an app) depend on a **capability** (OCR, transcription, web search, sending an email) without
knowing **what provides it**. The agent calls a stable contract; which service fulfils it (a local
container, a mini app, a vendor API) is decided outside the agent, and changed in one place without
touching the agent, its skills or its prompts.

This is dependency inversion, as in an EJB container: the component declares a resource reference,
the deployment descriptor binds it to a real resource. Here the agent uses an **interface**, a
**connector** implements it, a **binding** configures one connector, and handlerd wires interface to
binding when the agent starts.

Later, Handler ships a catalog of standard interfaces, each with the connectors known to implement it.

## 2. Use cases

| # | Use case | What changes between implementations |
|---|---|---|
| US1 | Extract the text of scanned contracts in a project folder | Tesseract in a local container, Mistral OCR, Google Vision |
| US2 | Transcribe meeting recordings | whisper.cpp on the host's GPU, a vendor API |
| US3 | Search the web from an agent with no general egress | SearXNG on the host, Brave Search API, Kagi |
| US4 | Send a notification email at the end of a task | a local SMTP relay, a transactional email API |

In each, the agent's work is the same whatever the provider; the provider changes with cost,
privacy (local vs. remote), quality or availability.

## 3. Concepts

| Concept | Responsibility | Where | How many |
|---|---|---|---|
| **Interface** | what the agent can call: tools, their schemas, their errors, their meaning | `interfaces/<name>/v<N>/` in the repository | one per capability and version: `ocr/v1`, `transcribe/v1` |
| **Connector** | one implementation of one or more interfaces, run outside the agent's sandbox | `connectors/<name>/` in the repository | several per interface: `ocr-tesseract`, `ocr-mistral` |
| **Binding** | one connector with its settings and secret references (the existing `handler.binding/v1`, §6) | `~/.config/handler-ai/bindings/<name>.toml` | one per configured instance: `ocr-mistral-perso` |
| **Service selection** | which binding fulfils each interface an agent uses | the agent (defaults in the project) | per agent |

What the agent knows: the interface (its tools and skill). What it never knows: the connector,
the vendor, its endpoint, its credential.

**Service vs. addon.** An addon puts a tool *inside* the agent's sandbox for the agent to drive
(the Shopify CLI, a browser on the sandbox's display): the agent sees the tool, its env and its
egress. A service is a capability *behind* a contract, running *outside* the sandbox: the agent sees
only the contract. When a capability could be either, ask whether the agent needs the tool itself
(addon) or only its result (service). This also settles two points left open by `addons.md`: the
"narrow operation service outside the sandbox" of §8.2 and the MCP servers hosted outside the
sandbox of open question 5 are connectors.

## 4. The interface contract

### 4.1 Format

An interface is **data**: MCP tool definitions (`name`, `description`, `inputSchema`,
`outputSchema`) in JSON Schema draft 2020-12. The agent already consumes tools in exactly this form,
so the contract is what the agent sees, with no translation layer and no second schema language
(alternatives: §9).

```
interfaces/ocr/v1/
├── interface.toml      metadata, limits, errors
├── tools.json          exactly what the agent sees: an MCP tools/list payload
├── skills/ocr/SKILL.md when and how to use it (what the schemas cannot say)
└── conformance/        fixtures every connector must pass (§4.4)
    ├── cases.toml
    └── invoice.pdf
```

```toml
# interfaces/ocr/v1/interface.toml
apiVersion = "handler.interface/v1"
name = "ocr"
version = 1
description = "Extract text from scanned documents and images"

[limits]
maxFileBytes = 20_000_000
timeoutSeconds = 120

# The only errors a connector may return; the skill tells the agent what to do with each.
[errors]
unsupported_format = "the file is not a PDF or an image"
too_large          = "the file exceeds limits.maxFileBytes"
unavailable        = "the service is down or out of quota; retrying later may work"
```

```json
[{
  "name": "ocr_extract",
  "description": "Extract the text of a PDF or image in the work folder, page by page.",
  "inputSchema": {
    "type": "object",
    "additionalProperties": false,
    "required": ["path"],
    "properties": {
      "path":      { "type": "string", "format": "handler-file", "description": "a file in the work folder" },
      "languages": { "type": "array", "items": { "type": "string", "pattern": "^[a-z]{2}$" } }
    }
  },
  "outputSchema": {
    "type": "object",
    "additionalProperties": false,
    "required": ["pages"],
    "properties": {
      "pages": { "type": "array", "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["text"],
        "properties": {
          "text":   { "type": "string" },
          "blocks": { "type": "array", "items": { "$ref": "#/$defs/block" } }
        }
      }}
    },
    "$defs": {
      "block": {
        "type": "object",
        "additionalProperties": false,
        "required": ["text", "bbox"],
        "properties": {
          "text": { "type": "string" },
          "bbox": { "type": "array", "items": { "type": "number" }, "minItems": 4, "maxItems": 4 }
        }
      }
    }
  }
}]
```

### 4.2 Rules

- S1. **The interface owns everything the model reads**: tool names, descriptions, the skill. The
  agent is served `tools.json`, never the connector's own `tools/list`. A connector that could
  reword a description would change the model's behaviour when swapped.
- S2. **Schemas are closed** (`additionalProperties: false` on every object) and validated in
  both directions by handlerd (§5): an invalid input is refused before it reaches the connector; an
  output that does not match `outputSchema` fails the call with `unavailable` and is logged. A
  connector cannot leak vendor-specific fields the agent would start to rely on.
- S3. **Errors are a closed list per interface.** A connector maps its own failures (HTTP 429, a
  crashed engine) onto them; the agent sees `{"error": "<code>", "message": "…"}`, never a
  vendor's stack trace.
- S4. **Files go through Handler formats.** `format: "handler-file"` is an input path that handlerd reads from
  the agent's scope (a path outside it is refused) and hands to the connector as bytes.
  `format: "handler-output-file"` is a path the agent names, where handlerd writes the bytes the connector
  returns (e.g. `tts/v1`). Connectors never see paths. This works because the scope is mounted at
  the same absolute path in the sandbox and on the host.
- S5. **Tool names start with the interface name** (`ocr_*`), so two interfaces never collide in
  an agent.
- S6. **No optional capabilities.** If some connectors return bounding boxes and others cannot,
  `blocks` is optional in the output and the skill says so; if the difference matters to the agent,
  it is another interface. Feature flags would make connectors silently non-interchangeable.

### 4.3 Versions

A version is a folder, and a published version is **frozen**: any change, even an added optional
field, is a new version (`ocr/v2`). There is no "compatible change" to judge. A connector lists the
versions it implements (`implements = ["ocr/v1", "ocr/v2"]`); an agent uses exactly one version of
each interface.

### 4.4 Conformance

What "a connector implements `ocr/v1`" means is decided by the interface's fixtures, not by the
connector's claim (the idea of Dapr's per-building-block conformance tests).

```toml
# interfaces/ocr/v1/conformance/cases.toml
[[case]]
name = "invoice text"
tool = "ocr_extract"
input = { path = "invoice.pdf" }
expect.pages.minItems = 1
expect.contains = ["INV-2024-0042", "Total"]   # a quality floor, not an exact output

[[case]]
name = "rejects a zip"
tool = "ocr_extract"
input = { path = "archive.zip" }
expect.error = "unsupported_format"
```

Outputs vary between vendors (OCR text, search results), so cases assert properties (`contains`,
counts, error codes) on top of the schema, never exact values. `handler connector check <connector>
--binding <binding>` runs every case of every implemented version through the real router (so
schemas are validated too) and reports each case. A connector is listed under an interface in the
catalog once it passes; a remote connector needs a binding with real credentials to be checked,
like the opt-in credential tests.

## 5. Runtime

```
agent sandbox                        handlerd (host)                       connector sandbox
harness ──stdio──► handler-service ocr ──socket──► service router ──socket──► connector (MCP server)
                   (toolbox command)          · serves tools.json          · secrets in its env
                                              · validates in and out (S2)  · egress: its target only
                                              · reads/writes handler files (S4)· strict confinement
                                              · applies limits, logs calls
```

- **The connector runs in its own sandbox**, with the mini app runtime (`contracts.md` H.3): strict
  confinement, a socket folder, egress exactly its manifest's, secrets as env. The agent's sandbox
  holds no credential and no egress for the service; this is the "operation service outside the
  sandbox" of `addons.md` §8.3, so it is safe in `bypass` mode.
- **The agent side is one generic stdio bridge**, `handler-service <interface>`, in the toolbox: it
  relays MCP between stdio and a socket handlerd mounts into the sandbox. `render` adds one
  `mcpServers` entry per interface the agent uses, the same path as addon MCP servers (G4, B.3), so
  every harness that accepts stdio MCP servers can use services, Vibe included.
- **The router is the only place that knows the binding.** It resolves interface → binding for the
  calling agent, starts the connector if needed, and enforces S1–S4 and the interface's limits.
  Each call is logged per session (interface, tool, duration, error code; never the payload).
- **One connector instance per binding**, started on first call, shared by every agent that selects
  the binding, stopped when idle. A heavy local model (an OCR or speech model) loads once; a remote
  connector is a small stateless proxy.

Between the router and the connector, the protocol is MCP over the socket with the interface's tool
names. A connector may therefore wrap an existing MCP server by renaming its tools and reshaping
its results.

## 6. Connectors and bindings

```
connectors/ocr-mistral/
├── connector.toml
├── main.ts            Deno, like a mini app backend: serves MCP on HANDLER_CONNECTOR_SOCKET
└── PROVISIONING.md    how to get the least-privilege key a binding needs
```

```toml
# connectors/ocr-mistral/connector.toml
apiVersion = "handler.connector/v1"
name = "ocr-mistral"
description = "Mistral OCR API"
implements = ["ocr/v1"]
egress = ["api.mistral.ai:443"]

[secretSlots.api_key]
env = "MISTRAL_API_KEY"
required = true

[settings.model]
env = "MISTRAL_OCR_MODEL"
description = "defaults to mistral-ocr-latest"
```

A **binding** stays `handler.binding/v1`: it names exactly one of `addon` or `connector`, and fills its
slots the same way (G2 rules, secret references, the same form in the web UI). It is the same
concept, "a configured instance of something Handler knows how to use", so it stays one concept.

```toml
# ~/.config/handler-ai/bindings/ocr-mistral-perso.toml
apiVersion = "handler.binding/v1"
connector = "ocr-mistral"
description = "Mistral OCR, personal key"
secrets = { api_key = { command = ["pass", "show", "mistral/ocr"] } }
```

**Selection** maps interfaces to bindings: `services = { ocr = "ocr-mistral-perso" }` on an
agent, with defaults on the project. Swapping the service is changing that one value,
or one dropdown in the agent editor; the next session uses the new connector with the same tools.
A project may declare `requires = ["ocr/v1"]`: its agents cannot start until each required
interface has a binding, with an error naming it.

Checks when an agent is saved (like G3): each selected binding is valid, is a
connector binding, and its connector implements the interface's version; an agent uses each
interface once.

## 7. The catalog

- `interfaces/` holds the standard interfaces as they are written: `ocr`, `transcribe`, `tts`,
  `web-search`, `embed`, `image-gen`, `send-email`.
- `connectors/` holds the known implementations; each passes the conformance of what it
  implements (§4.4).
- The web UI lists, per interface, its connectors and the bindings already made; choosing a
  connector opens the binding form for its slots.

Like addons (`addons.md` open question 4), both live in the repository for now; a user directory
for personal ones, or downloading third-party ones, is a later decision.

## 8. Code

| Part | Where |
|---|---|
| `InterfaceManifest`, `ConformanceCase`, `ConnectorManifest`; `Binding` with `connector` | `packages/contracts/src/handler_contracts/interface.py`, `connector.py`, `addon.py` (`extra="forbid"`, schemas in `schemas/`) |
| Loading and checking interfaces (draft 2020-12, closed objects, S5 prefixes, `handler-*` formats only on strings) and connectors | `packages/control-plane/src/handler_control/services.py` |
| Router: per-binding connector lifecycle, one compiled validator per tool (`jsonschema`), file formats, limits, call log | `packages/control-plane/src/handler_control/service_router.py` |
| Connector sandbox | `compose.connector_sandbox_spec`, next to `compose.app_sandbox_spec` |
| `services` → `mcpServers` entries and the socket mount | `compose.py` (the control plane composes; `render` only receives MCP servers, B.3) |
| Bridge `handler-service` | a file of the launch, like `handler-sandbox-env` (`handler_harness/data/`) |
| `handler connector check`, `handler service list` | `packages/cli` (through the Control API) |
| Normative contract | a new section of `contracts.md`; tests in `tests/services` |

## 9. Alternatives considered

| Approach | Verdict |
|---|---|
| **MCP tool definitions (JSON Schema)** as the interface | **chosen**: it is what the model sees; no conversion |
| OpenAPI | describes HTTP endpoints the agent never sees; would need converting to tools |
| Protobuf, WIT | strong typing and code generation, but MCP and LLMs speak JSON Schema: a conversion everywhere |
| TypeSpec | pleasant to write, but one more compiler step for data Handler could read directly |
| Connector inside the agent's sandbox (an addon with an MCP server) | the agent sees the credential, the egress and the vendor; swapping changes the tools it sees |
| Plain MCP servers selected per agent, no interface | no contract: tool names and outputs change with the server, so prompts and skills break on a swap |
| Interface versions with compatible changes (semver) | needs a judgement on every change; frozen versions are simpler while there are no users |

Prior art for the model: Dapr building blocks and components (stable API, swappable component,
conformance suite), Radius recipes and the Score spec (a workload declares a resource type, the
platform binds it), Crossplane composite resources and compositions, Kubernetes Service Binding,
JNDI resource references and the OSGi service registry, ports and adapters. MCP gateways (Docker
MCP Gateway, ToolHive) host servers outside the agent and hold their credentials, but do not fix the
interface.

## 10. Open questions

1. Connector runtime: Deno only (the mini app runtime, cheapest), or any image (to wrap an existing
   OCR or speech container as is)? A local model needing a GPU pushes towards images.
2. Should a mini app be able to *be* a connector (an app the person also uses, exposing an
   interface to agents)?
3. ~~A CLI generated from the same schemas, or MCP only?~~ A CLI is needed: scripts call services
   through one (`handler-llm` is the first, hand-written); agents may use it too.
4. Large outputs (a 300-page OCR): return in one call, or let the interface write to an
   `handler-output-file` and return a summary?
5. Connector instances shared across agents: does any interface need per-agent state (a search
   session, a mailbox), and so one instance per agent?
6. Interfaces in a user directory, and their trust: an interface's descriptions go straight to the
   model, so a third-party one is a prompt-injection surface and should be reviewed like a skill.
