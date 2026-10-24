import type { SessionUpdate } from "@agentclientprotocol/sdk";
import { describe, expect, it } from "vitest";
import { imageSrc, markdown } from "@handler/acp-view/lib/render";
import { SessionState, type ToolEntry } from "@handler/acp-view/lib/session.svelte";
import { counts, lines, rows } from "@handler/acp-view/lib/diff";
import { activity, duration, headline, relative, summary, turnSummary } from "@handler/acp-view/lib/tools";
import { websocketStream, type Closed } from "../src/lib/acp/transport";
import { dirname, resolveLink, splitFrontmatter } from "../src/lib/knowledge";
import * as access from "../src/lib/access";
import { isEgressEntry, normalizeEntry, withEntry } from "../src/lib/hosts";
import { href, parse } from "../src/lib/router.svelte";
import { readSkill, writeSkill } from "../src/lib/skillmd";
import { who } from "../src/lib/skills";
import type { Agent, AgentDefinition, AgentsFile, App, BindingInfo, HandlerNeed, Project, Session } from "../src/lib/contracts.gen";
import * as projects from "../src/lib/projects.svelte";
import { ago, appOf, dayOf, inFolder, isChat } from "../src/lib/agents";
import * as runs from "../src/lib/runs";
import * as job from "../src/lib/interface";
import * as automations from "../src/lib/automations";
import type { AutomationRun, SecretInfo } from "../src/lib/contracts.gen";
import * as secrets from "../src/lib/secrets";
import { byArea, placeDot } from "../src/lib/menu";

const text = (t: string) => ({ type: "text" as const, text: t });

describe("SessionState", () => {
  it("merges streamed chunks of the same kind", () => {
    const s = new SessionState();
    s.apply({ sessionUpdate: "agent_message_chunk", content: text("Hel") });
    s.apply({ sessionUpdate: "agent_message_chunk", content: text("lo") });
    s.apply({ sessionUpdate: "agent_thought_chunk", content: text("hmm") });
    s.apply({ sessionUpdate: "agent_message_chunk", content: text("!") });
    expect(s.entries).toEqual([
      { kind: "agent", text: "Hello" },
      { kind: "thought", text: "hmm", ms: expect.any(Number) }, // ended by the next message
      { kind: "agent", text: "!" },
    ]);
  });

  it("shows a local prompt once, even when the agent echoes it", () => {
    const s = new SessionState();
    s.addUserPrompt("hello");
    s.apply({ sessionUpdate: "session_info_update", title: "greeting" }); // before the echo
    s.apply({ sessionUpdate: "user_message_chunk", content: text("hel") });
    s.apply({ sessionUpdate: "user_message_chunk", content: text("lo") });
    s.apply({ sessionUpdate: "agent_message_chunk", content: text("hi") });
    s.inTurn = false; // the prompt's answer
    s.apply({ sessionUpdate: "user_message_chunk", content: text("replayed") }); // session/load history
    expect(s.entries).toEqual([
      { kind: "user", text: "hello", images: [] },
      { kind: "agent", text: "hi" },
      { kind: "user", text: "replayed", images: [] },
    ]);
  });

  it("keeps a prompt's images with its text", () => {
    const s = new SessionState();
    const image = { mimeType: "image/png", data: "iVBORw0KGgo=" };
    s.apply({ sessionUpdate: "user_message_chunk", content: { type: "image", ...image } }); // replayed
    s.apply({ sessionUpdate: "user_message_chunk", content: text("what is wrong here?") });
    s.apply({ sessionUpdate: "agent_message_chunk", content: text("the margin") });
    s.addUserPrompt("", [image]);
    expect(s.entries).toEqual([
      { kind: "user", text: "what is wrong here?", images: [image] },
      { kind: "agent", text: "the margin" },
      { kind: "user", text: "", images: [image] },
    ]);
  });

  it("tracks a tool call through its updates", () => {
    const s = new SessionState();
    s.apply({ sessionUpdate: "tool_call", toolCallId: "t1", title: "Read file", kind: "read", status: "pending" });
    s.apply({
      sessionUpdate: "tool_call_update",
      toolCallId: "t1",
      status: "completed",
      content: [{ type: "diff", path: "/a.txt", oldText: "a", newText: "b" }],
    });
    const tool = s.entries[0];
    expect(tool?.kind === "tool" && tool.status).toBe("completed");
    expect(tool?.kind === "tool" && tool.content[0]?.type).toBe("diff");
  });

  it("keeps modes, options, commands and title in sync", () => {
    const s = new SessionState();
    s.apply({ sessionUpdate: "current_mode_update", currentModeId: "yolo" } as SessionUpdate);
    s.apply({ sessionUpdate: "available_commands_update", availableCommands: [{ name: "init", description: "x" }] });
    s.apply({ sessionUpdate: "session_info_update", title: "Fix bug" } as SessionUpdate);
    expect([s.currentMode, s.commands[0]?.name, s.title]).toEqual(["yolo", "init", "Fix bug"]);
  });

  it("replaces the plan rather than stacking it", () => {
    const s = new SessionState();
    const entry = (status: "pending" | "completed") => ({ content: "step", priority: "high" as const, status });
    s.apply({ sessionUpdate: "plan", entries: [entry("pending")] });
    s.apply({ sessionUpdate: "plan", entries: [entry("completed")] });
    expect(s.entries).toHaveLength(1);
  });
});

describe("a tool call in one line", () => {
  const tool = (over: Partial<ToolEntry>): ToolEntry => ({
    kind: "tool", id: "t", title: "", status: "completed", content: [], locations: [], ...over,
  });
  const out = (t: string) => ({ type: "content" as const, content: text(t) });

  it("keeps a title's own verb and shows paths relative to the folder", () => {
    expect(headline(tool({ title: "Edit /w/p/src/a.py", toolKind: "edit" }), "/w/p")).toEqual({ verb: "Edit", title: "src/a.py" });
    expect(headline(tool({ title: "Write notes.md", toolKind: "edit" }))).toEqual({ verb: "Write", title: "notes.md" });
    expect(headline(tool({ title: "uv run pytest", toolKind: "execute" }))).toEqual({ verb: "Bash", title: "uv run pytest" });
    expect(relative("/w/p/a.py", "/w/p/")).toBe("a.py");
    expect(relative("/w/other/a.py", "/w/p")).toBe("/w/other/a.py");
    expect(relative("/w/pp/a.py", "/w/p")).toBe("/w/pp/a.py");
  });

  it("names the step in progress, and what a turn did", () => {
    const entries = [
      { kind: "user" as const, text: "go", images: [] },
      tool({ title: "Read /w/p/a.py", toolKind: "read" }),
      tool({ title: "Edit /w/p/a.py", toolKind: "edit", locations: [{ path: "/w/p/a.py" }] }),
      tool({ title: "uv run pytest", toolKind: "execute", status: "in_progress" }),
    ];
    expect(activity(entries, "/w/p")).toBe("Bash uv run pytest");
    expect(activity(entries.slice(0, 3))).toBeNull();
    expect(turnSummary(entries.slice(1), 72_000)).toBe("1m12s · 3 steps · 1 file changed");
    expect(turnSummary([{ kind: "agent", text: "hi" }], 3000)).toBeNull(); // no step: no footer
    expect(duration(7_380_000)).toBe("2h03m");
  });

  it("keeps the current plan and how long a turn took", () => {
    const s = new SessionState();
    s.addUserPrompt("go");
    const plan = [{ content: "a", status: "in_progress" as const, priority: "high" as const }];
    s.apply({ sessionUpdate: "plan", entries: plan });
    s.apply({ sessionUpdate: "agent_message_chunk", content: text("ok") });
    s.apply({ sessionUpdate: "plan", entries: [{ ...plan[0]!, status: "completed" }] });
    expect(s.plan[0]?.status).toBe("completed");
    s.turnTook(5000);
    expect(s.entries[0]).toMatchObject({ kind: "user", ms: 5000 });
  });

  it("says what it gave back: a failure's first line, a command's last, a diff's size", () => {
    expect(summary(tool({ status: "failed", content: [out("error: no module\nmore")] }))).toBe("error: no module");
    expect(summary(tool({ toolKind: "execute", content: [out("```\n...\n12 passed\n```")] }))).toBe("12 passed");
    expect(summary(tool({ toolKind: "read", content: [out("a\nb\nc")] }))).toBe("3 lines");
    const diff = { type: "diff" as const, path: "/a", oldText: "x\ny\n", newText: "x\nz\nw\n" };
    expect(summary(tool({ toolKind: "edit", content: [diff] }))).toBe("+2 −1");
    expect(summary(tool({ toolKind: "execute", status: "in_progress", content: [out("half")] }))).toBeNull();
  });
});

