// The device's link to its host, through the gateway (remote design §4–5): sealed
// envelopes posted to /v1/device/down, and a long poll of /v1/device/poll for what the host sends
// back.
//
// Frames are multiplexed by session: `s: <session id>` is the ACP traffic of this device's
// attachment to that session — exposed as an ACP transport (`transport(s)`), so the session view
// is the same AcpConnection as the handler web UI's — `s: null` is the control channel
// (list sessions and apps, ping, detach; `_handler/remote/closed`, `sessions_changed`, `apps_changed`
// from the host), and `s: "app:<name>"` an app's requests (its UI, its backend calls).
//
// The client is served by the gateway: requests go to this page's own origin.
import type { AnyMessage } from "@agentclientprotocol/sdk";
import type { Closed, OpenTransport } from "@handler/acp-view/lib/connection.svelte";
import { open, seal, type Envelope } from "./crypto";
import type { Device } from "./pairing";
import type { ClosedNotice, DetachParams } from "./remote.gen";

type Message = Record<string, unknown>;
export interface Frame {
  s: string | null;
  m: Message;
}

/** Where a command is: posted → the gateway saw the host fetch it → the host acknowledged it
 *  (sealed: the only proof). `expired`: the host refused it as too old. */
export type SendState = "sending" | "sent" | "fetched" | "delivered" | "expired" | "failed";

const POLL_WAIT = 25;
const PING_EVERY = 30_000;
const HOST_ONLINE = 35_000; // a polling host is "seen now"; it stops polling when nothing is shared
const LEASE = 90_000; // the host detaches a device that sent nothing for that long (remote.py)
// Until when the host may take an envelope (`expires`): a command now or never, a queued call
// whenever the host is back within 7 days. The host takes each one once, before it expires.
const LIVE = 5 * 60_000;
const QUEUED = 7 * 24 * 3600_000;
const SEEN_KEY = "handler-remote-seen:";
const CURSOR_KEY = "handler-remote-cursor:";

/** One request of a batch (`requestAll`), and how it ended. */
export interface Call {
  method: string;
  params?: object;
}
export type Settled<T = unknown> = { ok: true; result: T } | { ok: false; error: Error };

function readIds(key: string): Record<string, number> {
  try {
    const ids = JSON.parse(localStorage.getItem(key) ?? "{}") as Record<string, number>;
    const now = Date.now();
    return Object.fromEntries(Object.entries(ids).filter(([, until]) => until > now));
  } catch {
    return {};
  }
}

/** Ids of the host's envelopes this device opened, each until it expires (then the host's own
 *  `expires` refuses it): a gateway replaying one gets nothing, after a reload or a new launch
 *  too. Kept in localStorage, per device: a page starts from the ids opened before it (by an
 *  earlier launch, or another tab), then adds its own; it never takes in another open tab's
 *  later ids, which that tab may still be waiting to open itself. */
class Seen {
  private ids: Record<string, number>;
  private readonly key: string;

  constructor(deviceId: string) {
    this.key = SEEN_KEY + deviceId;
    this.ids = readIds(this.key);
  }

  has(id: string): boolean {
    return id in this.ids;
  }

  add(id: string, expires: number): void {
    this.ids[id] = expires;
    const kept = readIds(this.key); // what other pages of this device opened meanwhile
    kept[id] = expires;
    try {
      localStorage.setItem(this.key, JSON.stringify(kept));
    } catch {
      /* storage full: kept in memory for this page */
    }
  }
}

/** What a device keeps of its link (the ids it opened, where its poll is): erased with it. */
export function forgetLink(deviceId: string): void {
  localStorage.removeItem(SEEN_KEY + deviceId);
  localStorage.removeItem(CURSOR_KEY + deviceId);
}

export class Mailbox {
  reachable = $state<boolean | null>(null); // the gateway answered the last poll
  unauthorized = $state(false); // the gateway does not know this device (revoked?)
  error = $state<string | null>(null);
  hostSeen = $state<number | null>(null);
  now = $state(Date.now());
  lastSend = $state<{ id: string; state: SendState } | null>(null);

