// What the bell counts and lists, for every project and app (sessions polled with those started
// elsewhere, lib/sessions.svelte.ts; the inbox's, lib/inbox.svelte.ts): the sessions that need
// you plus the runs and plans that failed or want an answer wait; the sessions working run. The
// browser tab says the same count (App.svelte, lib/favicon.ts).
import { inbox } from "./inbox.svelte";
import { bellState } from "./menu";
import { sessions, type LiveSession } from "./sessions.svelte";

class Bell {
  get waiting() {
    return sessions.list.filter((s) => s.status === "needs-you");
  }
  get running() {
    return sessions.list.filter((s) => s.status === "working" || s.status === "starting");
  }
  get told() {
    return inbox.waiting;
  }
  get count(): number {
    return this.waiting.length + this.told.length;
  }
  get state() {
    return bellState(this.count, this.running.length);
  }
}

export const bell = new Bell();

/** The question a session waiting for you asks, when this tab is attached to it (else none: it
 *  is opened to be answered), with its first allow and its first reject. */
export function question(s: LiveSession) {
  const pending = s.conn?.permissions[0];
  if (!pending) return null;
  const options = pending.request.options;
  const pick = (kind: string) => options.find((o) => o.kind === `${kind}_once`) ?? options.find((o) => o.kind.startsWith(kind));
  return { title: pending.request.toolCall.title, allow: pick("allow"), reject: pick("reject"), answer: pending.answer };
}