describe("a diff", () => {
  const file = (n: number) => Array.from({ length: n }, (_, i) => `line ${i + 1}`);

  it("numbers its lines and marks a changed line's words", () => {
    const all = lines("a = 1\nb = 2\n", "a = 1\nb = 3\nc = 4\n");
    expect(all.map((l) => [l.kind, l.n])).toEqual([["same", 1], ["del", 2], ["add", 2], ["add", 3]]);
    expect(all[2]!.words?.filter((w) => w.changed).map((w) => w.text)).toEqual(["3"]);
    expect(all[3]!.words).toBeUndefined(); // nothing it replaces
    expect(counts(all)).toEqual({ added: 2, removed: 1 });
    expect(lines(null, "x\n")).toEqual([{ kind: "add", n: 1, text: "x" }]); // a new file
  });

  it("folds long unchanged runs, keeping three lines around each change", () => {
    const before = file(20);
    const after = [...before];
    after[9] = "changed";
    const shown = rows(lines(before.join("\n") + "\n", after.join("\n") + "\n"));
    expect(shown.map((r) => (r.kind === "fold" ? `fold ${r.lines.length}` : r.kind))).toEqual([
      "fold 6", "same", "same", "same", "del", "add", "same", "same", "same", "fold 7",
    ]);
  });
});

describe("markdown rendering of untrusted agent output", () => {
  it("renders markdown", () => {
    expect(markdown("**bold** `code`")).toContain("<strong>bold</strong>");
    expect(markdown("[docs](https://example.org/x)")).toContain('href="https://example.org/x"');
  });

  it("shows raw HTML as text instead of interpreting it", () => {
    expect(markdown("<b>hi</b>")).toContain("&lt;b&gt;hi&lt;/b&gt;");
  });

  it("never loads remote images", () => {
    expect(markdown("![tracker](https://evil.test/p.png)")).not.toContain("<img");
  });

  // Assertions are on real markup (tags/attributes), not substrings: escaped text is harmless.
  it.each([
    ['<img src=x onerror="alert(1)">', /<img/],
    ["<script>alert(1)</script>", /<script/],
    ["[x](javascript:alert(1))", /href=/],
    ["[x](JaVaScRiPt:alert(1))", /href=/],
    ["[x](data:text/html,<script>alert(1)</script>)", /href=|<script/],
    ['<iframe src="https://evil.test"></iframe>', /<iframe/],
    ['<a href="#" style="position:fixed">x</a>', /<a\b/],
    ['<form action="https://evil.test"><input name=a></form>', /<form|<input/],
  ])("neutralizes %s", (input, forbidden) => {
    expect(markdown(input)).not.toMatch(forbidden);
  });
});

describe("images from tools (e.g. browser screenshots)", () => {
  it("shows raster images as inline data", () => {
    expect(imageSrc({ type: "image", mimeType: "image/png", data: "iVBORw0KGgo=" })).toBe(
      "data:image/png;base64,iVBORw0KGgo=",
    );
  });

  it.each([
    { type: "image", mimeType: "image/svg+xml", data: "PHN2Zz4=" }, // SVG can carry script
    { type: "image", mimeType: "text/html", data: "PGI+" },
    { type: "image", mimeType: "image/png", data: 'x" onerror="alert(1)' },
    { type: "image", mimeType: "image/png" },
    { type: "text", mimeType: "image/png", data: "iVBORw0KGgo=" },
  ])("refuses %o", (block) => {
    expect(imageSrc(block)).toBeNull();
  });
});

describe("router", () => {
  it.each([
    ["#/", { view: "home" }],
    ["", { view: "home" }],
    ["#/sessions/k1", { view: "session", key: "k1" }],
    ["#/settings", { view: "settings", section: "models" }],
    ["#/settings/areas", { view: "settings", section: "areas" }],
    ["#/addons", { view: "addons" }],
    ["#/skills", { view: "skills" }],
    ["#/skills/code-review", { view: "skill", name: "code-review" }],
    ["#/skills/new", { view: "skill", name: null }],
    ["#/skills/code-review?imported=replaced", { view: "skill", name: "code-review", imported: "replaced" }],
    ["#/skills/code-review?imported=nope", { view: "skill", name: "code-review" }],
    ["#/settings/nope", { view: "settings", section: "models" }],
    ["#/projects/p1", { view: "project", id: "p1" }],
    ["#/projects/p1?agent=a1", { view: "project", id: "p1", agent: "a1" }],
    ["#/projects/new", { view: "edit-project" }],
    ["#/projects/new?knowledge=me", { view: "edit-project", knowledge: "me" }],
    ["#/projects/p1/edit", { view: "edit-project", id: "p1" }],
    ["#/projects/p1/agents/new", { view: "edit-agent", project: "p1" }],
    ["#/projects/p1/agents/a1", { view: "edit-agent", project: "p1", id: "a1" }],
    ["#/projects/p1/agents/new?from=a1", { view: "edit-agent", project: "p1", from: "a1" }],
    ["#/knowledge", { view: "knowledge" }],
    ["#/knowledge?path=projects%2Fshop", { view: "knowledge", path: "projects/shop" }],
    ["#/knowledge?note=me%2Ftools.md", { view: "knowledge", note: "me/tools.md" }],
  ])("parses %s", (hash, route) => {
    expect(parse(hash)).toEqual(route);
  });

  it("round-trips", () => {
    expect(parse(href({ view: "knowledge", path: "a b/c&d" }))).toEqual({ view: "knowledge", path: "a b/c&d" });
    expect(parse(href({ view: "edit-project", knowledge: "projects/x" }))).toEqual({ view: "edit-project", knowledge: "projects/x" });
    expect(parse(href({ view: "edit-project", id: "p 1" }))).toEqual({ view: "edit-project", id: "p 1" });
    expect(parse(href({ view: "edit-agent", project: "p1", id: "a b" }))).toEqual({ view: "edit-agent", project: "p1", id: "a b" });
    expect(parse(href({ view: "edit-agent", project: "p1" }))).toEqual({ view: "edit-agent", project: "p1" });
    expect(parse(href({ view: "settings", section: "remote" }))).toEqual({ view: "settings", section: "remote" });
    expect(parse(href({ view: "agents" }))).toEqual({ view: "agents" });
    expect(parse(href({ view: "chat" }))).toEqual({ view: "chat" });
    expect(parse(href({ view: "chat", agent: "a 1", say: "a mail & more?" }))).toEqual({ view: "chat", agent: "a 1", say: "a mail & more?" });
    expect(parse(href({ view: "chat", new: true }))).toEqual({ view: "chat", new: true });
    expect(parse(href({ view: "agents", agent: "a 1" }))).toEqual({ view: "agents", agent: "a 1" });
    expect(parse(href({ view: "project", id: "p1", agent: "a b" }))).toEqual({ view: "project", id: "p1", agent: "a b" });
    expect(parse(href({ view: "terminal", agent: "a1", connection: "c 1" }))).toEqual({ view: "terminal", agent: "a1", connection: "c 1" });
    expect(parse(href({ view: "skill", name: "a b", imported: "new" }))).toEqual({ view: "skill", name: "a b", imported: "new" });
    expect(parse(href({ view: "agent", id: "a1" }))).toEqual({ view: "agent", id: "a1" });
    expect(parse(href({ view: "edit-ad-hoc", id: "a1" }))).toEqual({ view: "edit-ad-hoc", id: "a1" });
    expect(parse(href({ view: "set-up-helper", need: "skill-review" }))).toEqual({ view: "set-up-helper", need: "skill-review" });
    expect(href({ view: "set-up-helper", need: "skill-review" })).toBe("#/helpers/skill-review/set-up");
    expect(parse(href({ view: "setup", file: "shop-kit", project: "p1" }))).toEqual({ view: "setup", file: "shop-kit", project: "p1" });
    expect(parse(href({ view: "setup", file: "shop-kit" }))).toEqual({ view: "setup", file: "shop-kit" });
    expect(parse(href({ view: "edit-ad-hoc" }))).toEqual({ view: "edit-ad-hoc" });
    expect(parse(href({ view: "run", id: "s_1" }))).toEqual({ view: "run", id: "s_1" });
  });
});

