// The remote client's state: this device (paired or not), the host's shared sessions, and the
// session on screen — an AcpConnection (the same as the handler web UI's) over the mailbox.
import type { AcpConnection } from "@handler/acp-view/lib/connection.svelte";
import { forgetPages, loadPage, queuedCalls, saveQueuedCalls, type AppPage, type QueuedCall } from "./apps";
import { answerOnCard, cardAnswers } from "./card";
import { unb64 } from "./crypto";
import { forgetLink, Mailbox, type Settled } from "./mailbox.svelte";
import { acp, prefetch } from "./lazy";
import { forgetSnapshot, loadSnapshot, saveSnapshot, type Home } from "./snapshot";
import { unsharedAfter, type Unshared } from "./home";
import { withSetting } from "./nudges";
import { deviceFrom, forgetDevice, loadDevice, readFragment, saveDevice, type Device, type PairingInfo } from "./pairing";
import type {
  StartFailed,
  AgentList,
  AskAnswer,
  ActionOption,
  AskOptions,
  RemoteTranscription,
  TranscribeParams,
  AskTurn,
  ActParams,
  NudgeFillParams,
  NudgeParams,
  NudgeSettingAnswer,
  NudgeSettingParams,
  RemoteActionRun,
  RemoteNudgeFill,
  AppList,
  InboxList,
  InboxMessage,
  InboxReadParams,
  PushKey,
  PushSubscribeParams,
  PushSubscription,
  PushTest,
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

/** Back on the page, the host is asked again only if what is shown is older than that. */
const STALE = 10_000;
const TAB_KEY = "handler-remote-tab";
const KINDS_KEY = "handler-push-kinds";
const READ_KEY = "handler-inbox-read";

/** The inbox messages read on this phone (their ids): a message is read once tapped here. */
function storedRead(): string[] {
  try {
    return JSON.parse(localStorage.getItem(READ_KEY) ?? "[]") as string[];
  } catch {
    return [];
  }
}

type PushKind = NonNullable<PushSubscribeParams["kinds"]>[number];

/** The bottom tabs: Ask (shown only when the host offers something to ask, D.24), Sessions (the
 *  owner's devices only), Apps, Inbox, Settings. */
export type Tab = "ask" | "sessions" | "apps" | "inbox" | "settings";
const TABS: Tab[] = ["ask", "sessions", "apps", "inbox", "settings"];

/** The tab kept from the last launch: Ask until one is chosen. */
function storedTab(): Tab {
  const kept = localStorage.getItem(TAB_KEY);
  return TABS.includes(kept as Tab) ? (kept as Tab) : "ask";
}

/** The kinds this phone turned on; both when it never said (as the host takes it). */
function storedKinds(): PushKind[] {
  const kept = localStorage.getItem(KINDS_KEY);
  return kept ? (JSON.parse(kept) as PushKind[]) : ["needs-you", "app-news"];
}

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
  unshared = $state<Unshared[]>([]); // shown here and no longer shared: this launch only
  listError = $state<string | null>(null);
  loading = $state(false);
  // when the host sent the Home shown (null: none yet, the neutral Starting screen shows); `fresh` once it was
  // asked again in this launch (until then it is the last launch's, said quietly)
  homeAt = $state<number | null>(null);
  fresh = $state(false);
  private refreshing: Promise<void> | null = null;

  /** The Home shown is the last launch's and nothing answers: the gateway is unreachable (the
   *  phone offline, or the gateway down) or the computer is not listening. Its rows are only
   *  shown, not answered, until the live Home replaces it. */
  get offline(): boolean {
    const m = this.mailbox;
    if (this.homeAt === null || this.fresh || !m) return false;
    return m.reachable === false || Boolean(m.reachable && !m.unauthorized && m.hostSeen !== null && !m.hostOnline);
  }

  // who this device is for, and the apps shared with that person
  person = $state("owner");
  scope = $state<"all" | "apps">("all");
  apps = $state<SharedApp[]>([]);
  currentApp = $state<SharedApp | null>(null);
  page = $state<AppPage | null>(null);
  appPath = $state("/"); // the page of the app to show (a nudge's), given to the app in its frame
  appError = $state<string | null>(null);
  appLoading = $state(false);

  // A5: calls left for when the computer is back, what apps told this person, push
  calls = $state<QueuedCall[]>(queuedCalls());
  inbox = $state<InboxMessage[]>([]);
  // read on tap, kept on this phone (not told to the host)
  readHere = $state<string[]>(storedRead());
  pushOn = $state(localStorage.getItem("handler-push") === "1"); // subscribed: some kind is on
  pushKinds = $state<PushKind[]>(storedKinds()); // what it is pushed for, each a switch (H.10)
  pushError = $state<string | null>(null);
  pushTest = $state<"sending" | "sent" | null>(null); // the last test push asked from Settings

  // the tab is the one last chosen (Ask until one is), never changed for the person once a screen
  // is shown; Settings (this device, notifications, forget) is a tab too, not kept for the next launch
  tab = $state<Tab>(storedTab());
  // Ask (D.24), the owner's devices: what can be asked now
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
  composeAgent = $state<string | null>(null); // chosen again: its start failed
  startError = $state<string | null>(null);
  private awaited: string | null = null; // started here: opened once the host shares it

  // the session on screen
  current = $state<SharedSession | null>(null);
  conn = $state<AcpConnection | null>(null);
  attaching = $state(false);
  error = $state<string | null>(null);
  // said on the session's screen when it opened instead of answering on its card
  notice = $state<string | null>(null);
  private opening: Promise<void> | null = null;

  // a card answering its session's ask (its id), and what went wrong on a card
  answering = $state<string | null>(null);
  cardError = $state<{ id: string; words: string } | null>(null);

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
    if (this.device && !this.offer) {
      const kept = await loadSnapshot(this.device.deviceId).catch(() => null);
      if (kept) this.show(kept.home, kept.at);
      this.connect();
    }
    this.ready = true;
  }

  /** Home as the host sent it at `at`, in one go: every list at once, and the tab the person
   *  sees never switched under them (Ask shows first only when nothing was shown yet). */
  private show(home: Home, at: number): void {
    const shown = this.homeAt !== null;
    const hadAsks = this.askOptions.length > 0;
    [this.person, this.scope, this.apps, this.inbox] = [home.person, home.scope, home.apps, home.inbox];
    this.setSessions(home.sessions);
    [this.agents, this.chats] = [home.agents, home.chats];
    [this.askOptions, this.voice] = [home.askOptions, home.voice];
    if (shown && !hadAsks && this.tab === "ask") this.tab = "sessions"; // the screen shown stays
    this.homeAt = at;
  }

  /** The shared sessions as the host lists them now; those gone leave their trace. */
  private setSessions(sessions: SharedSession[]): void {
    this.unshared = unsharedAfter(this.sessions, sessions, this.unshared);
    this.sessions = sessions;
  }

  /** What Home shows now, kept for the next launch (sealed, snapshot.ts). */
  private keep(): void {
    if (!this.device || this.homeAt === null) return;
    const home: Home = $state.snapshot({
      person: this.person,
      scope: this.scope,
      apps: this.apps,
      inbox: this.inbox,
      sessions: this.sessions,
      agents: this.agents,
      chats: this.chats,
      askOptions: this.askOptions,
      voice: this.voice,
    });
    void saveSnapshot(this.device.deviceId, home, this.homeAt).catch(() => undefined);
  }

  /** The tabs this device shows: Ask when there is something to ask, Sessions on the owner's. */
  get tabs(): Tab[] {
    return TABS.filter((t) => (t === "ask" ? this.askOptions.length > 0 : t === "sessions" ? this.scope === "all" : true));
  }

  /** The tab on screen: the one chosen, or where it would be shown without the tab it no longer
   *  has (Ask with nothing to ask, Sessions on a device of apps only). */
  get screen(): Tab {
    if (this.tabs.includes(this.tab)) return this.tab;
    return this.scope === "all" ? "sessions" : "apps";
  }

  /** The person chose a tab: the one shown first next time (Settings excepted). */
  chooseTab(tab: Tab): void {
    this.tab = tab;
    if (tab !== "settings") localStorage.setItem(TAB_KEY, tab);
  }

  /** What this device kept from its pairing (the last Home, its link's place), for a new one. */
  private async erase(): Promise<void> {
    if (this.device) forgetLink(this.device.deviceId);
    localStorage.removeItem(TAB_KEY);
    localStorage.removeItem(READ_KEY);
    this.readHere = [];
    await forgetSnapshot().catch(() => undefined);
    [this.homeAt, this.fresh, this.sessions, this.apps, this.inbox, this.askOptions] = [null, false, [], [], [], []];
    this.unshared = [];
    [this.agents, this.chats, this.tab] = [[], [], "ask"];
  }

  /** Accept the QR code's pairing (replacing a previous one). */
  async pair(): Promise<void> {
    if (!this.offer) return;
    try {
      if (!crypto.subtle) throw new Error("this page is not served over HTTPS: the browser gives it no cryptography");
      const device = await deviceFrom(this.offer);
      this.mailbox?.stop();
      this.mailbox = null;
      await this.erase(); // the previous pairing's
      await saveDevice(device);
      this.offer = null;
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
    await this.erase();
    await forgetDevice();
    forgetPages();
    forgetDrafts();
    this.device = null;
  }

  private connect(): void {
    if (!this.device || this.mailbox) return;
    const mailbox = new Mailbox(this.device);
    mailbox.onControl = (method, params) => {
      // the new list comes with it: with nothing shared, the host stops polling and could not answer
      if (method === "_handler/remote/sessions_changed") {
        this.setSessions((params as unknown as SessionList).sessions ?? []);
        this.openAwaited();
        this.keep();
      }
      if (method === "_handler/remote/start_failed") this.startFailed(params as unknown as StartFailed);
      if (method === "_handler/remote/apps_changed") {
        this.apps = (params as unknown as SharedApps).apps ?? [];
        this.keep();
      }
    };
    mailbox.onHostBack = () => void this.refresh();
    mailbox.onQueuedAnswer = (id, m) => {
      const status = (m.result as { status?: number } | undefined)?.status;
      this.calls = this.calls.map((c) => (c.id === id ? { ...c, done: true, status } : c));
      saveQueuedCalls(this.calls);
    };
    mailbox.start();
    this.mailbox = mailbox;
    void this.refresh();
    if (this.pushOn) void this.resendSubscription(mailbox);
  }

  /** Home from the host: its five lists asked in one envelope (one trip), shown in one go. One
   *  at a time: asked again meanwhile, the one under way is awaited. */
  refresh(): Promise<void> {
    this.refreshing ??= this.fetchHome().finally(() => (this.refreshing = null));
    return this.refreshing;
  }

  /** Back on the page (the phone slept, another app was in front): asked again if not fresh. */
  refreshIfStale(): void {
    if (!this.fresh || this.homeAt === null || Date.now() - this.homeAt > STALE) void this.refresh();
  }

  private async fetchHome(): Promise<void> {
    const mailbox = this.mailbox;
    if (!mailbox) return;
    this.loading = true;
    try {
      // a device for apps only is told "none" (sessions, agents) or refused (Ask) by the host
      const [apps, inbox, sessions, agents, options] = await mailbox.requestAll([
        { method: "_handler/remote/list_apps" },
        { method: "_handler/remote/inbox" },
        { method: "_handler/remote/list_sessions" },
        { method: "_handler/remote/list_agents" },
        { method: "_handler/remote/ask_options" },
      ]);
      const listed = must<AppList>(apps!);
      const all = listed.scope === "all";
      const startable = all ? must<AgentList>(agents!) : { projects: [], chats: [] };
      const asks = all && options!.ok ? (options!.result as AskOptions) : null;
      const home: Home = {
        person: listed.person,
        scope: listed.scope,
        apps: listed.apps,
        inbox: must<InboxList>(inbox!).messages,
        sessions: all ? must<SessionList>(sessions!).sessions : [],
        agents: startable.projects,
        chats: startable.chats ?? [],
        askOptions: asks?.actions ?? [],
        voice: {
          listens: asks?.listens ?? false,
          readAloudSpoken: asks?.readAloudSpoken ?? true,
          readAloudTyped: asks?.readAloudTyped ?? false,
        },
      };
      this.show(home, Date.now());
      this.fresh = true;
      void this.tellRead(this.readHere).catch(() => undefined); // read here while it was away
      this.listError = null;
      this.keep();
      this.openAwaited();
      if (this.current) this.current = home.sessions.find((s) => s.id === this.current?.id) ?? this.current;
    } catch (e) {
      this.listError = mailbox.hostOnline
        ? (e as Error).message
        : "Your computer is not listening: Handler there reaches this phone only while a session or an app is shared (or the computer is off).";
    } finally {
      this.loading = false;
      prefetch(); // the session and app screens, once Home is answered and the browser idle
    }
  }

  /** Ask (D.24): the exchange so far, the person's words last; answered once an app did it. */
  async ask(turns: AskTurn[], spoken: boolean): Promise<AskAnswer> {
    if (!this.mailbox) throw new Error("not paired");
    const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    return await this.mailbox.request<AskAnswer>("_handler/remote/ask", { turns, timezone, spoken }, 120_000);
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

  /** One of an app's actions, its form filled, from the owner's device; from a nudge (H.17),
   *  which it makes done once it succeeds. An agent's comes back running: read it again. */
  async act(params: ActParams): Promise<RemoteActionRun> {
    if (!this.mailbox) throw new Error("not paired");
    return await this.mailbox.request<RemoteActionRun>("_handler/remote/act", params, 120_000);
  }

  /** What the owner said about an open nudge, as its form filled (never sent, H.17). */
  async nudgeFill(id: string, said: string): Promise<RemoteNudgeFill> {
    if (!this.mailbox) throw new Error("not paired");
    const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    const params: NudgeFillParams = { id, said, timezone };
    return await this.mailbox.request<RemoteNudgeFill>("_handler/remote/nudge_fill", params, 120_000);
  }

  /** A nudge of this device's person dismissed: it ends, in the inbox as it is now. */
  async nudgeDismiss(id: string): Promise<void> {
    if (!this.mailbox) throw new Error("not paired");
    const params: NudgeParams = { id };
    const ended = await this.mailbox.request<InboxMessage>("_handler/remote/nudge_dismiss", params);
    this.inbox = this.inbox.map((m) => (m.id === id ? ended : m));
  }

  /** How often an app's nudge alerts the owner again, for its open ones and its next ones. */
  async nudgeSetting(params: NudgeSettingParams): Promise<void> {
    if (!this.mailbox) throw new Error("not paired");
    const { setting } = await this.mailbox.request<NudgeSettingAnswer>("_handler/remote/nudge_setting", params);
    this.inbox = withSetting(this.inbox, params.app, params.nudge, setting);
  }

  /** The inbox again (a nudge's action ran: it may be done). */
  async refreshInbox(): Promise<void> {
    if (!this.mailbox) return;
    this.inbox = (await this.mailbox.request<InboxList>("_handler/remote/inbox")).messages;
  }

  /** The New session screen: on a project's agents, or on Chat with `say` typed. */
  compose(chat = false, say = ""): void {
    [this.composeChat, this.composeSay, this.startError, this.composing] = [chat, say, null, true];
    this.composeAgent = null;
  }

  /** A new session of an allowed agent, `prompt` sent first, or `fields` for an agent with a
   *  form (D.18); opened once the host shares it. */
  async start(agentId: string, prompt: string, fields: Record<string, unknown> | null = null): Promise<void> {
    if (!this.mailbox) return;
    this.startError = null;
    try {
      const params: StartSessionParams = fields ? { agentId, fields } : { agentId, prompt: prompt.trim() || null };
      const { session } = await this.mailbox.request<StartedSession>("_handler/remote/start_session", params);
      this.awaited = session;
      [this.composeSay, this.composeAgent] = [prompt, agentId]; // again if it does not start
      this.composing = false;
      setTimeout(() => void this.refresh(), 3000); // in case the notice was missed
    } catch (e) {
      this.startError = (e as Error).message;
    }
  }

  /** The session started here did not start: New session again, saying why. */
  private startFailed(failed: StartFailed): void {
    if (failed.session !== this.awaited) return;
    this.awaited = null;
    this.startError = failed.missingImage
      ? "It did not start: its program is not prepared yet. Prepare it in Handler on your computer, then start it again."
      : `It did not start: ${failed.error}`;
    this.composing = true;
  }

  private openAwaited(): void {
    const found = this.awaited ? this.sessions.find((s) => s.id === this.awaited) : undefined;
    if (!found) return;
    this.awaited = null;
    void this.open(found);
  }

  /** A card's Reject or Allow (rule phone.a-card-answers-only-the-ask-it-shows, card.ts): only a
   *  safe ask, alone, answered once, and only the very ask the card shows. Any other case, or that
   *  ask gone meanwhile, opens the session instead, saying so when the ask changed. */
  async answerCard(s: SharedSession, answer: "allow" | "reject"): Promise<void> {
    if (!this.mailbox || this.offline || this.answering) return;
    if (!cardAnswers(s)) {
      await this.open(s);
      return;
    }
    [this.answering, this.cardError] = [s.id, null];
    try {
      const answered = await answerOnCard(this.mailbox.transport(s.id), s, answer);
      if (!answered) {
        await this.open(s);
        this.notice = `Nothing was ${answer === "allow" ? "allowed" : "rejected"}: what it asks changed. Here it is.`;
      }
    } catch (e) {
      this.cardError = { id: s.id, words: `Not answered: ${(e as Error).message}` };
    } finally {
      this.answering = null;
    }
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
    this.notice = null;
    if (this.offline) {
      this.error = "Offline: this session can be answered from here once the phone reaches your computer again.";
      return;
    }
    this.error = null;
    this.attaching = true;
    const conn = new (await acp()).AcpConnection(); // its own chunk: the ACP SDK and its schemas
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
    this.notice = null;
    if (unshared) this.setSessions(this.sessions.filter((s) => s.id !== id));
    else if (this.mailbox?.hostOnline) void this.refresh();
  }

  /** Show an app: its page from handler, or this phone's copy when the host does not answer;
   *  `path` (a nudge's page, `/log?day=…&nudge=…`) is given to the app in its frame. */
  async openApp(shared: SharedApp, path = "/"): Promise<void> {
    if (!this.mailbox) return;
    this.currentApp = shared;
    this.appPath = path;
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

  /** The kinds of notification this device offers a switch for: a session needing you only on
   *  a device that sees sessions. */
  get pushChoices(): PushKind[] {
    return this.scope === "all" ? ["needs-you", "app-news"] : ["app-news"];
  }

  pushWants(kind: PushKind): boolean {
    return this.pushOn && this.pushKinds.includes(kind);
  }

  /** One switch of Notifications: the first one on subscribes this browser, the last one off
   *  unsubscribes it; in between, the host is told the kinds. */
  async togglePush(kind: PushKind): Promise<void> {
    if (!this.pushOn) {
      this.setKinds([kind]);
      await this.enablePush();
      return;
    }
    const on = this.pushWants(kind)
      ? this.pushKinds.filter((k) => k !== kind)
      : [...this.pushKinds, kind];
    if (!on.some((k) => this.pushChoices.includes(k))) {
      await this.disablePush();
      return;
    }
    this.pushError = null;
    this.setKinds(on);
    try {
      if (!this.mailbox) throw new Error("not connected");
      await this.resendSubscription(this.mailbox);
    } catch (e) {
      this.pushError = (e as Error).message;
    }
  }

  private setKinds(kinds: PushKind[]): void {
    this.pushKinds = kinds;
    localStorage.setItem(KINDS_KEY, JSON.stringify(kinds));
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
      await this.sendSubscription(this.mailbox, subscription);
      this.pushOn = true;
      localStorage.setItem("handler-push", "1");
    } catch (e) {
      this.pushError = (e as Error).message;
    }
  }

  /** On each open while notifications are on: the host gets this browser's subscription again
   *  (the browser may have changed it, and a host updated from a Handler that kept no keys has
   *  none). */
  private async resendSubscription(mailbox: Mailbox): Promise<void> {
    try {
      const registration = await navigator.serviceWorker?.getRegistration();
      const subscription = await registration?.pushManager.getSubscription();
      if (subscription) await this.sendSubscription(mailbox, subscription);
      else await this.enablePush();
    } catch (e) {
      this.pushError = (e as Error).message;
    }
  }

  /** Where the host posts, the keys it encrypts the push (its kind alone) to: Firefox for
   *  Android drops a push with no body; and the kinds this device is pushed for. */
  private async sendSubscription(mailbox: Mailbox, subscription: globalThis.PushSubscription): Promise<void> {
    const { p256dh, auth } = subscription.toJSON().keys ?? {};
    if (!p256dh || !auth) throw new Error("this browser gave no keys for its notifications");
    const on: PushSubscribeParams = {
      subscription: { endpoint: subscription.endpoint, keys: { p256dh, auth } },
      kinds: this.pushKinds,
    };
    await mailbox.request<PushSubscription>("_handler/remote/push_subscribe", on);
  }

  /** Two notifications: one this phone shows itself (no push), then a real push from the host,
   *  as a message would send. Which ones appear tells the phone's settings from the delivery. */
  async testPush(): Promise<void> {
    this.pushError = null;
    this.pushTest = "sending";
    try {
      if (!this.mailbox) throw new Error("not connected");
      if (Notification.permission !== "granted") {
        throw new Error(`this page may not show notifications (its permission: ${Notification.permission})`);
      }
      const registration = await navigator.serviceWorker.getRegistration();
      if (!registration) throw new Error("no service worker on this page: turn notifications off and on");
      await registration.showNotification("Handler", { body: "Test 1 of 2: shown by this phone.", tag: "handler-test" });
      await new Promise((resolve) => setTimeout(resolve, 3_000));
      const answer = await this.mailbox.request<PushTest>("_handler/remote/push_test");
      if (!answer.sent) throw new Error(answer.problem ?? "not sent");
      this.pushTest = "sent";
    } catch (e) {
      this.pushTest = null;
      this.pushError = (e as Error).message;
    }
  }

  async disablePush(): Promise<void> {
    this.pushError = null;
    this.pushTest = null;
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
    localStorage.removeItem(KINDS_KEY);
    this.pushKinds = storedKinds();
  }

  /** Read: the host says so, or the person tapped it on this phone. */
  isRead(m: InboxMessage): boolean {
    return Boolean(m.read) || this.readHere.includes(m.id);
  }

  /** The person tapped a message: read on this phone at once (kept here: also while the computer
   *  is away), and on the computer (`inbox_read`); the ones read here and not on the computer are
   *  told again when it is back (`tellRead`). */
  markRead(id: string): void {
    if (!this.readHere.includes(id)) {
      const ids = new Set(this.inbox.map((m) => m.id));
      this.readHere = [...this.readHere.filter((r) => ids.has(r)), id];
      localStorage.setItem(READ_KEY, JSON.stringify(this.readHere));
    }
    void this.tellRead([id]).catch(() => undefined);
  }

  /** The computer told which messages were read here (those it does not say read yet); a failure
   *  loses nothing but the computer's dot until the next try. */
  private async tellRead(ids: string[]): Promise<void> {
    const mailbox = this.mailbox;
    const unread = ids.filter((id) => this.inbox.some((m) => m.id === id && !m.read));
    if (!mailbox || this.offline || !unread.length) return;
    const told = await mailbox.requestAll(unread.map((id) => ({ method: "_handler/remote/inbox_read", params: { id } satisfies InboxReadParams })));
    const read = new Map(told.flatMap((t) => (t.ok ? [[(t.result as InboxMessage).id, t.result as InboxMessage] as const] : [])));
    if (read.size) this.inbox = this.inbox.map((m) => read.get(m.id) ?? m);
  }

  forgetDoneCalls(): void {
    this.calls = this.calls.filter((c) => !c.done);
    saveQueuedCalls(this.calls);
  }

  closeApp(): void {
    this.currentApp = null;
    this.page = null;
    this.appError = null;
    this.appPath = "/";
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

/** A request's answer, or its error thrown. */
function must<T>(settled: Settled): T {
  if (!settled.ok) throw settled.error;
  return settled.result as T;
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
