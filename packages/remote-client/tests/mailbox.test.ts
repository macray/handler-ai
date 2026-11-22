// What the phone takes from the host (remote design §4): each envelope once, before
// it expires, a reload included; an answer only for the request it answers, on its channel. The
// gateway may replay old envelopes, which the host sealed and the phone opens.
import { beforeEach, describe, expect, it, vi } from "vitest";
import { deriveBits, directionKey, gatewayToken, importDeviceKey, open, seal, unb64, type Envelope } from "../src/lib/crypto";
import { forgetLink, Mailbox } from "../src/lib/mailbox.svelte";
import { AcpConnection } from "@handler/acp-view/lib/connection.svelte";
import type { Device } from "../src/lib/pairing";
import fixture from "../../../tests/fixtures/remote-vectors.json";

const address = { hostId: fixture.hostId, deviceId: fixture.deviceId };

async function keys() {
  const base = await importDeviceKey(unb64(fixture.key));
  const raw = async (info: string, usage: KeyUsage) =>
    crypto.subtle.importKey("raw", (await deriveBits(base, info)) as Uint8Array<ArrayBuffer>, "AES-GCM", false, [usage]);
  const device: Device = {
    gateway: "https://gw.example",
    ...address,
    name: "phone",
    seal: await directionKey(base, "down"),
    open: await directionKey(base, "up"),
    token: await gatewayToken(base),
  };
  // the host's side: it opens "down", seals "up"
  return { device, hostOpen: await raw("down", "decrypt"), hostSeal: await raw("up", "encrypt") };
}

type Frames = { s: string | null; m: Record<string, unknown> }[];
const receive = (box: Mailbox, envelope: Envelope) =>
  (box as unknown as { receive(e: Envelope): Promise<void> }).receive(envelope);