describe("websocket transport (C.1)", () => {
  class FakeSocket extends EventTarget {
    sent: string[] = [];
    send(data: string) {
      this.sent.push(data);
    }
    close() {
      this.dispatchEvent(Object.assign(new Event("close"), { code: 1000, reason: "" }));
    }
  }

  it("sends one JSON message per frame and splits incoming NDJSON", async () => {
    const ws = new FakeSocket();
    let closed: Closed | null = null;
    const stream = websocketStream(ws as unknown as WebSocket, (c) => (closed = c));
    const writer = stream.writable.getWriter();
    await writer.write({ jsonrpc: "2.0", id: 1, method: "initialize", params: {} });
    expect(ws.sent).toEqual(['{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}']);

    const reader = stream.readable.getReader();
    ws.dispatchEvent(Object.assign(new Event("message"), { data: '{"jsonrpc":"2.0","id":1,"result":{}}\n{"jsonrpc":"2.0","method":"x"}' }));
    expect((await reader.read()).value).toMatchObject({ id: 1 });
    expect((await reader.read()).value).toMatchObject({ method: "x" });

    ws.dispatchEvent(Object.assign(new Event("close"), { code: 1011, reason: "agent exited (3)" }));
    expect(await reader.read()).toEqual({ done: true, value: undefined });
    expect(closed).toEqual({ code: 1011, reason: "agent exited (3)" });
  });
});

describe("image targets (D.4, G.4)", () => {
  it("maps harness and addon targets to their API paths", async () => {
    const { imagePath } = await import("../src/lib/api");
    expect(imagePath("vibe")).toBe("/v1/harnesses/vibe");
    expect(imagePath("addon:shopify")).toBe("/v1/addons/shopify");
    expect(imagePath("network-filter")).toBe("/v1/network-filter");
    expect(imagePath("toolbox")).toBe("/v1/toolbox");
  });
});

describe("knowledge (D.5)", () => {
  it("splits frontmatter", () => {
    expect(splitFrontmatter("---\nversion: 1\nsummary: \"Shop: theme\"\n---\n\n# shop\n")).toEqual({
      meta: [
        ["version", "1"],
        ["summary", "Shop: theme"],
      ],
      body: "# shop\n",
    });
    expect(splitFrontmatter("# no frontmatter\n")).toEqual({ meta: [], body: "# no frontmatter\n" });
    expect(splitFrontmatter("---\nsummary: only\n---")).toEqual({ meta: [["summary", "only"]], body: "" });
  });

  it("resolves links between notes inside the root", () => {
    expect(resolveLink("projects/shop", "conventions.md")).toEqual({ note: "projects/shop/conventions.md" });
    expect(resolveLink("projects/shop", "decisions/_index.md")).toEqual({ folder: "projects/shop/decisions" });
    expect(resolveLink("projects/shop", "2026%20checkout.md")).toEqual({ note: "projects/shop/2026 checkout.md" });
    expect(resolveLink("projects/shop", "../_index.md")).toEqual({ folder: "projects" });
    expect(resolveLink(".", "me/")).toEqual({ folder: "me" });
    expect(resolveLink(".", "_index.md")).toEqual({ folder: "." });
    expect(resolveLink("me", "tools.md#editors")).toEqual({ note: "me/tools.md" });
  });

  it("keeps relative links only when asked", () => {
    expect(markdown("[t](tools.md)")).not.toContain("href=");
    expect(markdown("[t](tools.md)", { relativeLinks: true })).toContain('href="tools.md"');
    expect(markdown("[t](2026%20a.md)", { relativeLinks: true })).toContain('href="2026%20a.md"');
    for (const bad of ["javascript:alert(1)", "JaVaScRiPt:x", "data:text/html,x", "//evil.example/x"]) {
      expect(markdown(`[x](${bad})`, { relativeLinks: true })).not.toContain("href=");
    }
  });

  it("leaves other links alone", () => {
    for (const href of ["https://example.org/a.md", "mailto:x@y", "#top", "/etc/passwd.md", "../../x.md", "image.png", "%E0%A4%A.md"]) {
      expect(resolveLink("me", href)).toBeNull();
    }
    expect(dirname("a/b/c.md")).toBe("a/b");
    expect(dirname("c.md")).toBe(".");
  });
});

describe("allow-list entries", () => {
  it("accepts what the daemon accepts", () => {
    for (const ok of ["example.com:443", "*.github.com:443", "a-b.co.uk:80", "192.168.1.20:11434", "h.internal:65535"])
      expect(isEgressEntry(ok)).toBe(true);
    for (const bad of ["example.com", "192.168.1.20", "*:443", "*.com:443", "Example.com:443", "a.com\n.*:443", "256.1.1.1:80",
      "http://a.com:80", "a.com:0", "a.com:65536", "a.com:", "a.com:443:1", ""])
      expect(isEgressEntry(bad)).toBe(false);
  });

  it("normalizes what is pasted", () => {
    expect(normalizeEntry("  https://API.example.com:443/v1/x ")).toBe("api.example.com:443");
    expect(normalizeEntry("example.com:3000")).toBe("example.com:3000");
    expect(normalizeEntry("https://example.com/v1")).toBe("example.com"); // no port inferred: refused
  });

  it("adds entries sorted and once", () => {
    expect(withEntry(["b.com", "a.com"], "b.com")).toEqual(["a.com", "b.com"]);
    expect(withEntry([], "c.com")).toEqual(["c.com"]);
  });
});

describe("agents", () => {
  it("knows a folder below another, not a sibling with the same prefix", () => {
    expect(inFolder("/w/app", "/w/app")).toBe(true);
    expect(inFolder("/w/app/sub", "/w/app")).toBe(true);
    expect(inFolder("/w/app2", "/w/app")).toBe(false);
  });

  const w = (id: string, extra: Partial<Agent> = {}): Agent => ({
    id,
    model: { harness: "claude-code", account: "claude-perso" },
    scope: `/home/me/code/${id}`,
    network: "open",
    confinement: "strict",
    permissions: "bypass",
    acpUrl: "",
    connections: [],
    createdAt: "2026-09-01T00:00:00Z",
    ...extra,
  });

  it("reads an agent's home", () => {
    expect([appOf(w("x", { app: "planner" })), isChat(w("x", { app: "planner" }))]).toEqual(["planner", false]);
    expect([appOf(w("x", { chat: true })), isChat(w("x", { chat: true }))]).toEqual([null, true]);
    expect([appOf(w("x")), isChat(w("x"))]).toEqual([null, false]);
  });

  it("says how long ago", () => {
    const now = Date.parse("2026-09-27T12:00:00Z");
    expect(ago("2026-09-27T11:59:30Z", now)).toBe("just now");
    expect(ago("2026-09-27T10:00:00Z", now)).toBe("2 hours ago");
    expect(ago("2026-09-26T12:00:00Z", now)).toBe("1 day ago");
    expect(ago(null, now)).toBe("never");
    expect(ago("2026-10-04T12:00:00Z", now)).toBe("in 7 days");
  });

  it("heads a timeline's days", () => {
    const now = new Date(2026, 9, 15, 9, 0); // local time, as the timeline reads it
    expect(dayOf(new Date(2026, 9, 15, 0, 5).toISOString(), now)).toBe("today");
    expect(dayOf(new Date(2026, 9, 14, 23, 50).toISOString(), now)).toBe("yesterday");
    expect(dayOf(new Date(2026, 9, 12, 12, 0).toISOString(), now)).not.toMatch(/today|yesterday/);
  });
});

