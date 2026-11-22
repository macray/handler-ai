// The last Home this device showed (what was shared with its person, the inbox, what can be
// asked), shown at once on the next launch while the host is asked again (stale while
// revalidate). Only what came in envelopes that opened is written; it is sealed with AES-GCM
// under a key of its own, made non-extractable in this browser's IndexedDB (usable here, never
// readable), bound to the device it was shown for; forgetting the device or pairing again
// erases both.
import { deviceStore, type Store } from "./pairing";
import type { ActionOption, InboxMessage, RemoteAgent, RemoteProject, SharedApp, SharedSession } from "./remote.gen";

export interface Home {
  person: string;
  scope: "all" | "apps";
  apps: SharedApp[];
  inbox: InboxMessage[];
  sessions: SharedSession[];
  agents: RemoteProject[];
  chats: RemoteAgent[];
  askOptions: ActionOption[];
  voice: { listens: boolean; readAloudSpoken: boolean; readAloudTyped: boolean };
}

interface Sealed {
  iv: Uint8Array<ArrayBuffer>;
  ct: ArrayBuffer;
  at: number; // when the host sent it (ms)
}

const KEY = "snapshot-key";
const SNAPSHOT = "snapshot";
const aad = (deviceId: string): Uint8Array<ArrayBuffer> => new TextEncoder().encode(`handler-remote/home|${deviceId}`);

async function key(store: Store): Promise<CryptoKey> {
  const kept = (await store.get(KEY)) as CryptoKey | undefined;
  if (kept) return kept;
  const made = await crypto.subtle.generateKey({ name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
  await store.put(KEY, made);
  return made;
}

export async function saveSnapshot(deviceId: string, home: Home, at: number, store: Store = deviceStore): Promise<void> {
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const plain = new TextEncoder().encode(JSON.stringify(home));
  const ct = await crypto.subtle.encrypt({ name: "AES-GCM", iv, additionalData: aad(deviceId) }, await key(store), plain);
  const sealed: Sealed = { iv, ct, at };
  await store.put(SNAPSHOT, sealed);
}

/** The last Home of this device and when it was sent; null if none, or it does not open. */
export async function loadSnapshot(deviceId: string, store: Store = deviceStore): Promise<{ home: Home; at: number } | null> {
  const sealed = (await store.get(SNAPSHOT)) as Sealed | undefined;
  const k = (await store.get(KEY)) as CryptoKey | undefined;
  if (!sealed || !k) return null;
  try {
    const plain = await crypto.subtle.decrypt({ name: "AES-GCM", iv: sealed.iv, additionalData: aad(deviceId) }, k, sealed.ct);
    return { home: JSON.parse(new TextDecoder().decode(plain)) as Home, at: sealed.at };
  } catch {
    return null; // another device's, or damaged: the host is asked anyway
  }
}

export async function forgetSnapshot(store: Store = deviceStore): Promise<void> {
  await store.delete(SNAPSHOT);
  await store.delete(KEY);
}
