// A session's card on Sessions: since when it is in its state, its last line, its ask; and a safe
// ask answered on the card itself (D.7's `ask`, rule phone.a-card-answers-only-the-ask-it-shows).
//
// The card is not attached to its session. To answer, the phone attaches for a moment, without the
// conversation (`session/load` after the log's end: `handler.dev/afterSeq`, F.5), so the host sends
// only the session's state and its pending requests again (F.4). It answers the request whose tool
// call is the card's, and only that one: once, never "always"; then detaches. When that request is
// gone (answered on the computer, replaced by another one), nothing is answered: the session opens.
import type { Closed, OpenTransport } from "@handler/acp-view/lib/connection.svelte";
import type { SessionAsk, SharedSession } from "./remote.gen";

type Message = Record<string, unknown>;
type ToolCall = { toolCallId?: unknown; kind?: unknown };
type Option = { optionId?: unknown; kind?: unknown };

/** How long a card's answer may take, from attaching to the host saying it took it. */
const ANSWER_TIMEOUT = 30_000;

/** Whether a session's card answers its ask itself (Reject / Allow): only a safe one, not a plan
 *  to start from (its plan is read first, in the session), and only while it is the one ask. */
export function cardAnswers(s: SharedSession): s is SharedSession & { ask: SessionAsk } {
  return s.ask?.risk === "safe" && s.ask.kind !== "switch_mode" && s.pendingPermissions === 1;
}

const ASKS_TO: Partial<Record<NonNullable<SessionAsk["kind"]>, string>> = {
  execute: "Asks to run a command",
  edit: "Asks to change a file",
  delete: "Asks to delete a file",
  move: "Asks to move a file",
  fetch: "Asks to reach the network",
  read: "Asks to read a file",
  search: "Asks to search",
  switch_mode: "Asks to start from its plan",
};

/** What a card that needs you says it asks: from its ask's kind, else in general; with how many
 *  when there are more. */
export function asksWords(s: SharedSession): string {
  const words = (s.ask?.kind && ASKS_TO[s.ask.kind]) || "Asks for your permission";
  return s.pendingPermissions > 1 ? `${words} (${s.pendingPermissions})` : words;
}

/** How long a session is in its state, in a few characters: "now", "4m", "2h", "3d". The phone's
 *  clock behind the computer's: "now". */
export function age(since: string, now = Date.now()): string {
  const s = (now - Date.parse(since)) / 1000;
  if (s < 60) return "now";
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}

/** The request's answer the card gives: Allow is once (never "always"), Reject once. */
function optionFor(options: Option[], answer: "allow" | "reject"): string | null {
  const kinds = answer === "allow" ? ["allow_once"] : ["reject_once", "reject_always"];
  for (const kind of kinds) {
    const found = options.find((o) => o.kind === kind && typeof o.optionId === "string");
    if (found) return found.optionId as string;
  }
  return null;
}

/** Answer the card's ask over a short attachment: true once the host took the answer; false when
 *  nothing was answered because the session no longer waits on that very ask (the session is to
 *  be opened instead). Throws when the host refuses or does not answer in time. */
export async function answerOnCard(
  open: OpenTransport,
  s: SharedSession & { ask: SessionAsk },
  answer: "allow" | "reject",
  timeout = ANSWER_TIMEOUT,
): Promise<boolean> {
  if (!s.acpSessionId) return false;
  let closed: Closed | null = null;
  const transport = await open((c) => void (closed = c));
  const reader = transport.stream.readable.getReader();
  const writer = transport.stream.writable.getWriter();
  const deadline = Date.now() + timeout;
  let timer: ReturnType<typeof setTimeout> | undefined;
  /** The next message from the host; throws once the attachment is closed or the time is up. */
  const next = async (): Promise<Message> => {
    const late = new Promise<never>((_, fail) => {
      timer = setTimeout(() => fail(new Error("Your computer did not answer in time.")), Math.max(0, deadline - Date.now()));
    });
    try {
      const read = await Promise.race([reader.read(), late]);
      if (read.done) throw new Error((closed as Closed | null)?.reason || "The session closed.");
      return read.value as Message;
    } finally {
      clearTimeout(timer);
    }
  };
  const failed = (m: Message): Error => new Error(((m.error as Message | undefined)?.message as string) || "Refused.");
  try {
    const load = {
      sessionId: s.acpSessionId,
      cwd: s.scope,
      mcpServers: [],
      _meta: { "handler.dev/afterSeq": Number.MAX_SAFE_INTEGER }, // no conversation: its state alone
    };
    const hello = { protocolVersion: 1, clientCapabilities: { fs: { readTextFile: false, writeTextFile: false }, terminal: false } };
    await writer.write({ jsonrpc: "2.0", id: 1, method: "initialize", params: hello } as never);
    await writer.write({ jsonrpc: "2.0", id: 2, method: "session/load", params: load } as never);
    // after the load's answer, in this order and nothing between: the session's state, then each
    // request it waits on (F.4)
    let waiting: number | null = null;
    let loaded = false;
    const asked: Message[] = [];
    while (waiting === null || asked.length < waiting) {
      const m = await next();
      if ((m.id === 1 || m.id === 2) && "error" in m) throw failed(m);
      if (m.id === 2) loaded = true;
      else if (loaded && waiting === null && m.method === "_handler/session_state") {
        waiting = Number((m.params as Message | undefined)?.pendingPermissions ?? 0);
      } else if (waiting !== null && m.method === "session/request_permission") asked.push(m);
    }
    const mine = asked.find((m) => {
      const tool = ((m.params as Message | undefined)?.toolCall ?? {}) as ToolCall;
      return tool.toolCallId === s.ask.toolCallId && (s.ask.kind == null || tool.kind === s.ask.kind);
    });
    const optionId = mine && optionFor(((mine.params as Message).options ?? []) as Option[], answer);
    if (!mine || !optionId) return false;
    await writer.write({ jsonrpc: "2.0", id: mine.id, result: { outcome: { outcome: "selected", optionId } } } as never);
    // taken: the host says the session's state again, one ask fewer
    for (;;) {
      const m = await next();
      if (m.method === "_handler/session_state" && Number((m.params as Message | undefined)?.pendingPermissions) < asked.length) return true;
    }
  } finally {
    transport.close(); // detached: the host forgets this attachment
  }
}