describe("projects", () => {
  const agent = (id: string, extra: Partial<Agent> = {}): Agent => ({
    id,
    projectId: "p1",
    model: { harness: "claude-code", account: "claude-perso" },
    scope: "/home/me/code/shop",
    network: "open",
    confinement: "strict",
    permissions: "bypass",
    acpUrl: "",
    connections: [],
    createdAt: "2026-09-01T00:00:00Z",
    ...extra,
  });
  const project = (id: string, extra: Partial<Project> = {}): Project => ({
    id,
    name: id,
    folder: `/home/me/code/${id}`,
    pinned: true,
    agents: [agent("a1")],
    createdAt: "2026-09-01T00:00:00Z",
    ...extra,
  });

  it("edits an agent: its own values are copied", () => {
    const a = agent("a1", { name: "review", allow: ["a.test:443"], bindings: ["shop"], network: "none" });
    const spec = projects.agentSpec(a, { defaultAgent: "a1" });
    expect(spec).toMatchObject({ name: "review", allow: ["a.test:443"], bindings: ["shop"], knowledge: [], network: "none", default: true });
    expect(projects.agentBody({ ...spec, name: " Dev ", instructions: " be brief " }, { projectId: "p1" })).toMatchObject({
      projectId: "p1",
      name: "Dev",
      instructions: "be brief",
      default: true,
      confirmRisks: false,
    });
  });

  it("duplicates an agent as a copy with a free name", () => {
    const a = agent("a1", { name: "review", bindings: ["shop"], network: "none" });
    const copy = projects.duplicateAgent(a, ["review", "review-copy"]);
    expect(copy).toMatchObject({ name: "review-copy-2", bindings: ["shop"], network: "none", default: false });
    copy.bindings.push("x");
    expect(a.bindings).toEqual(["shop"]);
  });

  it("starts a new agent from the Guarded preset, a copy", () => {
    const spec = projects.emptyAgent({ harness: null, account: "codex", provider: null, model: null });
    expect(spec).toMatchObject({ network: "filtered", egress: "enforce", confinement: "strict", permissions: "bypass" });
    spec.network = "none";
    expect(projects.PRESETS[1]!.sandbox.network).toBe("filtered");
  });

  it("finds another agent set up the same but for its model: one goal, one agent", () => {
    const dev = agent("a1", { name: "dev", network: "filtered", egress: "enforce" });
    const review = agent("a2", { name: "review", network: "none" });
    const spec = projects.emptyAgent({ harness: "codex", account: "plus", provider: null, model: null });
    expect(projects.sameSetup({ ...spec, name: "codex" }, [review, dev], { defaultAgent: "a1" })?.id).toBe("a1");
    expect(projects.sameSetup({ ...spec, network: "open" }, [review, dev], { defaultAgent: "a1" })).toBeUndefined();
  });

  it("labels, orders and searches", () => {
    expect(projects.agentLabel({ name: null, model: { provider: "llamacpp", harness: "codex" } })).toBe("llamacpp");
    // one the command line made outside projects: its folder's name, not its account's
    expect(projects.agentLabel({ name: null, scope: "/home/me/code/scratch/", model: { account: "claude-perso", harness: "claude-code" } })).toBe("scratch");
    const list = [project("old"), project("used", { lastUsedAt: "2026-09-20T00:00:00Z" }), project("x")];
    expect(projects.byRecentUse(list).map((p) => p.id)).toEqual(["used", "old", "x"]);
    expect(projects.byName(list).map((p) => p.id)).toEqual(["old", "used", "x"]); // each keeps its place
    expect(projects.matches(project("shop", { description: "Liquid theme" }), "liquid claude")).toBe(true);
    expect(projects.matches(project("shop"), "vibe")).toBe(false);
  });

  it("says who uses a skill: the projects giving it, then the agents that picked it", () => {
    const list = [project("shop"), project("blog")];
    expect(who({ projects: ["shop", "blog"], usedBy: ["agents/x/review", "ad-hoc/notes"] }, list)).toBe(
      "all agents of shop, blog · picked by x/review, ad-hoc/notes",
    );
    expect(who({ usedBy: ["agents/blog/dev"] }, list)).toBe("picked by blog/dev");
    expect(who({}, list)).toBe("");
  });

  it("puts a picker's choices used in the project first, saying where the others are used", () => {
    const list = [project("shop"), project("blog"), project("shop-2")];
    const choices = [
      { name: "a" },
      { name: "b", usedBy: ["agents/blog/dev", "ad-hoc/x"] },
      { name: "c", projects: ["shop"], usedBy: ["agents/shop-2/dev"] },
      { name: "d", usedBy: ["agents/shop/review"] },
    ];
    const rows = projects.byUse(list, choices, "shop").map((r) => [r.choice.name, r.note]);
    expect(rows).toEqual([["c", "used in shop-2"], ["d", ""], ["a", ""], ["b", "used in blog"]]);
    expect(projects.byUse(list, choices).map((r) => r.note)).toEqual(["", "used in blog", "used in shop, shop-2", "used in shop"]);
  });
});

describe("model access", () => {
  it("labels what runs and sends a provider's harness only", () => {
    expect(access.accessLabel({ harness: "codex", account: null, provider: "llamacpp", model: "qwen" })).toBe("codex · provider llamacpp · qwen");
    expect(access.accessLabel({ harness: "claude-code", account: "pro", provider: null, model: null })).toBe("claude-code · account pro");
    expect(access.chosen({ harness: null, account: null, provider: "llamacpp", model: null })).toBe(false);
    const pro = { harness: "claude-code", account: "pro", provider: null, model: null };
    const local = { harness: "codex", account: null, provider: "llamacpp", model: "qwen" };
    expect(projects.agentBody(projects.emptyAgent(pro), {}).model).toEqual({ account: "pro", harness: null, provider: null, model: null });
    expect(projects.agentBody(projects.emptyAgent(local), {}).model).toEqual({ provider: "llamacpp", harness: "codex", account: null, model: "qwen" });
    expect(access.sameModel(pro, { harness: null, account: "pro", provider: null, model: null })).toBe(true);
    expect(access.sameModel(pro, { ...pro, model: "opus" })).toBe(false);
    expect(access.sameRun(access.accessOf({ harness: "codex", provider: "a" }), { harness: "codex", account: null, provider: "a", model: "m" })).toBe(true);
  });
});

describe("SKILL.md in the skill editor", () => {
  it("reads name and description as fields and keeps the rest as written", () => {
    const text =
      "---\nname: pdf\ndescription: >\n  Fill PDF forms.\n  Use for PDFs.\nlicense: MIT\nmetadata:\n  version: 2\n---\n\n# PDF\n\nSteps.\n";
    const doc = readSkill(text);
    expect(doc).toEqual({ name: "pdf", description: "Fill PDF forms. Use for PDFs.", other: "license: MIT\nmetadata:\n  version: 2", body: "# PDF\n\nSteps.\n" });
    expect(readSkill(writeSkill(doc))).toEqual(doc);
  });

  it("quotes a description YAML would misread", () => {
    for (const description of ["Review: diffs and style", "- a list?", "it's #1", "plain words, no trouble"]) {
      const doc = { name: "x", description, other: "", body: "B\n" };
      expect(readSkill(writeSkill(doc)).description).toBe(description);
    }
    expect(readSkill('---\nname: x\ndescription: "a \\"quoted\\" one"\n---\nB').description).toBe('a "quoted" one');
    expect(readSkill("no frontmatter")).toEqual({ name: "", description: "", other: "", body: "no frontmatter" });
  });
});