describe("what the phone takes from the host", () => {
  let k: Awaited<ReturnType<typeof keys>>;
  let sent: Envelope[];
  const up = (frames: Frames, expires = Date.now() + 60_000) => seal(k.hostSeal, address, "up", { expires, frames });
  const changed: Frames = [{ s: null, m: { jsonrpc: "2.0", method: "_handler/remote/sessions_changed", params: {} } }];

  beforeEach(async () => {
    sessionStorage.clear();
    localStorage.clear();
    k = await keys();
    sent = [];
    vi.stubGlobal("fetch", async (_url: string, init: RequestInit) => {
      sent.push(JSON.parse(init.body as string));
      return new Response(null, { status: 202 });
    });
  });

  it("takes an envelope once, even after a reload", async () => {
    const envelope = await up(changed);
    const box = new Mailbox(k.device);
    const seen = vi.fn();
    box.onControl = seen;
    await receive(box, envelope);
    await receive(box, envelope);
    const reloaded = new Mailbox(k.device);
    reloaded.onControl = seen;
    await receive(reloaded, envelope);
    expect(seen).toHaveBeenCalledTimes(1);
  });

  it("refuses an expired envelope", async () => {
    const box = new Mailbox(k.device);
    box.onControl = vi.fn();
    await receive(box, await up(changed, Date.now() - 1));
    expect(box.onControl).not.toHaveBeenCalled();
  });

  it("gives a request only its own answer, on its channel", async () => {
    const box = new Mailbox(k.device);
    const asked = box.request<{ n: number }>("_handler/remote/list_apps");
    await vi.waitFor(() => expect(sent).toHaveLength(1));
    const plain = await open(k.hostOpen, address, "down", sent[0]!);
    expect(plain.expires).toBeGreaterThan(Date.now()); // the host refuses it after
    const id = (plain.frames as Frames)[0]!.m.id;
    expect(typeof id).toBe("string"); // random: no old answer has it
    // an old answer (a counter's id), then the right id on another channel: neither is taken
    await receive(box, await up([{ s: null, m: { jsonrpc: "2.0", id: 1, result: { n: 1 } } }]));
    await receive(box, await up([{ s: "app:other", m: { jsonrpc: "2.0", id, result: { n: 2 } } }]));
    await receive(box, await up([{ s: null, m: { jsonrpc: "2.0", id, result: { n: 3 } } }]));
    expect(await asked).toEqual({ n: 3 });
  });

  it("asks several things in one envelope, each ending on its own", async () => {
    const box = new Mailbox(k.device);
    const all = box.requestAll([{ method: "_handler/remote/list_apps" }, { method: "_handler/remote/inbox" }, { method: "_handler/remote/ask_options" }]);
    await vi.waitFor(() => expect(sent).toHaveLength(1));
    const plain = await open(k.hostOpen, address, "down", sent[0]!);
    const frames = plain.frames as Frames;
    expect(frames.map((f) => f.m.method)).toEqual(["_handler/remote/list_apps", "_handler/remote/inbox", "_handler/remote/ask_options"]);
    expect(new Set(frames.map((f) => f.m.id)).size).toBe(3); // each its own random id
    const [apps, inbox, ask] = frames.map((f) => f.m.id);
    // the host answers them together, in any order; one refused
    await receive(
      box,
      await up([
        { s: null, m: { jsonrpc: "2.0", id: ask, error: { code: -32602, message: "Ask is for the owner's devices" } } },
        { s: null, m: { jsonrpc: "2.0", id: inbox, result: { messages: [] } } },
        { s: null, m: { jsonrpc: "2.0", id: apps, result: { apps: [] } } },
      ]),
    );
    const settled = await all;
    expect(settled.slice(0, 2)).toEqual([
      { ok: true, result: { apps: [] } },
      { ok: true, result: { messages: [] } },
    ]);
    expect(settled[2]).toMatchObject({ ok: false, error: { message: "Ask is for the owner's devices" } });
  });

  it("shows a session's frames in the order the host sent them, an envelope's together", async () => {
    const box = new Mailbox(k.device);
    const conn = new AcpConnection();
    const connected = conn.connect(box.transport("s1"));
    await vi.waitFor(() => expect(sent).toHaveLength(1));
    const asked = (await open(k.hostOpen, address, "down", sent[0]!)).frames as Frames;
    const id = asked[0]!.m.id;
    await receive(box, await up([{ s: "s1", m: { jsonrpc: "2.0", id, result: { protocolVersion: 1, agentCapabilities: {} } } }]));
    await connected;
    const update = (text: string) => ({
      s: "s1",
      m: { jsonrpc: "2.0", method: "session/update", params: { sessionId: "x", update: { sessionUpdate: "agent_message_chunk", content: { type: "text", text } } } },
    });
    const told = { s: "s1", m: { jsonrpc: "2.0", method: "_handler/line", params: { event: "told agent", text: "go on" } } };
    // a replay: the agent's first message, Handler's line, the agent's next one
    await receive(box, await up([update("one, "), update("two."), told, update("three")]));
    await vi.waitFor(() => expect(conn.session.entries).toHaveLength(3));
    expect(conn.session.entries.map((e) => [e.kind, "text" in e ? e.text : null])).toEqual([
      ["agent", "one, two."],
      ["told", "go on"],
      ["agent", "three"],
    ]);
  });

  it("takes an envelope once across launches, but a page started earlier still takes it", async () => {
    const envelope = await up(changed);
    const earlier = new Mailbox(k.device); // another tab, open before the envelope came
    const box = new Mailbox(k.device);
    box.onControl = vi.fn();
    earlier.onControl = vi.fn();
    await receive(box, envelope);
    sessionStorage.clear(); // a new launch: nothing of the last one's tab
    const next = new Mailbox(k.device);
    next.onControl = vi.fn();
    await receive(next, envelope);
    expect(next.onControl).not.toHaveBeenCalled(); // a gateway replaying it gets nothing
    await receive(earlier, envelope);
    expect(earlier.onControl).toHaveBeenCalledTimes(1); // it may be waiting for it
    forgetLink(k.device.deviceId); // a forgotten device keeps nothing
    expect(Object.keys(localStorage).filter((key) => key.includes(k.device.deviceId))).toEqual([]);
  });
});

describe("where the poll is", () => {
  let k: Awaited<ReturnType<typeof keys>>;
  let polls: URLSearchParams[];

  beforeEach(async () => {
    localStorage.clear();
    k = await keys();
    polls = [];
    vi.stubGlobal("fetch", async (url: string) => {
      const params = new URL(url, "https://gw.example").searchParams;
      polls.push(params);
      if (polls.length > 1) return new Promise(() => undefined); // a long poll, waiting
      return Response.json({ cursor: "ep-7", envelopes: [], fetched: [], hostSeen: Date.now() });
    });
  });

  it("answers at once first, then long-polls; a new launch goes on from where the last one was", async () => {
    const box = new Mailbox(k.device);
    box.start();
    await vi.waitFor(() => expect(polls).toHaveLength(2));
    box.stop();
    expect([polls[0]!.get("after"), polls[0]!.get("wait")]).toEqual(["", "0"]); // whether the host listens, now
    expect(box.hostOnline).toBe(true);
    expect([polls[1]!.get("after"), polls[1]!.get("wait")]).toEqual(["ep-7", "25"]);

    polls = [];
    const next = new Mailbox(k.device); // the next launch: not the old envelopes again
    next.start();
    await vi.waitFor(() => expect(polls).toHaveLength(2));
    next.stop();
    expect(polls[0]!.get("after")).toBe("ep-7");
  });
});

