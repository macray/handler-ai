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

export type Entry =
  | { kind: "user"; text: string; images: PromptImage[]; ms?: number } // ms: how long its turn took, when seen
  | { kind: "agent"; text: string }
  | { kind: "thought"; text: string; ms?: number } // ms: how long it thought, once it went on
  | ToolEntry
  | { kind: "plan"; entries: PlanEntry[] }
  | { kind: "notice"; text: string; severity?: string };

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
      case "notice":
        this.push({ kind: "notice", text: noticeText(update), severity: severityOf(update) });
        break;
      default:
        break; // usage, compaction…: not shown
    }
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
      if (e?.kind === "user") {
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
