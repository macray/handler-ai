// The chat sessions being supervised. The daemon holds them (contract F): an agent outlives this
// page, so a reload re-attaches and the turn in progress carries on. Several tabs (or a paired
// phone) may be attached at once (F.7); only beyond the daemon's limit is the oldest closed
// (4001), and this tab then shows the session as open elsewhere.
//
// The sidebar lists the sessions this browser opened (ids in localStorage), attached while they
// run, and the running sessions started elsewhere (the CLI, an editor, a phone), polled and not
// attached until opened: attaching would keep them from stopping when idle.
// Views use only this module's interface (`sessions`, `LiveSession`).
import { SvelteSet } from "svelte/reactivity";
import { AcpConnection } from "@handler/acp-view/lib/connection.svelte";
import type { Prompt, PromptImage } from "@handler/acp-view/lib/images";
import { websocketTransport } from "./acp/transport";
import { token } from "./auth";
import { api, ApiError } from "./api";
import type { Agent, ModelAccess, Session } from "./contracts.gen";

export type SessionStatus = "starting" | "needs-you" | "working" | "replied" | "idle" | "elsewhere" | "stopped" | "failed";

export const STATUS_LABEL: Record<SessionStatus, string> = {
  starting: "starting",
  "needs-you": "needs you",
  working: "working",
  replied: "replied",
  idle: "idle",
  elsewhere: "open elsewhere",
  stopped: "stopped",
  failed: "failed",
};

/** Close code of an attachment closed because too many clients were attached (F.7). */
const ATTACHED_ELSEWHERE = 4001;

export class LiveSession {
  info = $state() as Session; // the daemon's view, refreshed on each (re)attach
  agent = $state() as Agent;
  conn = $state<AcpConnection | null>(null);
  starting = $state(false);
  /** While starting, where it is (both real: the daemon answers once the agent runs, then the
   *  conversation is replayed); `reattach`: its sandbox was already running; `since`: ms. */
  startup = $state<{ step: "sandbox" | "conversation"; reattach: boolean; since: number } | null>(null);
  error = $state<string | null>(null);
  unread = $state(false); // a turn ended while the user was looking elsewhere
  draft = $state(""); // composer text, kept while switching sessions
  draftImages = $state<PromptImage[]>([]); // and its images
  queued = $state<Prompt | null>(null); // typed while the agent works: sent when its turn ends
  discovered = $state(false); // started elsewhere, not opened here: not attached, not saved

  constructor(info: Session, agent: Agent) {
    this.info = info;
    this.agent = agent;
  }

  get key(): string {
    return this.info.id;
  }

  get title(): string | null {
    return this.conn?.session.title ?? this.info.title ?? null;
  }

  get live(): boolean {
    return Boolean(this.conn && !this.conn.closed && this.conn.sessionId);
  }

  get elsewhere(): boolean {
    return this.conn?.closed?.code === ATTACHED_ELSEWHERE;
  }

  get status(): SessionStatus {
    if (this.starting) return "starting";
    if (this.elsewhere) return "elsewhere";
    if (!this.conn && (this.info.state === "running" || this.info.state === "starting")) {
      // not attached: what the daemon says
      if (this.info.pendingPermissions) return "needs-you";
      return this.info.busy ? "working" : "idle";
    }
    // not running: failed (its first start failed: it never runs) or stopped (resumable)
    if (!this.live || !this.conn) return this.info.state === "failed" ? "failed" : "stopped";
    if (this.conn.permissions.length) return "needs-you";
    if (this.conn.busy) return "working";
    if (this.unread) return "replied";
    return "idle";
  }
}

const STORAGE = "handler.sessions.open"; // ids of the sessions this browser keeps in its sidebar
const POLL_MS = 5000; // sessions started elsewhere

class SessionStore {
  list = $state<LiveSession[]>([]);
  restored = $state(false); // the sidebar is known (restore() done)
  loadError = $state<string | null>(null); // the daemon's sessions could not be listed
  private closed = new Set<string>(); // closed here: not adopted again (a stale link, a race)
  /** Closed here, the daemon still stopping them: no longer live, though the daemon says so. */
  stopping = new SvelteSet<string>();
  /** The session on screen (set by its view): turns ending there are not "unread". */
  viewing = $state<string | null>(null);