describe("a job, as the agent editor shows it (D.18)", () => {
  it("names how a saved agent is used, as everywhere", () => {
    expect(job.useOfAgent({})).toBe("chat");
    expect(job.useOfAgent({ interface: { fields: { type: "object" } } })).toBe("brief");
    expect(job.useOfAgent({ interface: { fields: { type: "object" }, result: { type: "object" } } })).toBe("job");
    expect(job.USE_LABEL.job).toBe("Job");
  });

  it("writes the schemas: status and summary first, keys from the labels", () => {
    const j = job.newJob();
    expect(j.fields).toEqual([]); // the person names the form's fields
    j.fields.push({ ...job.newField("long-text"), title: "Request" });
    j.fields.push({ ...job.newField("choice"), title: "Level", choices: "low, high", required: false });
    j.result.push({
      ...job.newField("items"),
      title: "Invoices",
      items: [
        { ...job.newField("text"), title: "Supplier" },
        { ...job.newField("number"), title: "Due date", required: false },
      ],
    });
    j.result.push({ ...job.newField("list"), title: "Notes", required: false });
    expect(job.interfaceOf(j)).toEqual({
      fields: {
        type: "object",
        properties: {
          request: { type: "string", title: "Request", "x-handler": "long-text" },
          level: { enum: ["low", "high"], title: "Level" },
        },
        required: ["request"],
      },
      result: {
        type: "object",
        properties: {
          status: job.STATUS,
          summary: job.SUMMARY,
          invoices: {
            type: "array",
            title: "Invoices",
            items: {
              type: "object",
              properties: { supplier: { type: "string", title: "Supplier" }, dueDate: { type: "number", title: "Due date" } },
              required: ["supplier"],
            },
          },
          notes: { type: "array", items: { type: "string" }, title: "Notes" },
        },
        required: ["status", "summary", "invoices"],
      },
      timeoutSec: 1800,
    });
  });

  it("reads back what it wrote, keeping saved keys", () => {
    const j = job.newJob();
    j.result.push({ ...job.newField("yes-no"), title: "Paid" });
    const iface = job.interfaceOf(j);
    const back = job.jobOf(iface)!;
    expect(back.result.map((f) => [f.key, f.saved, f.type])).toEqual([["paid", true, "yes-no"]]);
    back.result[0]!.title = "Already paid";
    expect(Object.keys((job.interfaceOf(back).result!.properties as object) ?? {})).toEqual(["status", "summary", "paid"]);
    expect(job.jobOf({ ...iface, fields: null })?.fields).toEqual([]);
    const fresh = job.unsaved(job.jobOf(job.interfaceOf({ ...job.newJob(), fields: [{ ...job.newField(), title: "Request" }] }))!);
    fresh.fields[0]!.title = "Invoice text"; // a new agent: keys follow labels
    expect(Object.keys(job.interfaceOf(fresh).fields!.properties as object)).toEqual(["invoiceText"]);
  });

  it("writes a skill field as a string marked skill, a field like the others", () => {
    const j = job.newJob();
    j.fields.push({ ...job.newField(), title: "Focus" }, { ...job.newField("skill"), title: "Skill to review", required: false });
    const iface = job.interfaceOf(j);
    expect(iface.fields).toEqual({
      type: "object",
      properties: { focus: { type: "string", title: "Focus" }, skillToReview: { type: "string", title: "Skill to review", "x-handler": "skill" } },
      required: ["focus"],
    });
    expect(job.jobOf(iface)!.fields.map((f) => f.type)).toEqual(["text", "skill"]);
    expect(runs.skillField(iface)).toBe("skillToReview");
    expect(runs.fieldsOf(iface.fields as runs.Schema).map((f) => f.kind)).toEqual(["text", "skill"]);
  });

  it("leaves to JSON what it cannot show as it is", () => {
    const base = job.interfaceOf(job.newJob());
    const withResult = (extra: Record<string, unknown>) => ({
      ...base,
      result: { ...base.result, properties: { ...(base.result!.properties as object), ...extra } },
    });
    expect(job.jobOf(withResult({ n: { type: "integer" } }))).toBeNull();
    expect(job.jobOf(withResult({ where: { "x-handler": "code-ref", type: "object" } }))).toBeNull();
    expect(job.jobOf(withResult({ s: { type: "string", minLength: 3 } }))).toBeNull();
    expect(job.jobOf({ result: { type: "object", properties: { verdict: { enum: ["a"] } } } })).toBeNull(); // no status
    expect(job.jobOf(withResult({ s: { type: "string" } }))?.result[0]?.type).toBe("text");
  });

  it("writes a brief as its form alone, and switches between brief and job", () => {
    const brief = job.interfaceOf(job.newBrief(), true);
    expect(brief).toEqual({
      fields: { type: "object", properties: { whatShouldItDo: { type: "string", title: "What should it do?", "x-handler": "long-text" } }, required: ["whatShouldItDo"] },
    });
    expect(job.jobOf(brief)?.fields.map((f) => f.title)).toEqual(["What should it do?"]);
    expect([job.useOf(""), job.useOf(JSON.stringify(brief)), job.useOf(JSON.stringify(job.interfaceOf(job.newJob())))]).toEqual(["chat", "brief", "job"]);
    expect(job.useOf('{"result": {')).toBe("job"); // being typed
    const asJob = JSON.parse(job.switchedTo("job", JSON.stringify(brief)));
    expect(asJob.fields).toEqual(brief.fields);
    expect(Object.keys(asJob.result.properties)).toEqual(["status", "summary"]);
    expect(JSON.parse(job.switchedTo("brief", JSON.stringify(asJob)))).toEqual(brief);
    // a job without a form becomes a brief with one
    expect(JSON.parse(job.switchedTo("brief", JSON.stringify(job.interfaceOf(job.newJob()))))).toEqual(brief);
  });

  it("finds the fields its instructions name, and follows a key that changes", () => {
    expect(job.placeholders("For {{audience}}, {{ audience }} and {{tags}}; {not} {{}}")).toEqual(["audience", "tags"]);
    expect(job.renamed("For {{audience}} and {{ audience }}, not {{audiences}}", "audience", "readers")).toBe("For {{readers}} and {{readers}}, not {{audiences}}");
    const parts = job.textParts("To {{client}}: {{ clinet }}.", ["client"]);
    expect(parts.map((p) => p.kind)).toEqual(["text", "field", "text", "unknown", "text"]);
    expect(parts.map((p) => p.text).join("")).toBe("To {{client}}: {{ clinet }}.");
    expect(parts[3]!.key).toBe("clinet");
  });

  it("makes keys and made-up values", () => {
    expect(job.keyOf("Due date")).toBe("dueDate");
    expect(job.keyOf("  ")).toBe("field");
    expect(job.keyOf("2nd try")).toBe("field2ndTry");
    const result = job.interfaceOf({ ...job.newJob(), result: [{ ...job.newField("number"), title: "Count" }, { ...job.newField(), title: "Owner" }] }).result;
    expect(job.sampleOf(result!)).toEqual({ status: "ok", summary: "What it did, in a sentence or two.", count: 3, owner: "Sample text" });
    const form = [
      { key: "level", title: "Level", kind: "choice", choices: ["low", "high"], required: true },
      { key: "done", title: "Done", kind: "boolean", choices: [], required: false },
    ] as const;
    expect(job.sampleInput(form.map((f) => ({ ...f, choices: [...f.choices] })))).toEqual({ level: "low", done: true });
  });
});

