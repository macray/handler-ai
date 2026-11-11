// View model of one ACP session: folds `session/update` notifications into what the UI shows.
// Used for live sessions (connection.ts).
import type {
  AvailableCommand,
  ContentBlock,
  PlanEntry,
  SessionConfigOption,
  SessionMode,
  SessionUpdate,
  ToolCallContent,
  ToolCallLocation,
  ToolCallStatus,
  ToolKind,
} from "@agentclientprotocol/sdk";
import type { PromptImage } from "./images";

export interface ToolEntry {
  kind: "tool";
  id: string;
  title: string;
  toolKind?: ToolKind | null;
  status: ToolCallStatus;
  content: ToolCallContent[];
  locations: ToolCallLocation[];
}

/** What the person answered for a host the network filter refused (F.9). */
export type HostDecision = "allowed" | "kept blocked";

/** A host Handler's network filter refused (F.9, a line of Handler's own): one per host per
 *  turn, its count raised by each repeat, and the person's answer once given. */
export interface HostEntry {
  kind: "host";
  card: number; // the seq of its first line in the session's log
  host: string;
  count: number; // refused so far in its turn; 0: only held
  decision: HostDecision | null;
  until: string | null; // a request held for the answer: when the agent stops waiting (ISO time)
  queued: boolean; // the answer is told to the agent once its turn ends
}

/** The model's host failing to connect (F.9, a line of Handler's own): once per turn. */
export interface ModelEntry {
  kind: "model";
  host: string; // host:port
  error: string; // "connection refused"…
  provider: string | null; // the provider it runs on
  local: boolean; // a server on this computer
}

/** What Handler says of a model that does not answer. */
export function modelText(e: ModelEntry): string {
  const local = e.local ? " Is the server listening on 0.0.0.0?" : "";
  return `The model at ${e.host} does not answer (${e.error}).${local}`;
}

export type Entry =
  | { kind: "user"; text: string; images: PromptImage[]; ms?: number } // ms: how long its turn took, when seen
  | { kind: "agent"; text: string }
  | { kind: "thought"; text: string; ms?: number } // ms: how long it thought, once it went on
  | ToolEntry
  | { kind: "plan"; entries: PlanEntry[] }
  | { kind: "notice"; text: string; severity?: string }
  | { kind: "told"; text: string; ms?: number } // Handler's message to the agent: a turn of its own
  | HostEntry
  | ModelEntry;

/** Whether an entry starts a turn: the person's prompt, or Handler's message to the agent. */
export function startsTurn(e: Entry | undefined): boolean {
  return e?.kind === "user" || e?.kind === "told";
}

export function blockText(block: ContentBlock): string {
  switch (block.type) {
    case "text":
      return block.text;
    case "resource_link":
      return `[${block.name}](${block.uri})`;
    case "resource":
      return "text" in block.resource ? block.resource.text : `(${block.resource.uri})`;
    default:
      return `(${block.type})`;
  }
}

export class SessionState {
  entries = $state<Entry[]>([]);
  modes = $state<SessionMode[]>([]);
  currentMode = $state<string | null>(null);
  configOptions = $state<SessionConfigOption[]>([]);
  commands = $state<AvailableCommand[]>([]);
  title = $state<string | null>(null);
  /** The agent's current plan: its last plan update. */
  plan = $state<PlanEntry[]>([]);
  /** How full the agent's context is, as it last said (`usage_update`); null: it never said. */
  usage = $state<{ used: number; size: number } | null>(null);
  /** How the last turn ended when it did not end normally (`cancelled`…), until the next one. */
  lastStop = $state<string | null>(null);

  /** A turn is in progress and its prompt is already shown: the agent's echo of it (if any,
   *  possibly after other updates) is skipped until the turn ends. */
  inTurn = false;

  /** Append streamed text to the last entry of the same kind, or start a new one. */
  private appendText(kind: "user" | "agent" | "thought", text: string): void {
    const last = this.entries.at(-1);
    if (last && last.kind === kind) last.text += text;
    else if (kind === "user") this.push({ kind, text, images: [] });
    else this.push({ kind, text });
  }

  private thinking = 0; // when the last thought started (ms)

  /** A new entry; a thought before it has ended (replayed ones end at once: no time said). */
  private push(entry: Entry): void {
    const last = this.entries.at(-1);
    if (last?.kind === "thought" && last.ms === undefined) last.ms = Date.now() - this.thinking;
    if (entry.kind === "thought") this.thinking = Date.now();
    this.entries.push(entry);
  }

  private tool(id: string): ToolEntry | undefined {
    for (let i = this.entries.length - 1; i >= 0; i--) {
      const e = this.entries[i];
      if (e?.kind === "tool" && e.id === id) return e;
    }
    return undefined;
  }

