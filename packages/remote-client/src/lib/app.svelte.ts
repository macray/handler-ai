// The remote client's state: this device (paired or not), the host's shared sessions, and the
// session on screen — an AcpConnection (the same as the handler web UI's) over the mailbox.
import { AcpConnection } from "@handler/acp-view/lib/connection.svelte";
import { forgetPages, loadPage, queuedCalls, saveQueuedCalls, type AppPage, type QueuedCall } from "./apps";
import { unb64 } from "./crypto";
import { Mailbox } from "./mailbox.svelte";
import { deviceFrom, forgetDevice, loadDevice, readFragment, saveDevice, type Device, type PairingInfo } from "./pairing";
import type {
  AgentList,
  AskAnswer,
  ActionOption,
  AskOptions,
  RemoteTranscription,
  TranscribeParams,
  AskTurn,
  RemoteActionRun,
  AppList,
  InboxList,
  InboxMessage,
  PushKey,
  PushSubscribeParams,
  PushSubscription,
  RemoteAgent,
  RemoteProject,
  SessionList,
  SharedApp,
  SharedApps,
  SharedSession,
  StartedSession,
  StartSessionParams,
} from "./remote.gen";

/** The host refused a frame of an attachment it no longer holds (it detached the sleeping phone). */
const NOT_ATTACHED = -32021;

/** Close codes after which re-attaching is pointless: the session is not shared or not running. */
const FINAL = new Map([
  [4002, "The agent stopped."],
  [4004, "The session is no longer shared."],
]);

class RemoteApp {
  ready = $state(false);
  device = $state<Device | null>(null);
  offer = $state<(PairingInfo & { key: Uint8Array<ArrayBuffer> }) | null>(null); // from a QR code
  pairError = $state<string | null>(null);
  mailbox = $state<Mailbox | null>(null);
  sessions = $state<SharedSession[]>([]);
  listError = $state<string | null>(null);
  loading = $state(false);

  // who this device is for, and the apps shared with that person
  person = $state("owner");
  scope = $state<"all" | "apps">("all");
  apps = $state<SharedApp[]>([]);
  currentApp = $state<SharedApp | null>(null);
  page = $state<AppPage | null>(null);
  appError = $state<string | null>(null);
  appLoading = $state(false);

  // A5: calls left for when the computer is back, what apps told this person, push
  calls = $state<QueuedCall[]>(queuedCalls());
  inbox = $state<InboxMessage[]>([]);
  pushOn = $state(localStorage.getItem("handler-push") === "1");
  pushError = $state<string | null>(null);

  settings = $state(false); // the Settings screen: this device, notifications, forget

  // Ask (D.24), the owner's devices: what can be asked now; the tab shown first when there is
  tab = $state<"ask" | "home">("home");
  askOptions = $state<ActionOption[]>([]);
  // speaking (D.25): a speech model chosen on the host; answers read aloud when you spoke / typed
  voice = $state({ listens: false, readAloudSpoken: true, readAloudTyped: false });

  // starting a session from here: the agents allowed (a project's, or who you talk to in Chat),
  // the screen (opened on Chat with words typed: Ask's "Start a chat about it"), the session
  // being started
  agents = $state<RemoteProject[]>([]);
  chats = $state<RemoteAgent[]>([]);
  composing = $state(false);
  composeChat = $state(false);
  composeSay = $state("");
  startError = $state<string | null>(null);
  private awaited: string | null = null; // started here: opened once the host shares it

  // the session on screen
  current = $state<SharedSession | null>(null);
  conn = $state<AcpConnection | null>(null);
  attaching = $state(false);
  error = $state<string | null>(null);
  ended = $state<string | null>(null); // why the session view cannot continue
  private opening: Promise<void> | null = null;

  async init(): Promise<void> {
    try {
      this.offer = readFragment(location.hash);
    } catch (e) {
      this.pairError = (e as Error).message;
    }
    if (this.offer || this.pairError) history.replaceState(null, "", location.pathname); // the key leaves the address bar
    try {
      this.device = await loadDevice();
    } catch (e) {
      this.pairError = `This browser cannot store keys: ${(e as Error).message}`;
    }
    if (this.device && !this.offer) this.connect();
    this.ready = true;
  }

  /** Accept the QR code's pairing (replacing a previous one). */
  async pair(): Promise<void> {
    if (!this.offer) return;
    try {
      if (!crypto.subtle) throw new Error("this page is not served over HTTPS: the browser gives it no cryptography");
      const device = await deviceFrom(this.offer);
      await saveDevice(device);
      this.offer = null;
      this.mailbox?.stop();
      this.device = device;
      this.connect();
    } catch (e) {
      this.pairError = (e as Error).message;
    }
  }

  decline(): void {
    this.offer?.key.fill(0);
    this.offer = null;
    if (this.device) this.connect();
  }

  async forget(): Promise<void> {
    this.close();
    this.mailbox?.stop();
    this.mailbox = null;
    await forgetDevice();
    forgetPages();
    forgetDrafts();
    this.settings = false;
    this.device = null;
    this.sessions = [];
    this.apps = [];
  }