describe("runs (D.18)", () => {
  const result = {
    type: "object",
    properties: {
      verdict: { enum: ["no-concerns", "caution", "do-not-install"], "x-handler": "verdict" },
      summary: { type: "string", title: "What it does" },
    },
  };

  it("makes a form from the interface's fields", () => {
    const fields = runs.fieldsOf({
      type: "object",
      properties: {
        expectation: { type: "string", title: "What you expect" },
        count: { type: "integer" },
        strict: { type: "boolean" },
        level: { enum: ["low", "high"] },
        extra: { type: "object" },
      },
      required: ["count"],
    });
    expect(fields.map((f) => [f.key, f.title, f.kind, f.required])).toEqual([
      ["expectation", "What you expect", "text", false],
      ["count", "Count", "number", true],
      ["strict", "Strict", "boolean", false],
      ["level", "Level", "choice", false],
      ["extra", "Extra", "json", false],
    ]);
    expect(runs.fieldValues(fields, { expectation: "", count: "3", extra: '{"a": 1}', level: "low" })).toEqual({
      count: 3,
      extra: { a: 1 },
      level: "low",
    });
    expect(() => runs.fieldValues(fields, { extra: "{" })).toThrow("Extra: not JSON");
    const more = runs.fieldsOf({
      type: "object",
      properties: { brief: { type: "string", "x-handler": "long-text" }, tags: { type: "array", items: { type: "string" } } },
    });
    expect(more.map((f) => f.kind)).toEqual(["long-text", "list"]);
    expect(runs.fieldValues(more, { tags: " a \n\nb " })).toEqual({ tags: ["a", "b"] });
    expect(runs.formValues(more, { tags: ["a", "b"] })).toEqual({ tags: "a\nb" });
  });

  it("finds the verdict and its tone", () => {
    expect(runs.verdictOf(result, { verdict: "caution", summary: "x" })).toEqual({ value: "caution", tone: "warn" });
    expect(runs.verdictOf(result, { verdict: "no-concerns" })?.tone).toBe("ok");
    expect(runs.verdictOf(result, { verdict: "do-not-install" })?.tone).toBe("danger");
    expect(runs.verdictOf({ type: "object", properties: { summary: { type: "string" } } }, { summary: "x" })).toBeNull();
    expect(runs.titleOf("whenUsed", {})).toBe("When used");
  });

  it("reads code references", () => {
    expect(runs.codeRef({ path: "scripts/a.sh", lines: [3, 5] })).toEqual({ path: "scripts/a.sh", from: 3, to: 5 });
    expect(runs.codeRef({ path: "a", lines: [5, 3] })).toBeNull();
    expect(runs.codeRef({ path: "a", lines: [0, 1] })).toBeNull();
    expect(runs.codeRef("a:1")).toBeNull();
  });

  it("tells how a run is doing", () => {
    const base = { id: "s", agentId: "a", harness: "h", scope: "/x", createdAt: "", lastActivityAt: "", acpUrl: "" } as Session;
    expect(runs.runState({ ...base, state: "running" })).toBe("running");
    expect(runs.runState({ ...base, state: "stopped", output: { valid: true, value: {} } })).toBe("done");
    expect(runs.runState({ ...base, state: "stopped", output: { valid: false, error: "x" } })).toBe("invalid");
    expect(runs.runState({ ...base, state: "stopped" })).toBe("no result");
  });

  it("fills an agent's form with its definition's defaults (a blueprint's agent, an app's)", () => {
    const spec = runs.definitionSpec({
      agentName: "Skill reviewer",
      permissions: "ask",
      network: "filtered",
      egress: "enforce",
      skills: [],
      knowledge: ["recipes"],
      display: true,
      interface: { result, fields: { type: "object", properties: { skill: { type: "string", "x-handler": "skill" } } } },
    });
    expect(spec.name).toBe("Skill reviewer");
    expect([spec.knowledge, spec.display]).toEqual([["recipes"], true]);
    expect([spec.permissions, spec.egress, spec.network]).toEqual(["ask", "enforce", "filtered"]);
    expect(runs.skillField(JSON.parse(spec.interface))).toBe("skill");
    expect(spec.model.account).toBeNull();
  });

  it("builds the body of an agent of no project, folderless or not", () => {
    const empty = projects.emptyAgent({ harness: null, account: "a", provider: null, model: null });
    const spec = { ...empty, interface: '{"result": {}}', default: true, remoteStart: true };
    const body = projects.agentBody(spec, { scope: null });
    expect(body.scope).toBeNull();
    expect(body.name).toBeNull(); // optional outside projects
    expect(body.interface).toEqual({ result: {} });
    expect([body.default, body.remoteStart]).toEqual([false, false]); // a project's only
    expect(body.confirmRisks).toBe(false); // what it widens is confirmed, as in projects (D.8)
    expect(projects.agentBody(spec, { chat: true }, true).confirmRisks).toBe(true);
    expect(() => projects.agentBody({ ...spec, interface: "{" }, { scope: "/x" })).toThrow("Interface: not JSON");
  });
});

describe("automations (I)", () => {
  it("makes a schedule from its form, and says what is wrong with one", () => {
    expect(automations.scheduleOf({ kind: "every", n: 30, unit: "m" })).toEqual({ every: "30m" });
    expect(automations.scheduleOf({ kind: "at", at: "08:30", days: [...automations.DAYS] })).toEqual({ at: "08:30" });
    expect(automations.scheduleOf({ kind: "at", at: "08:30", days: ["fri", "mon"] })).toEqual({ at: "08:30", days: ["mon", "fri"] });
    expect(automations.scheduleProblem({ kind: "every", n: 4, unit: "m" })).toBe("At least every 5 minutes.");
    expect(automations.scheduleProblem({ kind: "every", n: 4, unit: "h" })).toBeNull();
    expect(automations.scheduleProblem({ kind: "at", at: "8:30", days: ["mon"] })).toBe("Give a time, like 08:30.");
    expect(automations.scheduleProblem({ kind: "at", at: "08:30", days: [] })).toBe("Choose at least one day.");
  });

  it("says how often a schedule runs", () => {
    expect(automations.howOften({ kind: "every", n: 1, unit: "h" })).toBe("24 runs a day");
    expect(automations.howOften({ kind: "every", n: 7, unit: "h" })).toBe("about 3 runs a day");
    expect(automations.howOften({ kind: "every", n: 48, unit: "h" })).toBe("about 4 runs a week");
    expect(automations.howOften({ kind: "every", n: 9999, unit: "h" })).toBe("less than one run a week");
    expect(automations.howOften({ kind: "at", at: "08:30", days: ["mon"] })).toBe("1 run a week");
  });

  it("suggests a name from what runs and when", () => {
    expect(automations.suggestName("Code review", { kind: "every", n: 1, unit: "h" })).toBe("code-review-hourly");
    expect(automations.suggestName("Dev", { kind: "at", at: "08:30", days: [...automations.WEEKDAYS] })).toBe("dev-weekdays");
    expect(automations.suggestName("Dev", { kind: "at", at: "09:00", days: ["mon"] })).toBe("dev-mon");
    expect(automations.suggestName("", null)).toBe("automation-on-stop");
  });

  it("checks an agent's result as an automation needs it (I.3)", () => {
    const ok = {
      type: "object",
      required: ["status", "summary"],
      properties: { status: { enum: ["ok", "attention", "failed"] }, summary: { type: "string" } },
    };
    expect(automations.resultProblems(ok)).toEqual([]);
    expect(automations.resultProblems({ properties: { answer: { type: "string" } } })).toHaveLength(2);
    expect(automations.resultProblems({ ...ok, properties: { ...ok.properties, status: { enum: ["done"] } } })).toEqual([
      "a status of only ok, attention, failed",
    ]);
  });

  it("reads a definition back into its form, when the form can say it", () => {
    const base = { apiVersion: "handler.automation/v1" } as const;
    const agentRun = { agent: "Review", project: "shop", input: { fields: { focus: "security" } } };
    const daily = automations.formOf({ ...base, description: "d", when: { at: "07:00", days: ["fri", "mon"] }, run: agentRun, app: "planner" });
    expect(daily).toMatchObject({
      on: "time",
      schedule: { kind: "at", at: "07:00", days: ["mon", "fri"] },
      what: "agent",
      agent: { name: "Review", project: "shop", fields: { focus: "security" } },
      opens: "planner",
      description: "d",
    });
    expect(automations.formOf({ ...base, when: { every: "30m" }, run: agentRun })?.schedule).toEqual({ kind: "every", n: 30, unit: "m" });
    const app = automations.formOf({ ...base, when: "session.stopped", only: { project: ["shop"] }, run: { app: "coach", call: "POST /api/x" } });
    expect(app).toMatchObject({ on: "stop", stopProject: "shop", what: "app", app: "coach", call: "POST /api/x", agent: null, opens: "" });
    expect(automations.formOf({ ...base, when: "session.stopped", run: "python3 x.py" })).toBeNull();
    expect(automations.formOf({ ...base, when: "session.stopped", only: { agent: ["dev"] }, run: agentRun })).toBeNull();
  });

  it("lists the automations that are on and run an agent, by id", () => {
    const list = [
      { name: "a", enabled: true, agentId: "r1" },
      { name: "b", enabled: false, agentId: "r1" },
      { name: "c", enabled: true, agentId: "r2" },
      { name: "d", enabled: true, agentId: null },
    ];
    expect(automations.schedulesOf(list, "r1").map((a) => a.name)).toEqual(["a"]);
    expect(automations.runsAgent({ agentId: "r1" }, "r1")).toBe(true);
    expect(automations.runsAgent({ agentId: null }, "r1")).toBe(false);
  });

  it("says when it runs and what", () => {
    const base = { apiVersion: "handler.automation/v1", run: "python3 extract.py" } as const;
    expect(automations.whenSentence({ ...base, when: "session.stopped" })).toBe("When any session stops");
    expect(automations.whenSentence({ ...base, when: "session.stopped", only: { project: ["shop"], agent: ["dev", "ops"] } })).toBe(
      "When a session of project shop and of agent dev, ops stops",
    );
    expect(automations.whenSentence({ ...base, when: { every: "1h" } })).toBe("Every 1h");
    expect(automations.whenSentence({ ...base, when: { at: "08:30", days: ["mon", "fri"] } })).toBe("At 08:30 on mon, fri");
    expect(automations.onSchedule({ ...base, when: { every: "1h" } })).toBe(true);
    expect(automations.runSentence({ ...base, when: "session.stopped" })).toBe("runs a script");
    expect(automations.runSentence({ ...base, when: { every: "1h" }, run: { agent: "reviewer", project: "handler" } })).toBe(
      "runs the agent reviewer of handler",
    );
    expect(automations.runSentence({ ...base, when: { every: "1h" }, run: { app: "coach", call: "POST /api/x" } })).toBe(
      "calls POST /api/x of the app coach",
    );
  });

  it("says the slots a run missed", () => {
    const run = { state: "succeeded", missed: 3 } as AutomationRun;
    expect(automations.missedSentence(run)).toBe("3 slots missed before it (Handler was not running): only the latest runs");
    expect(automations.missedSentence({ ...run, missed: 0 })).toBe("");
  });

  it("sums a run's model use", () => {
    const run = { state: "succeeded", llm: { calls: 2, inTokens: 1000, outTokens: 200 } } as AutomationRun;
    expect(automations.usage(run)).toBe(`2 calls · ${(1200).toLocaleString()} tokens`);
    expect(automations.usage({ ...run, llm: { calls: 0 } })).toBe("");
    expect(automations.ended(run)).toBe(true);
    expect(automations.ended({ ...run, state: "queued" })).toBe(false);
  });

  it("has its routes", () => {
    expect(parse("#/automations")).toEqual({ view: "automations" });
    expect(parse("#/automations/env-issues")).toEqual({ view: "automation", name: "env-issues" });
    expect(parse("#/inbox")).toEqual({ view: "inbox" });
    expect(href({ view: "automation", name: "env-issues" })).toBe("#/automations/env-issues");
    expect(parse("#/automations/new?agent=ag_1")).toEqual({ view: "edit-automation", agent: "ag_1" });
    expect(href({ view: "edit-automation", agent: "ag_1" })).toBe("#/automations/new?agent=ag_1");
    expect(href({ view: "edit-automation" })).toBe("#/automations/new");
    expect(parse("#/automations/review/edit")).toEqual({ view: "edit-automation", name: "review" });
    expect(href({ view: "edit-automation", name: "review" })).toBe("#/automations/review/edit");
  });
});

