// Connect from any page (E1): one Connect at a time, its opener told what was made, the pages
// listing accounts and providers told something changed; closed with nothing made, no one is.
import { describe, expect, it, vi } from "vitest";
import { connect } from "../src/lib/connect.svelte";

describe("a Connect over the page", () => {
  it("tells its opener the one made, once, and closes", () => {
    const onDone = vi.fn();
    const before = connect.changes;
    connect.open("account", onDone);
    expect(connect.current?.kind).toBe("account");
    connect.done({ kind: "account", name: "claude-perso" });
    expect(connect.current).toBeNull();
    expect(onDone).toHaveBeenCalledExactlyOnceWith({ kind: "account", name: "claude-perso" });
    expect(connect.changes).toBe(before + 1);
  });

  it("tells no one when closed with nothing made, nor an opener another Connect replaced", () => {
    const first = vi.fn();
    const second = vi.fn();
    connect.open("both", first);
    connect.close();
    expect(connect.current).toBeNull();
    connect.open("provider", first);
    connect.open("provider", second);
    connect.done({ kind: "provider", name: "openrouter" });
    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledOnce();
  });
});
