// Home from the host (P2, P3): its five lists asked in one envelope and shown in one go; the tab
// the person sees is never switched under them once a screen is shown.
import { beforeEach, describe, expect, it } from "vitest";
import { app } from "../src/lib/app.svelte";
import { homeSessions, placeOf, stateOf, titleOf, unsharedAfter } from "../src/lib/home";
import type { SharedSession } from "../src/lib/remote.gen";
import type { Call, Mailbox, Settled } from "../src/lib/mailbox.svelte";

const asks = { actions: [{ app: "counter", action: "add", description: "Count one more" }] };

function host(answers: Record<string, Settled>, batches: Call[][]): Mailbox {
  return {
    hostOnline: true,
    async requestAll(calls: Call[]) {
      batches.push(calls);
      return calls.map((c) => answers[c.method] ?? { ok: true, result: {} });
    },
  } as unknown as Mailbox;
}

const owner = (withAsks: boolean): Record<string, Settled> => ({
  "_handler/remote/list_apps": { ok: true, result: { person: "owner", scope: "all", apps: [] } },
  "_handler/remote/inbox": { ok: true, result: { messages: [] } },
  "_handler/remote/list_sessions": { ok: true, result: { sessions: [{ id: "s1" }] } },
  "_handler/remote/list_agents": { ok: true, result: { projects: [], chats: [] } },
  "_handler/remote/ask_options": { ok: true, result: withAsks ? asks : { actions: [] } },
});

describe("Home", () => {
  let batches: Call[][];

  beforeEach(() => {
    batches = [];
    localStorage.clear();
    [app.homeAt, app.fresh, app.askOptions, app.sessions, app.tab, app.device] = [null, false, [], [], "ask", null];
  });

  it("is asked in one envelope and shown in one go, Ask first when nothing was shown yet", async () => {
    app.mailbox = host(owner(true), batches);
    const shown = app.refresh();
    expect(app.homeAt).toBeNull(); // nothing half-shown meanwhile
    await shown;
    expect(batches).toHaveLength(1);
    expect(batches[0]!.map((c) => c.method)).toHaveLength(5);
    expect([app.sessions.length, app.askOptions.length, app.tab, app.fresh]).toEqual([1, 1, "ask", true]);
  });

  it("stays on Home when something to ask comes after Home was shown", async () => {
    app.mailbox = host(owner(false), batches);
    await app.refresh();
    expect(app.homeAt).not.toBeNull(); // Home shown, no tabs
    app.mailbox = host(owner(true), batches);
    await app.refresh();
    expect([app.askOptions.length, app.tab]).toEqual([1, "sessions"]);
  });

  it("keeps the tab last chosen", async () => {
    app.chooseTab("inbox");
    expect(localStorage.getItem("handler-remote-tab")).toBe("inbox");
    app.mailbox = host(owner(true), batches);
    await app.refresh();
    expect([app.tab, app.screen]).toEqual(["inbox", "inbox"]);
  });

  it("does not keep Settings for the next launch", () => {
    app.chooseTab("apps");
    app.chooseTab("settings");
    expect([app.tab, localStorage.getItem("handler-remote-tab")]).toEqual(["settings", "apps"]);
  });

  it("shows the tabs this device has: Ask with something to ask, Sessions on the owner's", async () => {
    app.mailbox = host(owner(false), batches);
    await app.refresh();
    expect([app.tabs, app.screen]).toEqual([["sessions", "apps", "inbox", "settings"], "sessions"]);
    app.mailbox = host(owner(true), batches);
    await app.refresh();
    expect(app.tabs).toEqual(["ask", "sessions", "apps", "inbox", "settings"]);
  });

  it("for a device of apps only: no sessions nor Ask, the host's refusal is no error", async () => {
    app.mailbox = host(
      {
        "_handler/remote/list_apps": { ok: true, result: { person: "alice", scope: "apps", apps: [{ name: "counter" }] } },
        "_handler/remote/inbox": { ok: true, result: { messages: [] } },
        "_handler/remote/ask_options": { ok: false, error: new Error("Ask is for the owner's devices") },
      },
      batches,
    );
    await app.refresh();
    expect([app.apps.length, app.sessions.length, app.askOptions.length, app.listError]).toEqual([1, 0, 0, null]);
    expect([app.tabs, app.screen]).toEqual([["apps", "inbox", "settings"], "apps"]);
  });
});

const session = (id: string, more: Partial<SharedSession> = {}): SharedSession => ({
  id,
  origin: "ui",
  program: null,
  scope: `/home/me/code/${id}`,
  busy: false,
  pendingPermissions: 0,
  since: "2026-11-15T12:00:00Z",
  ...more,
});

describe("Home's sessions (E5)", () => {
  it("puts the shared sessions waiting for you on top, then the others, working before idle", () => {
    const list = [
      session("idle"),
      session("asks", { pendingPermissions: 2, busy: true }),
      session("works", { busy: true }),
      session("asks-too", { pendingPermissions: 1 }),
    ];
    const { needs, shared } = homeSessions(list);
    expect(needs.map((s) => s.id)).toEqual(["asks", "asks-too"]); // the host's order kept
    expect(shared.map((s) => s.id)).toEqual(["works", "idle"]);
    expect(list.map(stateOf)).toEqual(["idle", "needs", "working", "needs"]);
  });

  it("names a row by its title, then project · agent, never twice the same name", () => {
    const s = session("s", { title: "Fix the login loop", project: "shop-theme", agent: "Dev" });
    expect([titleOf(s), placeOf(s)]).toEqual(["Fix the login loop", "shop-theme · Dev"]);
    const untitled = session("u", { project: "shop-theme", agent: "Dev", label: "shop-theme · Dev" });
    expect([titleOf(untitled), placeOf(untitled)]).toEqual(["shop-theme", "Dev"]);
    const outside = session("notes", { label: "Writer" });
    expect([titleOf(outside), placeOf(outside)]).toEqual(["Writer", ""]);
    const titled = session("t", { title: "Draft the post", label: "Writer" });
    expect([titleOf(titled), placeOf(titled)]).toEqual(["Draft the post", "Writer"]);
    expect(titleOf(session("blog"))).toBe("blog"); // its folder's last part
  });

  it("keeps a trace of the sessions no longer shared, until one is shared again", () => {
    const [a, b] = [session("a", { title: "Refactor the store" }), session("b")];
    let trace = unsharedAfter([a, b], [b], [], 1000);
    expect(trace).toEqual([{ id: "a", title: "Refactor the store", at: 1000 }]);
    trace = unsharedAfter([b], [], trace, 2000);
    expect(trace.map((u) => u.id)).toEqual(["b", "a"]); // latest first
    expect(unsharedAfter([], [a], trace).map((u) => u.id)).toEqual(["b"]);
  });

  it("is told by the host: a session gone from the list leaves its trace", async () => {
    [app.sessions, app.unshared] = [[], []];
    const shared = owner(false);
    shared["_handler/remote/list_sessions"] = { ok: true, result: { sessions: [session("s1")] } };
    app.mailbox = host(shared, []);
    await app.refresh();
    expect(app.unshared).toEqual([]);
    const gone = owner(false);
    gone["_handler/remote/list_sessions"] = { ok: true, result: { sessions: [] } };
    app.mailbox = host(gone, []);
    await app.refresh();
    expect(app.unshared.map((u) => u.id)).toEqual(["s1"]);
  });
});
