// One attachment to a daemon-held session (contract F.4), using the official ACP SDK, over any
// transport: the handler web UI's WebSocket, or the remote client's encrypted mailbox.
//
// The UI is a plain ACP client: it advertises no fs/terminal capability (the daemon enforces
// that anyway, P1) and implements only what a person answers — permission requests. Attaching
// is `session/load`: the daemon replays the conversation, then the turn in progress (if any)
// continues live; `_handler/…` notifications tell whether the agent is busy. Other clients may be
// attached (F.7): their prompts arrive as `user_message_chunk`, and a permission request one of
// them answered is withdrawn (`_handler/permission_resolved`). Handler says things in the
// conversation too (`_handler/line`): a host its network filter refused, answered here with
// `_handler/decide_host` (F.9).
import {
  ClientSideConnection,
  PROTOCOL_VERSION,
  type Client,
  type InitializeResponse,
  type LoadSessionResponse,
  type RequestPermissionOutcome,
  type RequestPermissionRequest,
  type StopReason,
  type Stream,
} from "@agentclientprotocol/sdk";
import type { PromptImage } from "./images";
import { SessionState, type HostDecision } from "./session.svelte";

/** How a transport ended (a WebSocket close code and reason, or the remote equivalents). */
export interface Closed {
  code: number;
  reason: string;
}

/** An open transport: the ACP message stream, and how to close it. */
export interface Transport {
  stream: Stream;
  close(): void;
}

/** Opens a transport; calls `onClose` once when it ends, whoever ends it. */
export type OpenTransport = (onClose: (closed: Closed) => void) => Promise<Transport>;

export interface PendingPermission {
  request: RequestPermissionRequest;
  answer: (outcome: RequestPermissionOutcome) => void;
}

export class AcpConnection {
  readonly session = new SessionState();
  permissions = $state.raw<PendingPermission[]>([]); // raw: entries are compared by identity
  closed = $state<Closed | null>(null);
  busy = $state(false);
  turnStartedAt = $state<number | null>(null); // ms, while busy: the turn's elapsed time
  interrupting = $state(false); // cancelled, until the turn ends
  sessionId = $state<string | null>(null);
  agent = $state<InitializeResponse | null>(null);

  /** A turn this attachment did not start has ended. */
  onTurnEnded: (() => void) | null = null;

  private conn: ClientSideConnection | null = null;
  private transport: Transport | null = null;

  async connect(open: OpenTransport): Promise<void> {
    this.transport = await open((closed) => {
      this.closed = closed;
      this.idle();
      for (const p of this.permissions) p.answer({ outcome: "cancelled" });
      this.permissions = [];
    });
    const stream = this.transport.stream;
    const client: Client = {
      requestPermission: (request) =>
        new Promise((resolve) => {
          const entry: PendingPermission = {
            request,
            answer: (outcome) => {
              this.permissions = this.permissions.filter((p) => p !== entry);
              resolve({ outcome });
            },
          };
          this.permissions = [...this.permissions, entry];
        }),
      sessionUpdate: (notification) => {
        this.session.apply(notification.update);
      },
      extNotification: async (method, params) => {
        if (method === "_handler/session_state") {
          this.busy = Boolean(params.busy);
          this.session.inTurn = this.busy; // its prompt was in the replayed history
          const stop = typeof params.lastStopReason === "string" ? params.lastStopReason : null;
          this.session.lastStop = this.busy || stop === "end_turn" ? null : stop;
          const started = typeof params.turnStartedAt === "string" ? Date.parse(params.turnStartedAt) : NaN;
          this.turnStartedAt = this.busy ? (Number.isNaN(started) ? (this.turnStartedAt ?? Date.now()) : started) : null;
          if (!this.busy) this.interrupting = false;
        }
        if (method === "_handler/permission_resolved") {
          // answered by another client: our answer would be dropped, so just close the prompt
          for (const p of this.permissions) {
            if (p.request.toolCall.toolCallId === params.toolCallId) p.answer({ outcome: "cancelled" });
          }
        }
        if (method === "_handler/line") this.session.line(params);
        if (method === "_handler/turn_ended") {
          this.idle(); // a turn started before this attachment (e.g. before a reload)
          this.onTurnEnded?.();
        }
      },
    };
    this.conn = new ClientSideConnection(() => client, stream);
    this.agent = await this.conn.initialize({
      protocolVersion: PROTOCOL_VERSION,
      clientCapabilities: { fs: { readTextFile: false, writeTextFile: false }, terminal: false },
      clientInfo: { name: "handler-web-ui", title: "Handler", version: "0.1.0" },
    });
  }

