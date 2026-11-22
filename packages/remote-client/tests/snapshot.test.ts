// The last Home, kept for the next launch (P4): sealed under a key of its own that cannot be read,
// bound to the device it was shown for, erased with the pairing.
import { describe, expect, it } from "vitest";
import type { Store } from "../src/lib/pairing";
import { forgetSnapshot, loadSnapshot, saveSnapshot, type Home } from "../src/lib/snapshot";

function memory(): Store & { values: Map<string, unknown> } {
  const values = new Map<string, unknown>();
  return {
    values,
    get: async (key) => values.get(key),
    put: async (key, value) => void values.set(key, value),
    delete: async (key) => void values.delete(key),
  };
}

const home: Home = {
  person: "owner",
  scope: "all",
  apps: [{ name: "counter", description: "counts" } as Home["apps"][number]],
  inbox: [],
  sessions: [
    {
      id: "s1",
      title: "Fix the build",
      since: "2026-11-15T12:00:00Z",
      last: "All 42 tests pass",
      ask: { toolCallId: "t2", summary: "Read notes.md", kind: "read", risk: "safe" },
    } as Home["sessions"][number],
  ],
  agents: [],
  chats: [],
  askOptions: [],
  voice: { listens: false, readAloudSpoken: true, readAloudTyped: false },
};

describe("the last Home", () => {
  it("comes back as it was, with when the host sent it", async () => {
    const store = memory();
    await saveSnapshot("d_1", home, 1234, store);
    expect(await loadSnapshot("d_1", store)).toEqual({ home, at: 1234 });
  });

  it("is sealed: no plain text kept, under a key that cannot be read", async () => {
    const store = memory();
    await saveSnapshot("d_1", home, 1, store);
    const kept = new TextDecoder().decode((store.values.get("snapshot") as { ct: ArrayBuffer }).ct);
    expect(kept).not.toContain("Fix the build");
    expect(kept).not.toContain("All 42 tests pass"); // its last line and its ask too
    expect(kept).not.toContain("notes.md");
    const key = store.values.get("snapshot-key") as CryptoKey;
    expect(key.extractable).toBe(false);
    await expect(crypto.subtle.exportKey("raw", key)).rejects.toThrow();
  });

  it("opens only for the device it was shown for", async () => {
    const store = memory();
    await saveSnapshot("d_1", home, 1, store);
    expect(await loadSnapshot("d_2", store)).toBeNull();
  });

  it("is erased with its key", async () => {
    const store = memory();
    await saveSnapshot("d_1", home, 1, store);
    await forgetSnapshot(store);
    expect(store.values.size).toBe(0);
    expect(await loadSnapshot("d_1", store)).toBeNull();
  });
});