  /** Host notifications of the control channel (`_handler/remote/sessions_changed`). */
  onControl: ((method: string, params: Message) => void) | null = null;
  /** The answer to a call queued while the host was off (its id is "q-…"), arriving later. */
  onQueuedAnswer: ((id: string, m: Message) => void) | null = null;
  /** The host polls the gateway again (it was not, or this device could not tell). */
  onHostBack: (() => void) | null = null;

  // where this device's poll is, kept across launches: a new launch takes only what is new (the
  // gateway starts a cursor of another of its runs over)
  private cursor: string;
  private channels = new Map<string, (m: AnyMessage) => void>();
  private closers = new Map<string, (closed: Closed) => void>();
  // requests waiting for their answer: random ids, so an old answer (replayed) never matches one,
  // and on the channel they were asked on
  private replies = new Map<string, { s: string | null; resolve: (m: Message) => void }>();
  private seen: Seen;
  private states = new Map<string, SendState>();
  private stopped = false;
  private lastDown = Date.now(); // the last envelope the gateway took from this device
  private timers: ReturnType<typeof setInterval>[] = [];
  private listening = false; // the host polled at the last poll

  constructor(readonly device: Device) {
    this.seen = new Seen(device.deviceId);
    this.cursor = localStorage.getItem(CURSOR_KEY + device.deviceId) ?? "";
  }

  /** Sent nothing for nearly the lease (the phone slept): the host may have detached it. */
  get mayBeDetached(): boolean {
    return Date.now() - this.lastDown > LEASE - 15_000;
  }

  get hostOnline(): boolean {
    return this.hostSeen !== null && this.now - this.hostSeen < HOST_ONLINE;
  }

  private headers(): HeadersInit {
    return { Authorization: `Bearer ${this.device.deviceId}.${this.device.token}`, "Content-Type": "application/json" };
  }

  start(): void {
    void this.loop();
    this.timers.push(
      setInterval(() => {
        // keeps this device "around" for the host: it gets the shared list when it changes
        if (document.visibilityState === "visible") void this.notify("_handler/remote/ping").catch(() => undefined);
      }, PING_EVERY),
      setInterval(() => (this.now = Date.now()), 5_000),
    );
  }

  stop(): void {
    this.stopped = true;
    for (const t of this.timers) clearInterval(t);
  }

  // ── sending ─────────────────────────────────────────────────────────

  private track(id: string, state: SendState): void {
    const order: SendState[] = ["sending", "sent", "fetched", "delivered"];
    const previous = this.states.get(id);
    if (!previous || (order.includes(state) && order.indexOf(state) <= order.indexOf(previous))) return;
    this.states.set(id, state);
    if (this.lastSend?.id === id) this.lastSend = { id, state };
  }

  /** `shown`: session traffic (a prompt, an answer), whose progress the composer shows. */
  async send(frames: Frame[], shown = false): Promise<void> {
    const envelope = await seal(this.device.seal, this.device, "down", { expires: Date.now() + LIVE, frames });
    if (shown) {
      this.states.set(envelope.id, "sending");
      this.lastSend = { id: envelope.id, state: "sending" };
      if (this.states.size > 200) this.states.delete(this.states.keys().next().value as string);
    }
    try {
      const r = await fetch("/v1/device/down", { method: "POST", headers: this.headers(), body: JSON.stringify(envelope) });
      this.track(envelope.id, r.ok ? "sent" : "failed");
      if (r.ok) this.lastDown = Date.now();
      if (r.status === 401) this.unauthorized = true;
      if (!r.ok) throw new Error(`the gateway refused it (${r.status})`);
    } catch (e) {
      this.track(envelope.id, "failed");
      throw e;
    }
  }

