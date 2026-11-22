// A session's card (D.7's since, last, ask): its age, what it asks, and a safe ask answered on the
// card, only the very ask it shows, once (rule phone.a-card-answers-only-the-ask-it-shows; its
// end-to-end test: tests/e2e/test_remote_ui.py).
import type { Closed, OpenTransport } from "@handler/acp-view/lib/connection.svelte";
import { beforeEach, describe, expect, it } from "vitest";
import { app } from "../src/lib/app.svelte";
import { age, answerOnCard, asksWords, cardAnswers } from "../src/lib/card";
import type { Call, Mailbox, Settled } from "../src/lib/mailbox.svelte";
import type { SessionAsk, SharedSession } from "../src/lib/remote.gen";

type Message = Record<string, unknown>;

const OPTIONS = [
  { optionId: "once", name: "Allow once", kind: "allow_once" },
  { optionId: "always", name: "Always allow", kind: "allow_always" },
  { optionId: "no", name: "Reject", kind: "reject_once" },
];

const SAFE: SessionAsk = { toolCallId: "t2", summary: "Read notes.md", kind: "read", risk: "safe" };

function session(fields: Partial<SharedSession> = {}): SharedSession {
  return {
    id: "s1",
    origin: "ui",
    program: "Fake",
    scope: "/home/me/blog",
    acpSessionId: "acp-1",
    busy: true,
    pendingPermissions: 1,
    since: "2026-11-15T12:00:00Z",
    ask: SAFE,
    ...fields,
  };
}

function request(id: string, toolCallId: string, kind = "read"): Message {
  const toolCall = { toolCallId, title: "Read notes.md", kind };
  return { jsonrpc: "2.0", id, method: "session/request_permission", params: { sessionId: "acp-1", toolCall, options: OPTIONS } };
}

/** A computer holding a session that waits on `pending`: it answers the short attachment as
 *  handlerd does (F.4), and says its state again once an answer is taken. */
function computer(pending: Message[]) {
  const written: Message[] = [];
  let closed = false;
  const open: OpenTransport = async (onClose) => {
    let controller!: ReadableStreamDefaultController<unknown>;
    const readable = new ReadableStream({ start: (c) => void (controller = c) });
    const state = (n: number) => ({ jsonrpc: "2.0", method: "_handler/session_state", params: { busy: true, pendingPermissions: n } });
    const writable = new WritableStream({
      write(m: Message) {
        written.push(m);
        if (m.method === "initialize") controller.enqueue({ jsonrpc: "2.0", id: m.id, result: { protocolVersion: 1 } });
        else if (m.method === "session/load") {
          controller.enqueue({ jsonrpc: "2.0", id: m.id, result: {} });
          controller.enqueue(state(pending.length));
          for (const p of pending) controller.enqueue(p);
        } else if ("result" in m) controller.enqueue(state(pending.length - 1));
      },
    });
    return {
      stream: { readable, writable } as never,
      close: () => {
        closed = true;
        onClose({ code: 1000, reason: "closed" } as Closed);
      },
    };
  };
  return { open, written, closed: () => closed };
}

describe("a session's card", () => {
  it("answers only a safe ask, alone, that is not a plan to start from", () => {
    expect(cardAnswers(session())).toBe(true);
    expect(cardAnswers(session({ ask: { ...SAFE, risk: "risky" } }))).toBe(false);
    expect(cardAnswers(session({ pendingPermissions: 2 }))).toBe(false);
    expect(cardAnswers(session({ ask: { ...SAFE, kind: "switch_mode" } }))).toBe(false);
    expect(cardAnswers(session({ ask: null }))).toBe(false); // an older computer: it opens
  });

  it("says what it asks, from its kind, else in general", () => {
    expect(asksWords(session())).toBe("Asks to read a file");
    expect(asksWords(session({ ask: { toolCallId: "t", risk: "risky" } }))).toBe("Asks for your permission");
    expect(asksWords(session({ ask: null, pendingPermissions: 2 }))).toBe("Asks for your permission (2)");
  });

  it("says since when in a few characters; now when the clocks disagree", () => {
    const now = Date.parse("2026-11-15T12:00:00Z");
    expect(age("2026-11-15T11:58:00Z", now)).toBe("2m");
    expect(age("2026-11-15T09:00:00Z", now)).toBe("3h");
    expect(age("2026-11-13T12:00:00Z", now)).toBe("2d");
    expect(age("2026-11-15T12:01:00Z", now)).toBe("now");
  });
});

