// The WebCrypto side of the envelopes, against the vectors the Python connector is tested with
// (tests/fixtures/remote-vectors.json): both ends must derive the same keys and open each
// other's envelopes.
import { describe, expect, it } from "vitest";
import { b64, deriveBits, directionKey, gatewayToken, importDeviceKey, open, seal, unb64, type Envelope } from "../src/lib/crypto";
import { readFragment } from "../src/lib/pairing";
import fixture from "../../../tests/fixtures/remote-vectors.json";

const vectors = fixture as unknown as {
  key: string;
  hostId: string;
  deviceId: string;
  derived: { down: string; up: string; gatewayToken: string };
  down: { envelope: Envelope; plaintext: unknown };
  up: { envelope: Envelope; plaintext: unknown };
};
const address = { hostId: vectors.hostId, deviceId: vectors.deviceId };
const hex = (bytes: Uint8Array) => Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");

/** A key for the host's side of "down" (the device only ever encrypts with it). */
async function hostDownKey(base: CryptoKey): Promise<CryptoKey> {
  const raw = await deriveBits(base, "down");
  return crypto.subtle.importKey("raw", raw as Uint8Array<ArrayBuffer>, "AES-GCM", false, ["decrypt"]);
}

describe("envelopes", () => {
  it("derives the same keys as the host", async () => {
    const base = await importDeviceKey(unb64(vectors.key));
    expect(hex(await deriveBits(base, "down"))).toBe(vectors.derived.down);
    expect(hex(await deriveBits(base, "up"))).toBe(vectors.derived.up);
    expect(await gatewayToken(base)).toBe(vectors.derived.gatewayToken);
  });

  it("opens what the host sealed", async () => {
    const base = await importDeviceKey(unb64(vectors.key));
    const up = await directionKey(base, "up");
    expect(await open(up, address, "up", vectors.up.envelope)).toEqual(vectors.up.plaintext);
  });

  it("seals what the host opens, and nothing else opens", async () => {
    const base = await importDeviceKey(unb64(vectors.key));
    const down = await directionKey(base, "down");
    const hostKey = await hostDownKey(base);
    expect(await open(hostKey, address, "down", vectors.down.envelope)).toEqual(vectors.down.plaintext);

    const plain = { ts: 1, frames: [{ s: "s_1", m: { jsonrpc: "2.0", id: 3 } }] };
    const envelope = await seal(down, address, "down", plain);
    expect(await open(hostKey, address, "down", envelope)).toEqual(plain);
    // reflected, relabelled, for another device, or altered: refused
    await expect(open(await directionKey(base, "up"), address, "up", envelope)).rejects.toThrow();
    await expect(open(hostKey, address, "down", { ...envelope, id: "x".repeat(22) })).rejects.toThrow();
    await expect(open(hostKey, { ...address, deviceId: "d_0000000000000000" }, "down", envelope)).rejects.toThrow();
    const ct = unb64(envelope.ct);
    ct[0] = (ct[0] ?? 0) ^ 1;
    await expect(open(hostKey, address, "down", { ...envelope, ct: b64(ct) })).rejects.toThrow();
  });

  it("keeps the device's keys unreadable", async () => {
    const base = await importDeviceKey(unb64(vectors.key));
    const down = await directionKey(base, "down");
    expect(down.extractable).toBe(false);
    await expect(crypto.subtle.exportKey("raw", down)).rejects.toThrow();
  });
});

describe("pairing links", () => {
  const payload = { v: 1, g: "https://gw.example", h: vectors.hostId, d: vectors.deviceId, k: vectors.key, n: "phone" };
  const fragment = `#pair=${b64(new TextEncoder().encode(JSON.stringify(payload)))}`;

  it("reads the QR code's fragment", () => {
    const info = readFragment(fragment);
    expect(info).toMatchObject({ gateway: "https://gw.example", hostId: vectors.hostId, deviceId: vectors.deviceId, name: "phone" });
    expect(info?.key.length).toBe(32);
  });

  it("ignores other fragments and refuses malformed codes", () => {
    expect(readFragment("")).toBeNull();
    expect(readFragment("#/s/s_1")).toBeNull();
    const bad = { ...payload, k: b64(new Uint8Array(8)) };
    expect(() => readFragment(`#pair=${b64(new TextEncoder().encode(JSON.stringify(bad)))}`)).toThrow("not valid");
  });
});
