// What the phone takes from the host (remote design §4): each envelope once, before
// it expires, a reload included; an answer only for the request it answers, on its channel. The
// gateway may replay old envelopes, which the host sealed and the phone opens.
import { beforeEach, describe, expect, it, vi } from "vitest";
import { deriveBits, directionKey, gatewayToken, importDeviceKey, open, seal, unb64, type Envelope } from "../src/lib/crypto";
import { Mailbox } from "../src/lib/mailbox.svelte";
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
});