  get attention(): number {
    return this.list.filter((s) => s.status === "needs-you" || s.status === "replied").length;
  }

  get(key: string): LiveSession | undefined {
    return this.list.find((s) => s.key === key);
  }

  /** A new chat session with an agent (or one resuming an ACP session).
   *  `prompt`: the request, sent by the daemon once the agent runs; `model`: one of the agent's
   *  (default: its first, D.1). */
  async start(agent: Agent, resume?: string, prompt?: string, model?: ModelAccess): Promise<LiveSession> {
    return this.open(await api.createSession(agent.id, resume, prompt, model), agent);
  }

  /** Show a daemon session in the sidebar and attach to it (restarting it if stopped). */
  open(info: Session, agent: Agent): LiveSession {
    this.closed.delete(info.id);
    const existing = this.get(info.id);
    if (existing) return existing;
    const session = new LiveSession(info, agent);
    this.list.push(session); // class instances are not proxied: `session` is the stored object
    this.save();
    void this.connect(session);
    return session;
  }

  /** A session of the daemon by id (e.g. a link printed by `handler run`): shown and attached. */
  async adopt(key: string): Promise<LiveSession | null> {
    const existing = this.get(key);
    if (existing || this.closed.has(key)) return existing ?? null;
    try {
      const info = await api.session(key);
      return this.open(info, await api.agent(info.agentId));
    } catch {
      return null;
    }
  }

  /** Opened here: a discovered session becomes one of this browser's, attached while it runs. */
  view(session: LiveSession): void {
    if (session.discovered) {
      session.discovered = false;
      this.save();
    }
    const running = session.info.state === "running" || session.info.state === "starting";
    if (!session.conn && !session.starting && running) void this.connect(session);
  }

  /** The running sessions started elsewhere; those that stopped without being opened go. */
  async discover(): Promise<void> {
    // a request that fails: next time (the daemon is away); a throw would end the polling (restore)
    let all: Session[];
    try {
      all = await api.sessions();
    } catch {
      return;
    }
    const byId = new Map(all.map((s) => [s.id, s]));
    this.list = this.list.filter((s) => !s.discovered || byId.get(s.key)?.state === "running");
    // a check's run (D.20) is the agent's checks', not a session of yours
    const running = (s: Session) => (s.state === "running" || s.state === "starting") && !this.closed.has(s.id) && s.origin !== "check";
    const unknown = all.filter((s) => running(s) && !this.get(s.id));
    let agents = new Map<string, Agent>();
    try {
      if (unknown.length) agents = new Map((await api.agents()).map((a) => [a.id, a]));
    } catch {
      return;
    }
    for (const info of unknown) {
      const agent = agents.get(info.agentId);
      if (!agent || this.get(info.id)) continue;
      const session = new LiveSession(info, agent);
      session.discovered = true;
      this.list.push(session);
    }
    // not attached, or its attachment closed: what the daemon says (why the agent stopped)
    for (const s of this.list) if (!s.live && byId.has(s.key)) s.info = byId.get(s.key)!;
  }

  /** An agent changed (e.g. renamed): show it so in its open sessions. */
  updateAgent(agent: Agent): void {
    for (const s of this.list) if (s.agent.id === agent.id) s.agent = agent;
  }

  /** (Re)attach: the daemon replays the conversation; a stopped session is restarted. */
  async connect(session: LiveSession): Promise<void> {
    const before = session.conn; // its conversation stays shown while it restarts, and if that fails
    before?.close();
    session.starting = true;
    session.error = null;
    const startup = { step: "sandbox", reattach: session.info.state === "running", since: Date.now() } as const;
    session.startup = startup;
    const conn = new AcpConnection();
    conn.onTurnEnded = () => this.turnEnded(session);
    try {
      await conn.connect(websocketTransport(session.info.acpUrl, token() ?? "")); // answered once the agent runs
      session.startup = { ...startup, step: "conversation" };
      session.info = await api.session(session.key);
      await conn.loadSession(session.info.acpSessionId ?? "", session.info.scope);
      session.conn = conn;
    } catch (e) {
      session.error = conn.closed?.reason || (e as Error).message;
      session.info = await api.session(session.key).catch(() => session.info); // failed, or stopped with why
      const shown = before?.session.entries.length && conn.closed?.code !== ATTACHED_ELSEWHERE;
      session.conn = shown ? before : conn;
      conn.close();
    } finally {
      session.starting = false;
      session.startup = null;
    }
  }

