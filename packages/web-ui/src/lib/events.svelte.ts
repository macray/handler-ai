// The event stream (D.30): handlerd says which topic changed, never what: an area changed through
// the API (from any tab, the CLI), or what handlerd changed by itself. A page or a store reads what it shows again on its topics (`onChange`), and everything
// again whenever the stream (re)opens, so a change told while it was closed is never missed. One
// stream for the whole page, opened by the first to listen; the browser reconnects it by itself.
export type Topic =
  | "sessions"
  | "inbox"
  | "ask" // Ask's history (D.24): an ask kept, ended, deleted
  | "apps"
  | "agents" // an agent, its connections (terminals, editors), its checks and improvements
  | "projects"
  | "automations"
  | "plans"
  | "plan-drafts"
  | "handler-needs"
  | "builds";

const readers = new Map<Topic, Set<() => void>>();
let source: EventSource | null = null;

function all(): Set<() => void> {
  return new Set([...readers.values()].flatMap((set) => [...set]));
}

function open(): void {
  if (source) return;
  source = new EventSource("/v1/events");
  source.onopen = () => all().forEach((read) => read());
  source.onmessage = (e: MessageEvent<string>) => readers.get(e.data as Topic)?.forEach((read) => read());
  // back online (Wi-Fi back, the computer awake): a new stream now, not at the browser's next try
  window.addEventListener("online", again, { once: true });
}

function again(): void {
  source?.close();
  source = null;
  open();
}

/** `read` called when one of `topics` changes, and when the stream (re)opens; returns the stop.
 *  Listen before reading what it shows, so a change made while that read is under way is told. */
export function onChange(topics: Topic[], read: () => void): () => void {
  for (const topic of topics) {
    if (!readers.has(topic)) readers.set(topic, new Set());
    readers.get(topic)!.add(read);
  }
  open();
  return () => topics.forEach((topic) => readers.get(topic)?.delete(read));
}
