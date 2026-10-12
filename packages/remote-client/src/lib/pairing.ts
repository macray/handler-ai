// Pairing (docs/dev/design/remote.md §3): handler shows a QR code for
// `https://<gateway>/#pair=<base64url JSON>`. The fragment never reaches a server; it is read here,
// turned into non-extractable keys, stored in IndexedDB, and removed from the address bar.
import { directionKey, gatewayToken, importDeviceKey, unb64, type Address } from "./crypto";

export interface PairingInfo {
  gateway: string; // the gateway's URL, as handler knows it
  hostId: string;
  deviceId: string;
  name: string; // this device's name on the host
}

/** What the app keeps: who it is, and its keys (usable, not readable). */
export interface Device extends PairingInfo, Address {
  seal: CryptoKey; // "down": device → host, encrypt only
  open: CryptoKey; // "up": host → device, decrypt only
  token: string; // towards the gateway
}

interface Payload {
  v: number;
  g: string;
  h: string;
  d: string;
  k: string;
  n: string;
}

/** The pairing in a URL fragment (`#pair=…`), if any. Throws on a malformed one. */
export function readFragment(hash: string): (PairingInfo & { key: Uint8Array<ArrayBuffer> }) | null {
  const match = /^#?pair=([A-Za-z0-9_-]+)$/.exec(hash);
  if (!match?.[1]) return null;
  const p = JSON.parse(new TextDecoder().decode(unb64(match[1]))) as Payload;
  const key = unb64(p.k);
  const valid =
    p.v === 1 &&
    /^h_[0-9a-f]{16}$/.test(p.h) &&
    /^d_[0-9a-f]{16}$/.test(p.d) &&
    /^https?:\/\//.test(p.g) &&
    key.length === 32 &&
    typeof p.n === "string";
  if (!valid) throw new Error("this pairing code is not valid");
  return { gateway: p.g, hostId: p.h, deviceId: p.d, name: p.n, key };
}

export async function deviceFrom(info: PairingInfo & { key: Uint8Array<ArrayBuffer> }): Promise<Device> {
  const base = await importDeviceKey(info.key);
  info.key.fill(0); // only the derived keys are kept
  const { key: _, ...rest } = info;
  return {
    ...rest,
    seal: await directionKey(base, "down"),
    open: await directionKey(base, "up"),
    token: await gatewayToken(base),
  };
}

// ── storage (IndexedDB: CryptoKey objects are stored as they are, still non-extractable) ──

const DB = "handler-remote";
const STORE = "device";

function db(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error ?? new Error("IndexedDB unavailable"));
  });
}

async function tx<T>(mode: IDBTransactionMode, run: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const conn = await db();
  try {
    return await new Promise<T>((resolve, reject) => {
      const req = run(conn.transaction(STORE, mode).objectStore(STORE));
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error ?? new Error("IndexedDB error"));
    });
  } finally {
    conn.close();
  }
}

export async function loadDevice(): Promise<Device | null> {
  return ((await tx("readonly", (s) => s.get("device"))) as Device | undefined) ?? null;
}

export async function saveDevice(device: Device): Promise<void> {
  await tx("readwrite", (s) => s.put(device, "device"));
}

export async function forgetDevice(): Promise<void> {
  await tx("readwrite", (s) => s.delete("device"));
}
