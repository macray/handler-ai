// Envelopes (docs/dev/design/remote.md §4) in WebCrypto — the device side of
// packages/control-plane/src/handler_control/remote_crypto.py, checked against the same test vectors.
//
//   keys  HKDF-SHA256(K, salt "handler-remote/v1", info "down" | "up" | "gateway-auth")
//   seal  AES-256-GCM, random 96-bit nonce, AAD "handler-remote/v1|hostId|deviceId|dir|id"
//   plain {expires: unix ms, frames, …}: taken once, before it expires (mailbox.svelte.ts)
//
// The device key K is imported once, at pairing, and never kept: what is stored (IndexedDB) are
// the derived AES keys, non-extractable — page scripts can use them, not read them.

export const VERSION = "handler-remote/v1";
export type Direction = "down" | "up";

const enc = new TextEncoder();
const dec = new TextDecoder();

export function b64(bytes: Uint8Array): string {
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
}

export function unb64(text: string): Uint8Array<ArrayBuffer> {
  const s = atob(text.replaceAll("-", "+").replaceAll("_", "/") + "=".repeat((4 - (text.length % 4)) % 4));
  const out = new Uint8Array(s.length);
  for (let i = 0; i < s.length; i++) out[i] = s.charCodeAt(i);
  return out;
}

function hkdf(info: string): HkdfParams {
  return { name: "HKDF", hash: "SHA-256", salt: enc.encode(VERSION), info: enc.encode(info) };
}

export async function importDeviceKey(raw: Uint8Array<ArrayBuffer>): Promise<CryptoKey> {
  return crypto.subtle.importKey("raw", raw, "HKDF", false, ["deriveKey", "deriveBits"]);
}

export async function deriveBits(base: CryptoKey, info: string): Promise<Uint8Array> {
  return new Uint8Array(await crypto.subtle.deriveBits(hkdf(info), base, 256));
}

/** The AES key of one direction, non-extractable. The device seals "down" and opens "up". */
export async function directionKey(base: CryptoKey, direction: Direction): Promise<CryptoKey> {
  const usage: KeyUsage = direction === "down" ? "encrypt" : "decrypt";
  return crypto.subtle.deriveKey(hkdf(direction), base, { name: "AES-GCM", length: 256 }, false, [usage]);
}

/** The device's secret towards the gateway (sent as `<deviceId>.<token>`); not a key. */
export async function gatewayToken(base: CryptoKey): Promise<string> {
  return b64(await deriveBits(base, "gateway-auth"));
}

function aad(hostId: string, deviceId: string, direction: Direction, id: string): Uint8Array<ArrayBuffer> {
  return enc.encode(`${VERSION}|${hostId}|${deviceId}|${direction}|${id}`);
}

export interface Envelope {
  id: string;
  nonce: string;
  ct: string;
}

export interface Address {
  hostId: string;
  deviceId: string;
}

export async function seal(key: CryptoKey, to: Address, direction: Direction, plaintext: unknown): Promise<Envelope> {
  const id = b64(crypto.getRandomValues(new Uint8Array(16)));
  const nonce = crypto.getRandomValues(new Uint8Array(12));
  const data = enc.encode(JSON.stringify(plaintext));
  const additionalData = aad(to.hostId, to.deviceId, direction, id);
  const ct = new Uint8Array(await crypto.subtle.encrypt({ name: "AES-GCM", iv: nonce, additionalData }, key, data));
  return { id, nonce: b64(nonce), ct: b64(ct) };
}

/** The plaintext, or an error if the envelope was not sealed for this device and direction. */
export async function open(key: CryptoKey, at: Address, direction: Direction, envelope: Envelope): Promise<Record<string, unknown>> {
  const additionalData = aad(at.hostId, at.deviceId, direction, envelope.id);
  const data = await crypto.subtle.decrypt({ name: "AES-GCM", iv: unb64(envelope.nonce), additionalData }, key, unb64(envelope.ct));
  const plaintext: unknown = JSON.parse(dec.decode(data));
  if (typeof plaintext !== "object" || plaintext === null || typeof (plaintext as { expires?: unknown }).expires !== "number") {
    throw new Error("envelope without expiry");
  }
  return plaintext as Record<string, unknown>;
}