  apply(update: SessionUpdate): void {
    switch (update.sessionUpdate) {
      case "user_message_chunk":
        if (this.inTurn) break;
        if (update.content.type === "image") this.appendImage(update.content);
        else this.appendText("user", blockText(update.content));
        break;
      case "agent_message_chunk":
        this.appendText("agent", blockText(update.content));
        break;
      case "agent_thought_chunk":
        this.appendText("thought", blockText(update.content));
        break;
      case "tool_call":
        this.push({
          kind: "tool",
          id: update.toolCallId,
          title: update.title,
          toolKind: update.kind,
          status: update.status ?? "pending",
          content: update.content ?? [],
          locations: update.locations ?? [],
        });
        break;
      case "tool_call_update": {
        const tool = this.tool(update.toolCallId);
        if (!tool) break;
        if (update.title) tool.title = update.title;
        if (update.status) tool.status = update.status;
        if (update.kind) tool.toolKind = update.kind;
        if (update.content) tool.content = update.content;
        if (update.locations) tool.locations = update.locations;
        break;
      }
      case "plan": {
        this.plan = update.entries;
        const last = this.entries.at(-1);
        if (last?.kind === "plan") last.entries = update.entries;
        else this.push({ kind: "plan", entries: update.entries });
        break;
      }
      case "available_commands_update":
        this.commands = update.availableCommands;
        break;
      case "current_mode_update":
        this.currentMode = update.currentModeId;
        break;
      case "config_option_update":
        this.configOptions = update.configOptions;
        break;
      case "session_info_update":
        if (update.title !== undefined) this.title = update.title ?? null;
        break;
      case "usage_update":
        this.usage = { used: update.used, size: update.size };
        break;
      case "notice":
        this.push({ kind: "notice", text: noticeText(update), severity: severityOf(update) });
        break;
      default:
        break; // compaction…: not shown
    }
  }

  /** A line of Handler's own (`_handler/line`, F.5): a host refused or held (a new card, or its
   *  card's count raised, its wait ended), the person's answer for it (said on its cards so far),
   *  Handler's message to the agent (a turn of its own, with every queued answer), or the
   *  model's host that does not answer. */
  line(line: Record<string, unknown>): void {
    const { event, host, card, count, decision, until, queued, text, error, provider, local } = line;
    if (event === "told agent" && typeof text === "string") {
      for (const e of this.entries) if (e.kind === "host") e.queued = false;
      this.push({ kind: "told", text });
      this.inTurn = true;
      this.lastStop = null;
      return;
    }
    if (typeof host !== "string") return;
    if (event === "model unreached") {
      const why = typeof error === "string" ? error : "connection failed";
      this.push({ kind: "model", host, error: why, provider: typeof provider === "string" ? provider : null, local: local === true });
      return;
    }
    if (event === "host blocked" && typeof card === "number") {
      const times = typeof count === "number" ? count : 1;
      const wait = typeof until === "string" ? until : null;
      const known = this.entries.find((e): e is HostEntry => e.kind === "host" && e.card === card);
      if (known) {
        known.count = times;
        known.until = wait;
      } else this.push({ kind: "host", card, host, count: times, decision: null, until: wait, queued: false });
    } else if (event === "host decided" && (decision === "allowed" || decision === "kept blocked")) {
      for (const e of this.entries) {
        if (e.kind !== "host" || e.host !== host || e.decision !== null) continue;
        e.decision = decision;
        e.until = null;
        e.queued = queued === true;
      }
    }
  }

  /** The hosts the filter refused in this session that the person has not answered yet. */
  get undecided(): string[] {
    const hosts = this.entries.filter((e): e is HostEntry => e.kind === "host" && e.decision === null).map((e) => e.host);
    return [...new Set(hosts)];
  }

  private appendImage(image: PromptImage): void {
    const last = this.entries.at(-1);
    const { mimeType, data } = image;
    if (last?.kind === "user") last.images.push({ mimeType, data });
    else this.push({ kind: "user", text: "", images: [{ mimeType, data }] });
  }

  /** The turn in progress ended after `ms`: said under it. */
  turnTook(ms: number): void {
    for (let i = this.entries.length - 1; i >= 0; i--) {
      const e = this.entries[i];
      if (e?.kind === "user" || e?.kind === "told") {
        e.ms = ms;
        return;
      }
    }
  }

  /** The user's own prompt, shown immediately (agents do not always echo it). */
  addUserPrompt(text: string, images: PromptImage[] = []): void {
    this.push({ kind: "user", text, images });
    this.inTurn = true;
    this.lastStop = null;
  }
}

function noticeText(update: object): string {
  const u = update as { title?: string; description?: string };
  return [u.title, u.description].filter(Boolean).join(": ");
}

function severityOf(update: object): string | undefined {
  return (update as { severity?: string }).severity;
}

/** A token count, short: 950, 84k, 1.2M. */
export function tokens(n: number): string {
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${Math.round(n / 1000)}k`;
  return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
}

/** How full the context is: its percentage (null when the agent gives no window size), and
 *  what is said of it, short and in full. */
export function contextFill(usage: { used: number; size: number }): { percent: number | null; short: string; full: string } {
  const used = usage.used.toLocaleString();
  if (usage.size <= 0) return { percent: null, short: `${tokens(usage.used)} tokens`, full: `${used} tokens in its context` };
  const percent = Math.min(100, Math.round((usage.used / usage.size) * 100));
  return {
    percent,
    short: `${percent}% · ${tokens(usage.used)} / ${tokens(usage.size)}`,
    full: `${used} of ${usage.size.toLocaleString()} tokens in its context (${percent}%)`,
  };
}