describe("answering on the card", () => {
  it("attaches without the conversation, allows that ask once, then detaches", async () => {
    const host = computer([request("perm-2", "t2")]);
    expect(await answerOnCard(host.open, session() as never, "allow")).toBe(true);
    const load = host.written.find((m) => m.method === "session/load")!;
    expect((load.params as Message)._meta).toEqual({ "handler.dev/afterSeq": Number.MAX_SAFE_INTEGER });
    expect(host.written.at(-1)).toEqual({ jsonrpc: "2.0", id: "perm-2", result: { outcome: { outcome: "selected", optionId: "once" } } });
    expect(host.closed()).toBe(true);
  });

  it("rejects it once", async () => {
    const host = computer([request("perm-2", "t2")]);
    expect(await answerOnCard(host.open, session() as never, "reject")).toBe(true);
    expect((host.written.at(-1)!.result as Message).outcome).toEqual({ outcome: "selected", optionId: "no" });
  });

  it("answers nothing when the ask it shows is gone or replaced", async () => {
    for (const pending of [[], [request("perm-3", "t3", "execute")], [request("perm-2", "t2", "execute")]]) {
      const host = computer(pending);
      expect(await answerOnCard(host.open, session() as never, "allow")).toBe(false);
      expect(host.written.some((m) => "result" in m)).toBe(false);
      expect(host.closed()).toBe(true);
    }
  });

  it("answers its own ask among others", async () => {
    const host = computer([request("perm-1", "t1", "execute"), request("perm-2", "t2")]);
    expect(await answerOnCard(host.open, session() as never, "allow")).toBe(true);
    expect(host.written.filter((m) => "result" in m).map((m) => m.id)).toEqual(["perm-2"]);
  });
});

describe("the app, from a card", () => {
  beforeEach(() => {
    [app.homeAt, app.fresh, app.answering, app.cardError, app.notice] = [null, true, null, null, null];
  });

  it("opens the session instead, saying so, when the ask changed", async () => {
    const host = computer([request("perm-3", "t3", "execute")]);
    app.mailbox = { transport: () => host.open, hostOnline: true } as unknown as Mailbox;
    const opened: SharedSession[] = [];
    const open = app.open;
    app.open = async (s) => void opened.push(s);
    try {
      await app.answerCard(session(), "allow");
    } finally {
      app.open = open;
    }
    expect(opened.map((s) => s.id)).toEqual(["s1"]);
    expect(app.notice).toContain("Nothing was allowed");
    expect(host.written.some((m) => "result" in m)).toBe(false);
  });

  it("opens a risky ask's session without answering it", async () => {
    const host = computer([request("perm-2", "t2", "execute")]);
    app.mailbox = { transport: () => host.open, hostOnline: true } as unknown as Mailbox;
    const opened: string[] = [];
    const open = app.open;
    app.open = async (s) => void opened.push(s.id);
    try {
      await app.answerCard(session({ ask: { ...SAFE, kind: "execute", risk: "risky" } }), "allow");
    } finally {
      app.open = open;
    }
    expect(opened).toEqual(["s1"]);
    expect(host.written).toEqual([]);
  });
});

describe("a message read on the phone", () => {
  it("is told to the computer, and shown read as it says", async () => {
    const calls: Call[][] = [];
    app.mailbox = {
      hostOnline: true,
      async requestAll(c: Call[]): Promise<Settled[]> {
        calls.push(c);
        return c.map((x) => ({ ok: true, result: { id: (x.params as { id: string }).id, read: true } }));
      },
    } as unknown as Mailbox;
    [app.homeAt, app.fresh] = [1, true];
    app.inbox = [{ id: "m1", read: false } as never];
    app.markRead("m1");
    await new Promise((r) => setTimeout(r, 0));
    expect(calls).toEqual([[{ method: "_handler/remote/inbox_read", params: { id: "m1" } }]]);
    expect(app.inbox[0]!.read).toBe(true);
    expect(app.isRead(app.inbox[0]!)).toBe(true);
  });
});
