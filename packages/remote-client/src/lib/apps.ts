// Apps on the phone (handler's apps design §5.2): the app's page comes from
// handler over the `app:<name>` channel (inlined, one HTML page), is kept for when the host is
// offline, and runs in the sandboxed /appframe.html. Its backend calls reach this client by
// postMessage and go to handler sealed, like everything else; only /api/… of that app is
// reachable.
import type { Mailbox } from "./mailbox.svelte";
import type { AppHttpAnswer, AppHttpParams, AppUi, AppUiParams, SharedApp } from "./remote.gen";
import { unb64 } from "./crypto"; // the standard alphabet too

/** A call left at the gateway while the host was off; `done` once handler answered it. */
export interface QueuedCall {
  id: string;
  app: string;
  route: string;
  at: number;
  done?: boolean;
  status?: number;
}

const QUEUED_KEY = "handler-queued-calls";

export function queuedCalls(): QueuedCall[] {
  try {
    return JSON.parse(localStorage.getItem(QUEUED_KEY) ?? "[]");
  } catch {
    return [];
  }
}

export function saveQueuedCalls(calls: QueuedCall[]): void {
  try {
    localStorage.setItem(QUEUED_KEY, JSON.stringify(calls.slice(-50)));
  } catch {
    /* storage full */
  }
}

export interface AppPage {
  version: string;
  html: string;
  cached: boolean; // shown from this phone's copy: the host did not answer
}

/** What the frame posts for one backend call (see public/appframe.html). */
export interface FrameFetch {
  type: "handler-app-fetch";
  id: number;
  method: string;
  path: string;
  headers: Record<string, string>;
  body: ArrayBuffer | null;
}

export interface FrameAnswer {
  type: "handler-app-response";
  id: number;
  status?: number;
  headers?: Record<string, string>;
  body?: Uint8Array;
  error?: string;
}

const REQUEST_BYTES = 128 * 1024; // handler refuses bigger (a down envelope is 256 KiB)
const UI_TIMEOUT = 20_000;
const CALL_TIMEOUT = 90_000; // a backend may call a model

const cacheKey = (name: string): string => `handler-app-page:${name}`;

function cached(name: string): { version: string; html: string } | null {
  try {
    return JSON.parse(localStorage.getItem(cacheKey(name)) ?? "null");
  } catch {
    return null;
  }
}

function keep(name: string, page: { version: string; html: string }): void {
  try {
    localStorage.setItem(cacheKey(name), JSON.stringify(page));
  } catch {
    /* storage full: the page still works, just not offline */
  }
}

export function forgetPages(): void {
  for (const key of Object.keys(localStorage)) if (key.startsWith("handler-app-page:")) localStorage.removeItem(key);
}

/** The app's page: handler's current version (sent only when it changed), else this phone's copy. */
export async function loadPage(mailbox: Mailbox, name: string): Promise<AppPage> {
  const copy = cached(name);
  try {
    const params: AppUiParams = copy ? { have: copy.version } : {};
    const r = await mailbox.request<AppUi>("_handler/app/ui", params, UI_TIMEOUT, `app:${name}`);
    if (r.unchanged && copy) return { ...copy, cached: false };
    if (r.html == null) throw new Error("the host sent no page");
    keep(name, { version: r.version, html: r.html });
    return { version: r.version, html: r.html, cached: false };
  } catch (e) {
    if (copy) return { ...copy, cached: true };
    throw e;
  }
}

function toBase64(bytes: Uint8Array): string {
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(binary);
}

/** One backend call from the frame, carried to handler; network-like failures become `error`. A call
 *  to a route the app declares queued, while the host is off, is left at the gateway instead and
 *  answered 202 `{queued: true, id}` at once: handler runs it when it is back
 *  (apps design §5.3). */
export async function carry(mailbox: Mailbox, shared: SharedApp, m: FrameFetch): Promise<FrameAnswer> {
  const name = shared.name;
  const url = new URL(m.path, "http://app");
  const path = url.pathname + url.search;
  const key = m.headers["idempotency-key"] ?? crypto.randomUUID();
  const headers = { ...m.headers, "idempotency-key": key };
  if (!(path === "/api" || path.startsWith("/api/"))) {
    return { type: "handler-app-response", id: m.id, error: `only /api/… is reachable, not ${path}` };
  }
  const body = m.body ? new Uint8Array(m.body) : null;
  if (body && body.length > REQUEST_BYTES) {
    return { type: "handler-app-response", id: m.id, error: `request over ${REQUEST_BYTES / 1024} KiB` };
  }
  const params: AppHttpParams = { method: m.method, path, headers, body: body ? toBase64(body) : "" };
  const route = `${m.method} ${url.pathname}`;
  if (shared.queued?.includes(route) && !mailbox.hostOnline) {
    const id = `q-${key}`;
    try {
      await mailbox.queue([{ s: `app:${name}`, m: { jsonrpc: "2.0", id, method: "_handler/app/http", params } }]);
    } catch (e) {
      return { type: "handler-app-response", id: m.id, error: (e as Error).message };
    }
    saveQueuedCalls([...queuedCalls(), { id, app: name, route, at: Date.now() }]);
    const text = JSON.stringify({ queued: true, id });
    return {
      type: "handler-app-response",
      id: m.id,
      status: 202,
      headers: { "content-type": "application/json", "x-handler-queued": id },
      body: new TextEncoder().encode(text),
    };
  }
  try {
    const r = await mailbox.request<AppHttpAnswer>("_handler/app/http", params, CALL_TIMEOUT, `app:${name}`);
    return { type: "handler-app-response", id: m.id, status: r.status, headers: r.headers, body: unb64(r.body) };
  } catch (e) {
    return { type: "handler-app-response", id: m.id, error: (e as Error).message };
  }
}