  /** Leave frames at the gateway for when the host is back (only its "queued" routes). */
  async queue(frames: Frame[]): Promise<void> {
    const envelope = await seal(this.device.seal, this.device, "down", { expires: Date.now() + QUEUED, frames });
    const r = await fetch("/v1/device/queue", { method: "POST", headers: this.headers(), body: JSON.stringify(envelope) });
    if (!r.ok) throw new Error(`the gateway refused it (${r.status})`);
  }

  async notify(method: string, params: object = {}): Promise<void> {
    await this.send([{ s: null, m: { jsonrpc: "2.0", method, params } }]);
  }

  /** A request on the control channel (or `s`: an app's); its answer comes back through the poll. */
  async request<T>(method: string, params: object = {}, timeout = 30_000, s: string | null = null): Promise<T> {
    const [answer] = await this.ask([{ method, params }], timeout, s);
    const m = await answer!;
    if (m.error) throw new Error((m.error as { message?: string }).message ?? "error");
    return m.result as T;
  }

  /** Several requests of the control channel in one envelope (one trip to the host, which
   *  answers them together); each ends on its own, in their order. */
  async requestAll(calls: Call[], timeout = 30_000): Promise<Settled[]> {
    const answers = await this.ask(calls, timeout, null);
    return await Promise.all(
      answers.map(async (answer): Promise<Settled> => {
        try {
          const m = await answer;
          if (m.error) return { ok: false, error: new Error((m.error as { message?: string }).message ?? "error") };
          return { ok: true, result: m.result };
        } catch (e) {
          return { ok: false, error: e as Error };
        }
      }),
    );
  }

  /** Sends `calls` as the frames of one envelope; their answers, each awaited until `timeout`. */
  private async ask(calls: Call[], timeout: number, s: string | null): Promise<Promise<Message>[]> {
    const ids = calls.map(() => crypto.randomUUID());
    const timers: ReturnType<typeof setTimeout>[] = [];
    const answers = ids.map(
      (id) =>
        new Promise<Message>((resolve, reject) => {
          const timer = setTimeout(() => {
            this.replies.delete(id);
            reject(new Error("the host did not answer (is it online?)"));
          }, timeout);
          timers.push(timer);
          this.replies.set(id, {
            s,
            resolve: (m) => {
              clearTimeout(timer);
              resolve(m);
            },
          });
        }),
    );
    try {
      await this.send(calls.map(({ method, params = {} }, i) => ({ s, m: { jsonrpc: "2.0", id: ids[i], method, params } })));
    } catch (e) {
      for (const timer of timers) clearTimeout(timer);
      for (const id of ids) this.replies.delete(id);
      for (const answer of answers) answer.catch(() => undefined); // never awaited
      throw e;
    }
    return answers;
  }

  // ── receiving ───────────────────────────────────────────────────────

  private async loop(): Promise<void> {
    let backoff = 1_000;
    // the first poll answers at once, and the first after a failure: whether the gateway is
    // reached and the host listens is known now, not after a long poll's wait
    let wait = 0;
    let first = true;
    while (!this.stopped) {
      try {
        const params = new URLSearchParams({ after: this.cursor, wait: String(wait) });
        const r = await fetch(`/v1/device/poll?${params}`, { headers: this.headers() });
        if (r.status === 401) {
          this.unauthorized = true;
          this.reachable = true;
          await sleep(30_000);
          continue;
        }
        if (!r.ok) throw new Error(`gateway: HTTP ${r.status}`);
        const data = (await r.json()) as {
          cursor: string;
          envelopes: Envelope[];
          fetched: string[];
          hostSeen: number | null;
        };
        this.reachable = true;
        this.unauthorized = false;
        this.error = null;
        this.hostSeen = data.hostSeen;
        this.now = Date.now();
        for (const id of data.fetched) this.track(id, "fetched");
        for (const envelope of data.envelopes) await this.receive(envelope);
        this.keepCursor(data.cursor); // once what it covers is opened
        const back = this.hostOnline && !this.listening && !first;
        this.listening = this.hostOnline;
        first = false;
        if (back) this.onHostBack?.();
        backoff = 1_000;
        wait = POLL_WAIT;
      } catch (e) {
        this.listening = false;
        first = false; // what was asked meanwhile went unanswered: once back, the host is asked again
        wait = 0;
        this.reachable = false;
        this.error = (e as Error).message;
        await sleep(backoff);
        backoff = Math.min(backoff * 2, 15_000);
      }
    }
  }

