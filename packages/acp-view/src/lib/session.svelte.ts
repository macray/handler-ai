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
  | { kind: "user"; text: string; images: PromptImage[] }
  | { kind: "agent"; text: string }
  | { kind: "thought"; text: string }
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

  /** A turn is in progress and its prompt is already shown: the agent's echo of it (if any,
   *  possibly after other updates) is skipped until the turn ends. */
  inTurn = false;

  /** Append streamed text to the last entry of the same kind, or start a new one. */
  private appendText(kind: "user" | "agent" | "thought", text: string): void {
    const last = this.entries.at(-1);
    if (last && last.kind === kind) last.text += text;
    else if (kind === "user") this.entries.push({ kind, text, images: [] });
    else this.entries.push({ kind, text });
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
        this.entries.push({
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
        const last = this.entries.at(-1);
        if (last?.kind === "plan") last.entries = update.entries;
        else this.entries.push({ kind: "plan", entries: update.entries });
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
        this.entries.push({ kind: "notice", text: noticeText(update), severity: severityOf(update) });
        break;
      default:
        break; // usage, compaction…: not shown
    }
  }

  private appendImage(image: PromptImage): void {
    const last = this.entries.at(-1);
    const { mimeType, data } = image;
    if (last?.kind === "user") last.images.push({ mimeType, data });
    else this.entries.push({ kind: "user", text: "", images: [{ mimeType, data }] });
  }

  /** The user's own prompt, shown immediately (agents do not always echo it). */
  addUserPrompt(text: string, images: PromptImage[] = []): void {
    this.entries.push({ kind: "user", text, images });
    this.inTurn = true;
  }
}

function noticeText(update: object): string {
  const u = update as { title?: string; description?: string };
  return [u.title, u.description].filter(Boolean).join(": ");
}

function severityOf(update: object): string | undefined {
  return (update as { severity?: string }).severity;
}