  private connect(): void {
    if (!this.device || this.mailbox) return;
    const mailbox = new Mailbox(this.device);
    mailbox.onControl = (method, params) => {
      // the new list comes with it: with nothing shared, the host stops polling and could not answer
      if (method === "_handler/remote/sessions_changed") {
        this.sessions = (params as unknown as SessionList).sessions ?? [];
        this.openAwaited();
      }
      if (method === "_handler/remote/apps_changed") this.apps = (params as unknown as SharedApps).apps ?? [];
    };
    mailbox.onQueuedAnswer = (id, m) => {
      const status = (m.result as { status?: number } | undefined)?.status;
      this.calls = this.calls.map((c) => (c.id === id ? { ...c, done: true, status } : c));
      saveQueuedCalls(this.calls);
    };
    mailbox.start();
    this.mailbox = mailbox;
    void this.refresh();
  }

  async refresh(): Promise<void> {
    if (!this.mailbox) return;
    this.loading = true;
    try {
      const listed = await this.mailbox.request<AppList>("_handler/remote/list_apps");
      [this.person, this.scope, this.apps] = [listed.person, listed.scope, listed.apps];
      const { messages } = await this.mailbox.request<InboxList>("_handler/remote/inbox");
      this.inbox = messages;
      const { sessions } =
        this.scope === "all"
          ? await this.mailbox.request<SessionList>("_handler/remote/list_sessions")
          : { sessions: [] };
      this.sessions = sessions;
      const startable: AgentList =
        this.scope === "all" ? await this.mailbox.request<AgentList>("_handler/remote/list_agents") : { projects: [] };
      [this.agents, this.chats] = [startable.projects, startable.chats ?? []];
      const hadAsks = this.askOptions.length > 0;
      const options = this.scope === "all" ? await this.mailbox.request<AskOptions>("_handler/remote/ask_options").catch(() => null) : null;
      this.askOptions = options?.actions ?? [];
      this.voice = {
        listens: options?.listens ?? false,
        readAloudSpoken: options?.readAloudSpoken ?? true,
        readAloudTyped: options?.readAloudTyped ?? false,
      };
      if (!hadAsks && this.askOptions.length) this.tab = "ask"; // first shown, once there is something to ask
      this.listError = null;
      this.openAwaited();
      if (this.current) this.current = sessions.find((s) => s.id === this.current?.id) ?? this.current;
    } catch (e) {
      this.listError = this.mailbox.hostOnline
        ? (e as Error).message
        : "The host is not listening: it polls the gateway only while a session or an app is shared (or it is offline).";
    } finally {
      this.loading = false;
    }
  }

  /** Ask (D.24): the exchange so far, the person's words last; answered once an app did it. */
  async ask(turns: AskTurn[]): Promise<AskAnswer> {
    if (!this.mailbox) throw new Error("not paired");
    const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    return await this.mailbox.request<AskAnswer>("_handler/remote/ask", { turns, timezone }, 120_000);
  }

  /** A recording written down on the host with its speech model (D.25), never kept. */
  async transcribe(speech: TranscribeParams): Promise<string> {
    if (!this.mailbox) throw new Error("not paired");
    return (await this.mailbox.request<RemoteTranscription>("_handler/remote/transcribe", speech, 90_000)).text;
  }

  /** An agent's action, read again until it ends (H.12). */
  async actionRun(app: string, action: string, runId: string): Promise<RemoteActionRun> {
    if (!this.mailbox) throw new Error("not paired");
    return await this.mailbox.request<RemoteActionRun>("_handler/remote/action_run", { app, action, runId });
  }

  /** The New session screen: on a project's agents, or on Chat with `say` typed. */
  compose(chat = false, say = ""): void {
    [this.composeChat, this.composeSay, this.startError, this.composing] = [chat, say, null, true];
  }

  /** A new session of an allowed agent, `prompt` sent first; opened once the host shares it. */
  async start(agentId: string, prompt: string): Promise<void> {
    if (!this.mailbox) return;
    this.startError = null;
    try {
      const params: StartSessionParams = { agentId, prompt: prompt.trim() || null };
      const { session } = await this.mailbox.request<StartedSession>("_handler/remote/start_session", params);
      this.awaited = session;
      this.composing = false;
      setTimeout(() => void this.refresh(), 3000); // in case the notice was missed
    } catch (e) {
      this.startError = (e as Error).message;
    }
  }

  private openAwaited(): void {
    const found = this.awaited ? this.sessions.find((s) => s.id === this.awaited) : undefined;
    if (!found) return;
    this.awaited = null;
    void this.open(found);
  }

  /** Attach to a shared session: the host replays the conversation, then it goes on live. One
   *  attaching at a time: asked again meanwhile, the one under way is awaited. */
  open(session: SharedSession): Promise<void> {
    this.opening ??= this.attach(session).finally(() => (this.opening = null));
    return this.opening;
  }