  private keepCursor(cursor: string): void {
    this.cursor = cursor;
    try {
      localStorage.setItem(CURSOR_KEY + this.device.deviceId, cursor);
    } catch {
      /* storage full: this launch only */
    }
  }

  private async receive(envelope: Envelope): Promise<void> {
    if (this.seen.has(envelope.id)) return; // a replay
    let plain: Message;
    try {
      plain = await open(this.device.open, this.device, "up", envelope);
    } catch {
      console.warn("dropped an envelope that does not open with this device's key");
      return;
    }
    const expires = plain.expires as number;
    if (expires < Date.now()) {
      console.warn("dropped an expired envelope (held back, or replayed)");
      return;
    }
    this.seen.add(envelope.id, expires);
    for (const id of (plain.acks as string[] | undefined) ?? []) this.track(id, "delivered");
    for (const r of (plain.rejected as { id: string }[] | undefined) ?? []) this.track(r.id, "expired");
    for (const frame of (plain.frames as Frame[] | undefined) ?? []) {
      this.dispatch(frame);
      // The ACP connection reading a session's channel does not finish one message before it
      // takes the next: given an envelope's frames at once, a short handler overtakes a longer
      // one, and a Handler line lands inside the agent's message. Each frame is taken alone, as
      // a WebSocket message is (one task each).
      if (frame.s !== null) await nextTask();
    }
  }

  private dispatch({ s, m }: Frame): void {
    const answer = typeof m.id === "string" && !m.method;
    if (answer && (s === null || s.startsWith("app:"))) {
      const id = m.id as string;
      const waiting = this.replies.get(id);
      if (waiting?.s === s) {
        this.replies.delete(id);
        waiting.resolve(m);
      } else if (s !== null && id.startsWith("q-")) this.onQueuedAnswer?.(id, m);
      return;
    }
    if (s !== null) {
      this.channels.get(s)?.(m as AnyMessage);
      return;
    }
    if (m.method === "_handler/remote/closed") {
      const p = m.params as ClosedNotice;
      this.closers.get(p.s)?.({ code: p.code, reason: p.reason });
    } else if (typeof m.method === "string") {
      this.onControl?.(m.method, (m.params as Message) ?? {});
    }
  }

  // ── one session's ACP traffic, as a transport ──────────────────────

  transport(s: string): OpenTransport {
    return async (onClose) => {
      this.closers.get(s)?.({ code: 1000, reason: "replaced" });
      let controller!: ReadableStreamDefaultController<AnyMessage>;
      const readable = new ReadableStream<AnyMessage>({ start: (c) => void (controller = c) });
      let done = false;
      const finish = (closed: Closed): void => {
        if (done) return;
        done = true;
        this.channels.delete(s);
        this.closers.delete(s);
        try {
          controller.close();
        } catch {
          /* already closed */
        }
        onClose(closed);
      };
      this.channels.set(s, (m) => controller.enqueue(m));
      this.closers.set(s, finish);
      const writable = new WritableStream<AnyMessage>({ write: (m) => this.send([{ s, m: m as Message }], true) });
      return {
        stream: { readable, writable },
        close: () => {
          const leave: DetachParams = { s };
          if (!done) void this.notify("_handler/remote/detach", leave).catch(() => undefined);
          finish({ code: 1000, reason: "closed" });
        },
      };
    };
  }
}

/** After the microtasks already queued: a MessageChannel's message, which browsers do not
 *  delay as they do a nested `setTimeout(0)`. */
function nextTask(): Promise<void> {
  return new Promise((resolve) => {
    const channel = new MessageChannel();
    channel.port1.onmessage = () => {
      channel.port1.close();
      resolve();
    };
    channel.port2.postMessage(null);
  });
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