describe("secrets", () => {
  const info = (over: Partial<SecretInfo>): SecretInfo => ({ path: "providers/openrouter/apiKey", ...over }) as SecretInfo;

  it("groups a secret by what it belongs to, and names it there", () => {
    expect(secrets.group(info({ usedBy: ["providers/openrouter"] }))).toBe("providers");
    expect(secrets.group(info({ path: "spare/one", usedBy: [] }))).toBe("unused");
    expect(secrets.slot(info({ usedBy: ["providers/openrouter"] }))).toBe("openrouter · key");
    expect(secrets.slot(info({ path: "bindings/shop/theme_token", usedBy: ["bindings/shop"] }))).toBe("shop · theme_token");
    expect(secrets.slot(info({ path: "spare/one", usedBy: [] }))).toBe("spare/one");
    expect(secrets.ownerHref("accounts/perso")).toBe("#/settings/models");
  });

  it("says where its value is", () => {
    expect(secrets.source(info({ source: "env", hasValue: false }))).toBe("from an environment variable of Handler: not set");
    expect(secrets.source(info({}))).toBe("kept by Handler");
  });

  it("forgets only unused stored values", () => {
    expect(secrets.removable(info({ usedBy: [], createdAt: "2026-10-08T00:00:00Z" }))).toBe(true);
    expect(secrets.removable(info({ usedBy: ["providers/openrouter"], createdAt: "2026-10-08T00:00:00Z" }))).toBe(false);
    expect(secrets.removable(info({ source: "env", usedBy: [] }))).toBe(false);
  });
});

describe("apps (H)", () => {
  it("says what an installed app may reach", async () => {
    const { reaches } = await import("../src/lib/apps");
    const app = {
      files: [{ name: "tasks", mode: "rw", path: "/home/me/planner" }],
      agents: [
        { name: "planner", origin: { kind: "app", name: "planner", agent: "planner" }, agentId: "a1" },
        { name: "notes", origin: { kind: "app", name: "planner", agent: "notes" } },
      ],
    } as App;
    const label = (id: string): string => (id === "a1" ? "Planner (project home)" : id);
    expect(reaches({}, app, label)).toEqual(["Reaches no host: no network."]);
    expect(
      reaches(
        {
          egress: ["api.example.com:443"],
          files: { tasks: { mode: "rw" }, archive: {} },
          notify: true,
          agents: { planner: { from: "agent" }, notes: { from: "notes" } },
        },
        app,
        label,
      ),
    ).toEqual([
      "Reaches api.example.com:443.",
      "Reads and writes /home/me/planner.",
      "Reads the folder you give for archive.",
      "Sends you notifications (your inbox, desktop and phones).",
      "Runs your agent Planner (project home) when you use it, and reads its results.",
      "Runs the agent you give for notes when you use it, and reads its results.",
    ]);
  });

  it("says what deleting an agent stops", async () => {
    const { stopsWhenDeleted } = await import("../src/lib/apps");
    const app = { kind: "app", id: "planner", label: "planner", how: "needs it: Tells you what to do next" } as const;
    const handler = { kind: "handler", id: "skill-review", label: "Handler", how: "its skill reviewer" } as const;
    const automation = { kind: "automation", id: "every-5h", label: "every-5h", how: "runs it" } as const;
    expect(stopsWhenDeleted([])).toBe("");
    expect(stopsWhenDeleted([app])).toBe(" It is used by the app planner: it stops until you give it another agent.");
    expect(stopsWhenDeleted([handler, app])).toBe(
      " It is used by Handler (its skill reviewer) and the app planner: they stop until you give them another agent.",
    );
    expect(stopsWhenDeleted([app, automation])).toBe(
      " It is used by the app planner and the automation every-5h: they stop until you give them another agent.",
    );
  });

  it("reads what an agent was set up from", async () => {
    const { setUpFrom } = await import("../src/lib/agents");
    const { fileOrigin, needOrigin } = await import("../src/lib/setup");
    expect(setUpFrom({ kind: "agents-file", name: "tone-shop", version: 2, agent: "judge" })).toBe("tone-shop");
    expect(setUpFrom({ kind: "handler-need", name: "skill-review", version: 1 })).toBe("skill-review");
    expect(setUpFrom({ kind: "app", name: "planner", agent: "planner" })).toBeNull();
    expect(setUpFrom(null)).toBeNull();
    expect(fileOrigin({ name: "tone-shop", version: 3 }, "judge")).toEqual({ kind: "agents-file", name: "tone-shop", version: 3, agent: "judge" });
    expect(needOrigin({ name: "skill-review", version: 2 })).toEqual({ kind: "handler-need", name: "skill-review", version: 2 });
  });

  it("says what Handler or an app uses an agent for", async () => {
    const { usedFor } = await import("../src/lib/apps");
    const apps = [
      { name: "planner", agents: [{ name: "planner", origin: { kind: "app", name: "planner", agent: "planner" }, agentId: "a1" }] },
    ] as App[];
    const needs = [
      { name: "skill-review", version: 1, definition: { agentName: "Skill reviewer" }, description: "", agentId: "a1" },
      { name: "app-creator", version: 1, definition: { agentName: "App creator" }, description: "" },
    ] as HandlerNeed[];
    const of = (id: string, extra: Partial<Agent> = {}) => usedFor({ id, model: {}, ...extra } as unknown as Agent, needs, apps);
    expect(of("a1")).toEqual([
      { label: "Skill reviewer", app: false },
      { label: "planner", app: true },
    ]);
    expect(of("a2", { origin: { kind: "handler-need", name: "app-creator", version: 1 } })).toEqual([]); // set up from it, not given
    expect(of("a4")).toEqual([]);
  });

  it("says what it needs that was not given", async () => {
    const { missing } = await import("../src/lib/apps");
    const app = {
      files: [{ name: "tasks", mode: "rw" }],
      agents: [
        { name: "planner", origin: { kind: "app", name: "planner", agent: "planner" }, agentId: "a1", problem: "the agent given was deleted" },
        { name: "fine", origin: { kind: "app", name: "planner", agent: "fine" }, agentId: "a2" },
      ],
      secrets: [{ name: "KEY", set: false }],
    } as App;
    expect(missing(app)).toEqual(["the folder tasks", "the agent planner", "the secret KEY"]);
  });

  it("says who started a run", () => {
    const run = { origin: "app", app: "planner" } as Session;
    expect(runs.startedBy(run)).toBe("by the app planner");
    expect(runs.startedBy({ ...run, origin: "automation" })).toBe("by an automation");
    expect(runs.startedBy({ ...run, origin: "ui" })).toBe("by you");
  });
});