  private async attach(session: SharedSession): Promise<void> {
    if (!this.mailbox) return;
    this.conn?.close();
    this.current = session;
    this.error = null;
    this.ended = null;
    this.attaching = true;
    const conn = new AcpConnection();
    try {
      if (!session.acpSessionId) throw new Error("The session is still starting: open it again in a moment.");
      await conn.connect(this.mailbox.transport(session.id));
      await conn.loadSession(session.acpSessionId, session.scope);
      this.conn = conn;
    } catch (e) {
      this.error = conn.closed?.reason || (e as Error).message;
      conn.close();
    } finally {
      this.attaching = false;
    }
  }

  /** The attachment was closed by the host: say why, or re-attach (e.g. after the phone slept). */
  whyClosed(): string | null {
    const closed = this.conn?.closed;
    if (!closed) return null;
    return FINAL.get(closed.code) ?? null;
  }

  async reattach(): Promise<void> {
    if (this.current) await this.open(this.current);
  }

  close(): void {
    const unshared = this.whyClosed() !== null;
    const id = this.current?.id;
    this.conn?.close();
    this.conn = null;
    this.current = null;
    if (unshared) this.sessions = this.sessions.filter((s) => s.id !== id);
    else if (this.mailbox?.hostOnline) void this.refresh();
  }

  /** Show an app: its page from handler, or this phone's copy when the host does not answer. */
  async openApp(shared: SharedApp): Promise<void> {
    if (!this.mailbox) return;
    this.currentApp = shared;
    this.page = null;
    this.appError = null;
    this.appLoading = true;
    try {
      this.page = await loadPage(this.mailbox, shared.name);
    } catch (e) {
      this.appError = (e as Error).message;
    } finally {
      this.appLoading = false;
    }
  }

  /** Receive content-free pushes (on iPhone: only once handler is added to the home screen). */
  async enablePush(): Promise<void> {
    this.pushError = null;
    try {
      if (!this.mailbox) throw new Error("not connected");
      if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
        throw new Error("this browser cannot receive notifications (on iPhone: Share → Add to Home Screen, then open it from there)");
      }
      if ((await Notification.requestPermission()) !== "granted") throw new Error("notifications are not allowed for this page");
      const registration = await navigator.serviceWorker.register("/sw.js");
      await navigator.serviceWorker.ready;
      const { publicKey } = await this.mailbox.request<PushKey>("_handler/remote/push_key");
      const subscription = await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: unb64(publicKey) });
      const on: PushSubscribeParams = { endpoint: subscription.endpoint };
      await this.mailbox.request<PushSubscription>("_handler/remote/push_subscribe", on);
      this.pushOn = true;
      localStorage.setItem("handler-push", "1");
    } catch (e) {
      this.pushError = (e as Error).message;
    }
  }

  async disablePush(): Promise<void> {
    this.pushError = null;
    try {
      const registration = await navigator.serviceWorker?.getRegistration();
      await (await registration?.pushManager.getSubscription())?.unsubscribe();
      const off: PushSubscribeParams = {};
      await this.mailbox?.request<PushSubscription>("_handler/remote/push_subscribe", off);
    } catch (e) {
      this.pushError = (e as Error).message;
    }
    this.pushOn = false;
    localStorage.removeItem("handler-push");
  }

  forgetDoneCalls(): void {
    this.calls = this.calls.filter((c) => !c.done);
    saveQueuedCalls(this.calls);
  }

  closeApp(): void {
    this.currentApp = null;
    this.page = null;
    this.appError = null;
  }

  /** A prompt. Never lost: the phone re-attaches first when the host may have detached it
   *  while it slept, and resends it when the host says it was detached (the agent never got it).
   *  `false` when it failed: the caller gives the text back to the input. */
  async send(text: string): Promise<boolean> {
    if (!this.conn) return false;
    this.error = null;
    try {
      if (this.mailbox?.mayBeDetached) await this.reattach();
      try {
        await this.required().prompt(text); // how it ended: shown by the timeline
      } catch (e) {
        if ((e as { code?: number }).code !== NOT_ATTACHED) throw e;
        await this.reattach();
        await this.required().prompt(text);
      }
      return true;
    } catch (e) {
      const why = (e as Error).message;
      await this.reattach(); // a sound attachment for the next try, and the conversation as it is
      this.error = `Your message failed (${why}). It is back in the input.`;
      return false;
    }
  }

  private required(): AcpConnection {
    if (!this.conn || this.conn.closed) throw new Error(this.error ?? "the session could not be reattached");
    return this.conn;
  }
}

export const app = new RemoteApp();

const DRAFT = "handler-draft:";

/** What was typed for a session and not sent yet: kept on this phone, also across a reload. */
export function loadDraft(session: string): string {
  return localStorage.getItem(DRAFT + session) ?? "";
}

export function saveDraft(session: string, text: string): void {
  if (text) localStorage.setItem(DRAFT + session, text);
  else localStorage.removeItem(DRAFT + session);
}

function forgetDrafts(): void {
  for (const key of Object.keys(localStorage)) if (key.startsWith(DRAFT)) localStorage.removeItem(key);
}
