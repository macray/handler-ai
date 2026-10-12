import type { SessionUpdate } from "@agentclientprotocol/sdk";
import { describe, expect, it } from "vitest";
import { imageSrc, markdown } from "@handler/acp-view/lib/render";
import { SessionState } from "@handler/acp-view/lib/session.svelte";
import { websocketStream, type Closed } from "../src/lib/acp/transport";
import { dirname, resolveLink, splitFrontmatter } from "../src/lib/knowledge";
import * as access from "../src/lib/access";
import { isEgressEntry, normalizeEntry, withEntry } from "../src/lib/hosts";
import { href, parse } from "../src/lib/router.svelte";
import { readSkill, writeSkill } from "../src/lib/skillmd";
import { who } from "../src/lib/skills";
import type { Agent, Project, Session } from "../src/lib/contracts.gen";
import * as projects from "../src/lib/projects.svelte";
import { ago, inFolder, specOf } from "../src/lib/agents";
import * as runs from "../src/lib/runs";
import * as automations from "../src/lib/automations";
import type { AutomationRun, SecretInfo } from "../src/lib/contracts.gen";
import * as secrets from "../src/lib/secrets";

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
      { kind: "thought", text: "hmm" },
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
    ["#/settings/addons", { view: "settings", section: "addons" }],
    ["#/skills", { view: "skills" }],
    ["#/skills/code-review", { view: "skill", name: "code-review" }],
    ["#/skills/new", { view: "skill", name: null }],
    ["#/skills/code-review?imported=replaced", { view: "skill", name: "code-review", imported: "replaced" }],
    ["#/skills/code-review?imported=nope", { view: "skill", name: "code-review" }],
    ["#/settings/nope", { view: "settings", section: "models" }],
    ["#/projects/p1", { view: "project", id: "p1" }],
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
    expect(parse(href({ view: "terminal", agent: "a1", connection: "c 1" }))).toEqual({ view: "terminal", agent: "a1", connection: "c 1" });
    expect(parse(href({ view: "skill", name: "a b", imported: "new" }))).toEqual({ view: "skill", name: "a b", imported: "new" });
    expect(parse(href({ view: "agent", id: "a1" }))).toEqual({ view: "agent", id: "a1" });
    expect(parse(href({ view: "edit-ad-hoc", id: "a1" }))).toEqual({ view: "edit-ad-hoc", id: "a1" });
    expect(parse(href({ view: "edit-ad-hoc", builtin: "skill-review" }))).toEqual({ view: "edit-ad-hoc", builtin: "skill-review" });
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
    models: [{ harness: "claude-code", account: "claude-perso" }],
    scope: `/home/me/code/${id}`,
    network: "open",
    confinement: "strict",
    permissions: "bypass",
    acpUrl: "",
    connections: [],
    createdAt: "2026-09-01T00:00:00Z",
    ...extra,
  });

  it("edits what an ad-hoc agent is set to", () => {
    const spec = specOf(w("x", { network: "filtered", egress: "enforce", allow: ["a.test:443"] }));
    expect(spec).toMatchObject({ network: "filtered", allow: ["a.test:443"], egress: "enforce", permissions: "bypass", name: "" });
  });

  it("says how long ago", () => {
    const now = Date.parse("2026-09-27T12:00:00Z");
    expect(ago("2026-09-27T11:59:30Z", now)).toBe("just now");
    expect(ago("2026-09-27T10:00:00Z", now)).toBe("2 hours ago");
    expect(ago("2026-09-26T12:00:00Z", now)).toBe("1 day ago");
    expect(ago(null, now)).toBe("never");
    expect(ago("2026-10-04T12:00:00Z", now)).toBe("in 7 days");
  });
});

