import { afterEach, describe, expect, it, vi } from "vitest";
import { checkForUpdate, deployed } from "../src/lib/update";

const index = (script: string) => `<!doctype html><html><head><script type="module" crossorigin src="${script}"></script></head><body></body></html>`;

describe("a new client on the gateway", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    sessionStorage.clear();
    document.head.replaceChildren();
  });

  it("reads which script the gateway's index names, and nothing when offline", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(index("/assets/index-new.js"))));
    expect(await deployed()).toBe("/assets/index-new.js");
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("offline"))));
    expect(await deployed()).toBeNull();
  });

  it("reloads once when the gateway serves another client, not when it is the same", async () => {
    const reload = vi.fn();
    vi.stubGlobal("location", { ...location, origin: location.origin, reload });
    document.head.innerHTML = '<script type="module" src="/assets/index-old.js"></script>'; // never run

    vi.stubGlobal("fetch", vi.fn(async () => new Response(index("/assets/index-old.js"))));
    await checkForUpdate();
    expect(reload).not.toHaveBeenCalled();

    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(Date.now() + 120_000); // the next check, a while later
    vi.stubGlobal("fetch", vi.fn(async () => new Response(index("/assets/index-new.js"))));
    await checkForUpdate();
    expect(reload).toHaveBeenCalledTimes(1);
    vi.useRealTimers();
  });
});