  /** Attach to the daemon's session: its history is replayed as session/update. */
  async loadSession(sessionId: string, cwd: string): Promise<void> {
    const result = await this.required().loadSession({ sessionId, cwd, mcpServers: [] });
    this.sessionId = sessionId;
    this.adopt(result);
  }

  private adopt(result: LoadSessionResponse): void {
    this.session.modes = result.modes?.availableModes ?? [];
    this.session.currentMode = result.modes?.currentModeId ?? null;
    this.session.configOptions = result.configOptions ?? [];
  }

  /** Whether the agent takes images in a prompt (ACP `promptCapabilities.image`). */
  get takesImages(): boolean {
    return Boolean(this.agent?.agentCapabilities?.promptCapabilities?.image);
  }

  /** A turn: the images first, then the text (either may be empty, not both). When it fails, its
   *  prompt leaves the timeline if nothing came after it (the page gives it back to the input). */
  async prompt(text: string, images: PromptImage[] = []): Promise<StopReason> {
    this.session.addUserPrompt(text, images);
    const shown = this.session.entries.at(-1);
    this.busy = true;
    this.turnStartedAt = Date.now();
    try {
      const result = await this.required().prompt({
        sessionId: this.requiredSession(),
        prompt: [
          ...images.map((image) => ({ type: "image" as const, ...image })),
          ...(text ? [{ type: "text" as const, text }] : []),
        ],
      });
      return result.stopReason;
    } catch (e) {
      if (this.session.entries.at(-1) === shown) this.session.entries.pop();
      throw e;
    } finally {
      this.idle();
    }
  }

  /** Interrupt the turn in progress, whoever started it. As ACP asks of a client that cancels,
   *  its pending permission requests are answered `cancelled`. */
  async cancel(): Promise<void> {
    if (!this.busy) return;
    this.interrupting = true;
    await this.required().cancel({ sessionId: this.requiredSession() });
    for (const p of this.permissions) p.answer({ outcome: "cancelled" });
  }

  private idle(): void {
    if (this.busy && this.turnStartedAt !== null) this.session.turnTook(Date.now() - this.turnStartedAt);
    this.busy = false;
    this.session.inTurn = false;
    this.turnStartedAt = null;
    this.interrupting = false;
  }

  /** A refused host allowed for this agent, or kept blocked: handlerd saves it to the agent and
   *  applies it to its running sandboxes; every attached client then gets its line (F.9). */
  async decideHost(host: string, decision: HostDecision): Promise<void> {
    await this.required().extMethod("_handler/decide_host", { host, decision });
  }

  async setMode(modeId: string): Promise<void> {
    await this.required().setSessionMode({ sessionId: this.requiredSession(), modeId });
    this.session.currentMode = modeId;
  }

  async setOption(configId: string, value: string): Promise<void> {
    const result = await this.required().setSessionConfigOption({
      sessionId: this.requiredSession(),
      configId,
      value,
    });
    if (result?.configOptions) this.session.configOptions = result.configOptions;
  }

  close(): void {
    this.transport?.close();
  }

  private required(): ClientSideConnection {
    if (!this.conn) throw new Error("not connected");
    return this.conn;
  }

  private requiredSession(): string {
    if (!this.sessionId) throw new Error("no session");
    return this.sessionId;
  }
}