describe("agents set up from definitions (D.23, D.18)", () => {
  const def = { agentName: "Order triage", addons: ["shopify"], knowledge: ["shop/policies"], skills: ["tidy"], network: "filtered", permissions: "bypass" } as AgentDefinition;
  const file = { name: "shop-kit", version: 3, place: "project", agents: [{ part: "order-triage", definition: def, checks: [] }, { part: "dev", definition: { agentName: "Dev" }, checks: [] }] } as unknown as AgentsFile;

  it("names an agent in an agents file as handlerd does", async () => {
    const { slug, freeName } = await import("../src/lib/setup");
    expect(slug("Order triage")).toBe("order-triage");
    expect(slug("  Été ")).toBe("t");
    expect(slug("!!")).toBe("agent");
    expect(freeName("Skill reviewer", ["skill reviewer", "Skill reviewer 2"])).toBe("Skill reviewer 3");
    expect(freeName("Dev", [])).toBe("Dev");
  });

  it("asks only what an agent needs, and builds its request from the choice", async () => {
    const { fileOrigin, firstChoice, missing, needsOf, projectAgentBody, outsideAgentBody } = await import("../src/lib/setup");
    expect(needsOf(def)).toEqual(["its model", "a configuration of shopify", "a knowledge folder: shop/policies"]);
    const bindings = [{ name: "broken", addon: "shopify", error: "x" }, { name: "shop-main", addon: "shopify" }] as BindingInfo[];
    const c = firstChoice(def, bindings, ["shop/policies"]);
    expect(c.bindings).toEqual({ shopify: "shop-main" });
    expect(c.knowledge).toEqual({ "shop/policies": "shop/policies" });
    expect(missing(def, c)).toEqual(["its model"]);
    expect(missing(def, firstChoice(def, [], []))).toEqual(["its model", "a configuration of shopify", "a knowledge folder for shop/policies"]);
    c.model = { harness: null, account: "work", provider: null, model: null };
    expect(missing(def, c)).toEqual([]);
    const origin = fileOrigin(file, "order-triage");
    const body = projectAgentBody(origin, file.agents[0]!.definition, c);
    expect([body.origin, body.name, body.bindings, body.knowledge, body.skills, body.confirmRisks]).toEqual([
      { kind: "agents-file", name: "shop-kit", version: 3, agent: "order-triage" },
      "Order triage",
      ["shop-main"],
      ["shop/policies"],
      ["tidy"],
      true,
    ]);
    expect(body.model.account).toBe("work");
    const outside = outsideAgentBody(origin, file.agents[0]!.definition, c, null);
    expect([outside.scope, outside.origin]).toEqual([null, { kind: "agents-file", name: "shop-kit", version: 3, agent: "order-triage" }]);
  });

  it("says what an agent may do", async () => {
    const { mayDo } = await import("../src/lib/setup");
    expect(mayDo(def, "/home/me/shop")).toEqual(["read and write /home/me/shop", "reach its model, its addons' hosts", "never asks before acting"]);
    expect(mayDo({ ...def, modelAlone: true }, null)).toEqual(["nothing outside its call; its knowledge is sent to its provider"]);
    expect(mayDo({ agentName: "x", network: "none", permissions: "ask", display: true } as AgentDefinition, null)).toEqual([
      "a new folder each session",
      "no network",
      "asks before it acts",
      "use your screen and clipboard",
    ]);
  });
});

describe("installing an app (H.2)", () => {
  it("finds the folder it keeps its data in, and names its suggestions", async () => {
    const { dataNeed, suggested } = await import("../src/lib/apps");
    const files = [
      { name: "inbox", mode: "ro" },
      { name: "tasks", mode: "rw" },
    ] as App["files"];
    expect(dataNeed({ files, agents: [] })?.name).toBe("tasks"); // its only read-write one
    expect(dataNeed({ files, agents: [{ name: "a", worksIn: "inbox", origin: { kind: "app", name: "x", agent: "a" } }] as App["agents"] })?.name).toBe("inbox"); // where its agents work
    expect(dataNeed({ files: [...files!, { name: "out", mode: "rw" }] as App["files"], agents: [] })).toBeUndefined();
    const s = { description: "What to do next!", when: { every: "5h" }, run: { agent: "planner" } };
    const made = suggested({ name: "planner" }, s);
    expect(made.name).toBe("planner-what-to-do-next");
    expect(made.definition).toMatchObject({ app: "planner", run: { agent: "planner" }, when: { every: "5h" } });
  });

  it("opens its install page", () => {
    expect(parse(href({ view: "install-app", name: "planner" }))).toEqual({ view: "install-app", name: "planner" });
  });
});

describe("menu", () => {
  it("shows a place's most urgent session, nothing when none runs", () => {
    expect(placeDot([]).status).toBeNull();
    expect(placeDot(["stopped", "failed"])).toEqual({ status: null, needYou: 0, title: "" });
    expect(placeDot(["idle", "working", "stopped"]).status).toBe("working");
    expect(placeDot(["idle", "replied"]).status).toBe("replied");
    expect(placeDot(["working", "needs-you"])).toEqual({ status: "needs-you", needYou: 1, title: "1 needs you · 1 working" });
  });

  it("counts the sessions that need you", () => {
    expect(placeDot(["needs-you", "idle", "needs-you"])).toEqual({ status: "needs-you", needYou: 2, title: "2 need you · 1 idle" });
  });

  it("groups by area in the areas' order, no area last", () => {
    const items = [
      { name: "a", area: "Work" },
      { name: "b", area: null },
      { name: "c", area: "Personal" },
      { name: "d", area: "Gone" }, // an area no longer defined: with those of none
    ];
    expect(byArea(items, ["Personal", "Work", "Client"]).map((g) => [g.area, g.items.map((i) => i.name)])).toEqual([
      ["Personal", ["c"]],
      ["Work", ["a"]],
      [null, ["b", "d"]],
    ]);
    expect(byArea([{ area: null }], ["Work"])).toEqual([{ area: null, items: [{ area: null }] }]);
  });
});