  async send(session: LiveSession, prompt: Prompt): Promise<void> {
    if (!session.conn) return;
    session.error = null;
    try {
      await session.conn.prompt(prompt.text, prompt.images); // how it ended: shown by the timeline
      this.turnEnded(session);
    } catch (e) {
      const back = session.conn.closed ? "It goes back in the input when the agent runs again" : "It is back in the input";
      session.error = `Your message failed (${(e as Error).message}). ${back}.`;
      session.draft = [prompt.text, session.draft].filter(Boolean).join("\n\n");
      session.draftImages = [...prompt.images, ...session.draftImages];
    }
  }

  /** A message for when the turn in progress ends; a second one is added to it. */
  queue(session: LiveSession, prompt: Prompt): void {
    const before = session.queued;
    session.queued = before
      ? { text: [before.text, prompt.text].filter(Boolean).join("\n\n"), images: [...before.images, ...prompt.images] }
      : prompt;
  }

  /** The queued message, now: the turn in progress is interrupted, and it is sent when it ends. */
  async sendNow(session: LiveSession): Promise<void> {
    if (!session.conn?.busy) return this.sendQueued(session);
    try {
      await session.conn.cancel();
    } catch (e) {
      session.error = (e as Error).message;
    }
  }

  private turnEnded(session: LiveSession): void {
    if (session.queued) return void this.sendQueued(session);
    if (this.viewing !== session.key || document.hidden) session.unread = true;
  }

  private async sendQueued(session: LiveSession): Promise<void> {
    const prompt = session.queued;
    if (!prompt || !session.live) return;
    session.queued = null;
    await this.send(session, prompt);
  }

  seen(session: LiveSession): void {
    session.unread = false;
  }

  /** Stop the agent and drop the session from the sidebar; it stays resumable (launcher). */
  async close(session: LiveSession): Promise<void> {
    this.closed.add(session.key);
    session.conn?.close();
    this.list = this.list.filter((s) => s !== session);
    this.save();
    this.stopping.add(session.key);
    try {
      await api.stopSession(session.key);
    } catch {
      /* already gone */
    } finally {
      this.stopping.delete(session.key);
    }
  }

  /** After a page load: the sessions of the sidebar, re-attached if their agent is running. */
  async restore(): Promise<void> {
    try {
      await this.load();
    } catch (e) {
      const notFound = e instanceof ApiError && e.status === 404;
      this.loadError = notFound
        ? "This daemon has no sessions API (/v1/sessions): restart handlerd to run the current version."
        : `Sessions could not be loaded: ${(e as Error).message}`;
    } finally {
      this.restored = true;
    }
    await this.discover();
    setInterval(() => void this.discover(), POLL_MS);
  }

  private async load(): Promise<void> {
    const open = new Set(this.saved());
    const [all, agents] = await Promise.all([api.sessions(), api.agents()]);
    const byId = new Map(agents.map((r) => [r.id, r]));
    for (const info of all.reverse()) {
      const agent = byId.get(info.agentId);
      if (!agent || !open.has(info.id) || this.get(info.id)) continue;
      const session = new LiveSession(info, agent);
      this.list.push(session);
      if (info.state === "running" || info.state === "starting") void this.connect(session);
    }
    this.save();
  }

  private saved(): string[] {
    try {
      return JSON.parse(localStorage.getItem(STORAGE) ?? "[]") as string[];
    } catch {
      return [];
    }
  }

  private save(): void {
    try {
      localStorage.setItem(STORAGE, JSON.stringify(this.list.filter((s) => !s.discovered).map((s) => s.key)));
    } catch {
      /* storage unavailable: only running sessions come back after a reload */
    }
  }
}

export const sessions = new SessionStore();
