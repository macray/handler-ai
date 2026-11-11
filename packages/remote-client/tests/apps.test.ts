// The phone's side of an app's backend calls (apps design §5.2–5.3).
import { beforeEach, describe, expect, it } from "vitest";
import { carry, queuedCalls, type FrameFetch } from "../src/lib/apps";
import type { Mailbox } from "../src/lib/mailbox.svelte";

function fetchFrom(method: string, path: string): FrameFetch {
  return { type: "handler-app-fetch", id: 1, method, path, headers: { "content-type": "application/json" }, body: null };
}

function mailbox(online: boolean) {
  const sent: { queued: unknown[]; requests: unknown[] } = { queued: [], requests: [] };
  const box = {
    hostOnline: online,
    async queue(frames: unknown[]) {
      sent.queued.push(...frames);
    },
    async request(_method: string, params: unknown) {
      sent.requests.push(params);
      return { status: 200, headers: { "content-type": "application/json" }, body: btoa('{"ok":true}') };
    },
  };
  return { box: box as unknown as Mailbox, sent };
}

const coach = { name: "coach", description: null, version: "1.0.0", queued: ["POST /api/checkin"] };

describe("carry", () => {
  beforeEach(() => localStorage.clear());

  it("only reaches /api/… of the app", async () => {
    const { box, sent } = mailbox(true);
    const answer = await carry(box, coach, fetchFrom("GET", "/other"));
    expect(answer.error).toMatch(/only \/api/);
    expect(sent.requests).toEqual([]);
  });

  it("carries a call to handler with an idempotency key", async () => {
    const { box, sent } = mailbox(true);
    const answer = await carry(box, coach, fetchFrom("POST", "/api/checkin"));
    expect(answer.status).toBe(200);
    expect((sent.requests[0] as { headers: Record<string, string> }).headers["idempotency-key"]).toBeTruthy();
  });

  it("queues a queued route while the host is off, and answers 202 at once", async () => {
    const { box, sent } = mailbox(false);
    const answer = await carry(box, coach, fetchFrom("POST", "/api/checkin"));
    expect(answer.status).toBe(202);
    expect(JSON.parse(new TextDecoder().decode(answer.body))).toMatchObject({ queued: true });
    expect(sent.requests).toEqual([]);
    expect(sent.queued).toHaveLength(1);
    expect(queuedCalls().map((c) => c.route)).toEqual(["POST /api/checkin"]);
  });

  it("does not queue other routes: they fail like a network error would", async () => {
    const { box, sent } = mailbox(false);
    await carry(box, coach, fetchFrom("POST", "/api/other"));
    expect(sent.queued).toEqual([]);
    expect(sent.requests).toHaveLength(1); // tried (and would time out)
  });
});