describe("projects", () => {
  const agent = (id: string, extra: Partial<Agent> = {}): Agent => ({
    id,
    projectId: "p1",
    models: [{ harness: "claude-code", account: "claude-perso" }],
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
    agents: [agent("a1")],
    createdAt: "2026-09-01T00:00:00Z",
    ...extra,
  });

  it("edits an agent: its own values are copied", () => {
    const a = agent("a1", { name: "review", allow: ["a.test:443"], bindings: ["shop"], network: "none" });
    const spec = projects.agentSpec(a, { defaultAgent: "a1" });
    expect(spec).toMatchObject({ name: "review", allow: ["a.test:443"], bindings: ["shop"], knowledge: [], network: "none", default: true });
    expect(projects.agentBody({ ...spec, name: " Dev ", instructions: " be brief " })).toMatchObject({
      name: "Dev",
      instructions: "be brief",
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
    const spec = projects.emptyAgent([{ harness: null, account: "codex", provider: null, model: null }]);
    expect(spec).toMatchObject({ network: "filtered", egress: "enforce", confinement: "strict", permissions: "bypass" });
    spec.network = "none";
    expect(projects.PRESETS[1]!.sandbox.network).toBe("filtered");
  });

  it("finds another agent set up the same but for its models: one goal, one agent", () => {
    const dev = agent("a1", { name: "dev", network: "filtered", egress: "enforce" });
    const review = agent("a2", { name: "review", network: "none" });
    const spec = projects.emptyAgent([{ harness: "codex", account: "plus", provider: null, model: null }]);
    expect(projects.sameSetup({ ...spec, name: "codex" }, [review, dev], { defaultAgent: "a1" })?.id).toBe("a1");
    expect(projects.sameSetup({ ...spec, network: "open" }, [review, dev], { defaultAgent: "a1" })).toBeUndefined();
  });

  it("labels, orders and searches", () => {
    expect(projects.agentLabel({ name: null, models: [{ provider: "llamacpp", harness: "codex" }] })).toBe("llamacpp");
    const list = [project("old"), project("used", { lastUsedAt: "2026-09-20T00:00:00Z" }), project("x")];
    expect(projects.byRecentUse(list).map((p) => p.id)).toEqual(["used", "old", "x"]);
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
    const body = projects.agentBody(projects.emptyAgent([pro, local]));
    expect(body.models).toEqual([
      { account: "pro", harness: null, provider: null, model: null },
      { provider: "llamacpp", harness: "codex", account: null, model: "qwen" },
    ]);
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

  it("fills a built-in agent's form with its defaults", () => {
    const spec = runs.builtinSpec({
      name: "skill-review",
      description: "Reviews",
      agentName: "Skill reviewer",
      permissions: "ask",
      network: "filtered",
      egress: "enforce",
      skills: [],
      interface: { result, subject: "skill" },
    });
    expect(spec.name).toBe("Skill reviewer");
    expect([spec.permissions, spec.egress, spec.network]).toEqual(["ask", "enforce", "filtered"]);
    expect(JSON.parse(spec.interface).subject).toBe("skill");
    expect(spec.models[0]!.account).toBeNull();
  });

  it("builds an ad-hoc agent's body, folderless or not", () => {
    const spec = { ...projects.emptyAgent([{ harness: null, account: "a", provider: null, model: null }]), interface: '{"result": {}}' };
    const body = projects.adHocBody(spec, null);
    expect(body.scope).toBeNull();
    expect(body.name).toBeNull(); // optional outside projects
    expect(body.interface).toEqual({ result: {} });
    expect("default" in body || "remoteStart" in body).toBe(false);
    expect(body.confirmRisks).toBe(false); // what it widens is confirmed, as in projects (D.8)
    expect(projects.adHocBody(spec, null, null, true).confirmRisks).toBe(true);
    expect(() => projects.adHocBody({ ...spec, interface: "{" }, "/x")).toThrow("Interface: not JSON");
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
    const daily = automations.formOf({ ...base, description: "d", when: { at: "07:00", days: ["fri", "mon"] }, run: agentRun });
    expect(daily).toMatchObject({
      on: "time",
      schedule: { kind: "at", at: "07:00", days: ["mon", "fri"] },
      what: "agent",
      agent: { name: "Review", project: "shop", fields: { focus: "security" }, skill: "" },
      description: "d",
    });
    expect(automations.formOf({ ...base, when: { every: "30m" }, run: agentRun })?.schedule).toEqual({ kind: "every", n: 30, unit: "m" });
    const app = automations.formOf({ ...base, when: "session.stopped", only: { project: ["shop"] }, run: { app: "coach", call: "POST /api/x" } });
    expect(app).toMatchObject({ on: "stop", stopProject: "shop", what: "app", app: "coach", call: "POST /api/x", agent: null });
    expect(automations.formOf({ ...base, when: "session.stopped", run: "python3 x.py" })).toBeNull();
    expect(automations.formOf({ ...base, when: "session.stopped", only: { agent: ["dev"] }, run: agentRun })).toBeNull();
  });

  it("lists the automations that are on and run an agent", () => {
    const def = { apiVersion: "handler.automation/v1", when: { every: "1h" }, run: { agent: "Review", project: "shop" } } as const;
    const list = [
      { name: "a", enabled: true, definition: def },
      { name: "b", enabled: false, definition: def },
      { name: "c", enabled: true, definition: { ...def, run: { agent: "Other", project: "shop" } } },
    ];
    expect(automations.schedulesOf(list, "Review", "shop").map((a) => a.name)).toEqual(["a"]);
  });

  it("finds the automations that run an agent", () => {
    const def = { apiVersion: "handler.automation/v1", when: { every: "1h" }, run: { agent: "Review", project: "shop" } } as const;
    expect(automations.runsAgent(def, "Review", "shop")).toBe(true);
    expect(automations.runsAgent(def, "Review", null)).toBe(false);
    expect(automations.runsAgent({ ...def, run: { agent: "Review" } }, "Review", null)).toBe(true);
    expect(automations.runsAgent({ ...def, run: "python3 x.py" }, "Review", "shop")).toBe(false);
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

  it("names a secret after what it belongs to", () => {
    expect(secrets.title(info({ usedBy: ["providers/openrouter"] }))).toBe("Provider openrouter · key");
    expect(secrets.title(info({ path: "bindings/shop/theme_token", usedBy: ["bindings/shop"] }))).toBe(
      "Addon configuration shop · theme_token",
    );
    expect(secrets.title(info({ path: "spare/one", usedBy: [] }))).toBe("spare/one");
    expect(secrets.owner("accounts/perso")).toEqual({ label: "Account perso", route: { view: "settings", section: "models" } });
  });

  it("says where its value is", () => {
    expect(secrets.source(info({ source: "env", hasValue: false }))).toBe("from an environment variable of Handler: not set");
    expect(secrets.source(info({}))).toBe("kept by Handler");
  });

  it("replaces only stored values whose owner does not set them, forgets only unused ones", () => {
    expect(secrets.replaceable(info({}))).toBe(true);
    expect(secrets.replaceable(info({ path: "accounts/perso/token" }))).toBe(false);
    expect(secrets.replaceable(info({ source: "command" }))).toBe(false);
    expect(secrets.removable(info({ usedBy: [], createdAt: "2026-10-08T00:00:00Z" }))).toBe(true);
    expect(secrets.removable(info({ usedBy: ["providers/openrouter"], createdAt: "2026-10-08T00:00:00Z" }))).toBe(false);
    expect(secrets.removable(info({ source: "env", usedBy: [] }))).toBe(false);
  });
});
