import type { SessionUpdate } from "@agentclientprotocol/sdk";
import { describe, expect, it } from "vitest";
import { imageSrc, markdown } from "@handler/acp-view/lib/render";
import { SessionState, contextFill, modelText, tokens, type ToolEntry } from "@handler/acp-view/lib/session.svelte";
import { counts, lines, rows } from "@handler/acp-view/lib/diff";
import { activity, askedAtStep, changeLine, duration, headline, relative, summary, tail, turnChanges, turnSummary } from "@handler/acp-view/lib/tools";
import { websocketStream, type Closed } from "../src/lib/acp/transport";
import { dirname, resolveLink, splitFrontmatter } from "../src/lib/knowledge";
import * as access from "../src/lib/access";
import { isEgressEntry, normalizeEntry, recentLines, withEntry, withList } from "../src/lib/hosts";
import { href, opening, parse } from "../src/lib/router.svelte";
import { readSkill, writeSkill } from "../src/lib/skillmd";
import { who } from "../src/lib/skills";
import type { AddonInfo, AddonPreview, Agent, AgentDefinition, AgentsFile, App, BindingInfo, HandlerNeed, Project, Session, SourceItemDetail } from "../src/lib/contracts.gen";
import * as projects from "../src/lib/projects.svelte";
import * as safety from "../src/lib/safety";
import { ago, appOf, dayOf, inFolder, isChat, modeTone, nextMode } from "../src/lib/agents";
import * as runs from "../src/lib/runs";
import * as job from "../src/lib/interface";
import * as automations from "../src/lib/automations";
import * as plans from "../src/lib/plans";
import { ApiError } from "../src/lib/api";
import type { PlanRead, PlanStepView, PlanView } from "../src/lib/contracts.gen";
import type { AutomationRun, SecretInfo } from "../src/lib/contracts.gen";
import * as secrets from "../src/lib/secrets";
import { bellState, menuShows, moved, placeDot } from "../src/lib/menu";
import { tabTitle, withDot } from "../src/lib/favicon";
import { agentGroups, libraryTabs, yourAgents, type AgentFilter } from "../src/lib/library";
import * as tools from "../src/lib/tools";
import * as providers from "../src/lib/providers";
import * as helpers from "../src/lib/helpers";
import { following, makes } from "../src/lib/builds";
import type { Build } from "../src/lib/contracts.gen";
import type { EgressEvent, ProviderInfo, ProviderReach } from "../src/lib/contracts.gen";

const text = (t: string) => ({ type: "text" as const, text: t });

describe("SessionState", () => {
  it("keeps one card per refused host and turn, its count raised, then the answer said on it", () => {
    const s = new SessionState();
    s.apply({ sessionUpdate: "user_message_chunk", content: text("install it") });
    s.line({ seq: 3, event: "host blocked", host: "pypi.org:443", count: 1, card: 3 });
    s.line({ seq: 4, event: "host blocked", host: "pypi.org:443", count: 2, card: 3 });
    s.line({ seq: 5, event: "host blocked", host: "x.org:443", count: 1, card: 5 });
    s.line({ seq: 6, event: "host blocked", host: "pypi.org:443", count: 3, card: 3 });
    const cards = s.entries.filter((e) => e.kind === "host");
    expect(cards.map((c) => [c.host, c.count, c.decision])).toEqual([
      ["pypi.org:443", 3, null],
      ["x.org:443", 1, null],
    ]);
    expect(s.undecided).toEqual(["pypi.org:443", "x.org:443"]);
    s.line({ seq: 7, event: "host decided", host: "x.org:443", decision: "kept blocked" });
    s.line({ seq: 9, event: "host blocked", host: "pypi.org:443", count: 1, card: 9 }); // next turn
    expect(s.entries.filter((e) => e.kind === "host").map((c) => [c.card, c.decision])).toEqual([
      [3, null],
      [5, "kept blocked"],
      [9, null],
    ]);
    s.line({ seq: 10, event: "host decided", host: "pypi.org:443", decision: "allowed" });
    expect(s.undecided).toEqual([]);
    s.line({ seq: 11, event: "something else", host: "a.org:443" }); // unknown lines: ignored
    expect(s.entries.length).toBe(4);
  });

  it("counts a held request down until its refusal, and shows Handler's message as its own turn", () => {
    const s = new SessionState();
    s.apply({ sessionUpdate: "user_message_chunk", content: text("install it") });
    const until = "2026-11-01T12:00:08+00:00";
    s.line({ seq: 3, event: "host blocked", host: "pypi.org:443", count: 0, card: 3, until });
    const card = () => s.entries.find((e) => e.kind === "host");
    expect(card()).toMatchObject({ count: 0, until, decision: null });
    s.line({ seq: 4, event: "host blocked", host: "pypi.org:443", count: 1, card: 3 }); // refused
    expect(card()).toMatchObject({ count: 1, until: null });
    s.line({ seq: 5, event: "host decided", host: "pypi.org:443", decision: "allowed", queued: true });
    expect(card()).toMatchObject({ decision: "allowed", queued: true });
    s.line({ seq: 7, event: "told agent", text: "Handler: pypi.org:443 is now allowed. Go on." });
    expect(card()).toMatchObject({ queued: false });
    expect(s.entries.at(-1)).toEqual({ kind: "told", text: "Handler: pypi.org:443 is now allowed. Go on." });
    expect(s.entries.filter((e) => e.kind === "user").length).toBe(1); // never the person's
  });

  it("says when the model's host does not answer, and asks a server on this computer where it listens", () => {
    const s = new SessionState();
    s.line({ seq: 4, event: "model unreached", host: "host.containers.internal:3000", error: "connection refused", provider: "llama", local: true });
    s.line({ seq: 9, event: "model unreached", host: "api.example.com:443", error: "host not found", provider: "router", local: false });
    const [local, remote] = s.entries.filter((e) => e.kind === "model");
    expect(local).toEqual({ kind: "model", host: "host.containers.internal:3000", error: "connection refused", provider: "llama", local: true });
    expect(modelText(local!)).toBe("The model at host.containers.internal:3000 does not answer (connection refused). Is the server listening on 0.0.0.0?");
    expect(modelText(remote!)).toBe("The model at api.example.com:443 does not answer (host not found).");
  });

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

  it("keeps how full the context is, as last said (a replayed log ends on the latest)", () => {
    const s = new SessionState();
    expect(s.usage).toBeNull(); // a harness that never says: nothing shown
    s.apply({ sessionUpdate: "usage_update", used: 12_000, size: 200_000 });
    s.apply({ sessionUpdate: "agent_message_chunk", content: text("hi") });
    s.apply({ sessionUpdate: "usage_update", used: 84_000, size: 200_000, cost: { amount: 0.4, currency: "USD" } });
    expect(s.usage).toEqual({ used: 84_000, size: 200_000 });
  });

  it("says how full the context is", () => {
    expect([tokens(950), tokens(84_400), tokens(1_000_000), tokens(1_250_000)]).toEqual(["950", "84k", "1M", "1.3M"]);
    expect(contextFill({ used: 84_000, size: 200_000 })).toEqual({
      percent: 42,
      short: "42% · 84k / 200k",
      full: `${(84_000).toLocaleString()} of ${(200_000).toLocaleString()} tokens in its context (42%)`,
    });
    expect(contextFill({ used: 210_000, size: 200_000 }).percent).toBe(100);
    expect(contextFill({ used: 5_000, size: 0 })).toMatchObject({ percent: null, short: "5k tokens" });
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

  it("says what an edit changed, as Claude Code does", () => {
    const edit = { type: "diff" as const, path: "/w/p/a.py", oldText: "x\ny\n", newText: "x\nz\nw\n" };
    expect(changeLine(tool({ content: [edit] }), "/w/p")).toBe("Updated a.py with 2 additions and 1 removal");
    const one = { type: "diff" as const, path: "/w/p/a.py", oldText: "x\n", newText: "y\n" };
    expect(changeLine(tool({ content: [one] }), "/w/p")).toBe("Updated a.py with 1 addition and 1 removal");
    const made = { type: "diff" as const, path: "/w/p/n.md", oldText: null, newText: "a\nb\nc\n" };
    expect(changeLine(tool({ content: [made] }), "/w/p")).toBe("Wrote 3 lines to n.md");
    expect(changeLine(tool({ content: [edit, made] }), "/w/p")).toBe("Updated 2 files with 5 additions and 1 removal");
    expect(changeLine(tool({ content: [out("no diff")] }))).toBeNull();
  });

  it("keeps a command's last lines, indented as printed", () => {
    expect(tail(tool({ content: [out("```console\na\n  b\nc\n```\n")] }), 2)).toEqual({ lines: ["  b", "c"], more: 1 });
    expect(tail(tool({ content: [out("ok")] }), 4)).toEqual({ lines: ["ok"], more: 0 });
    expect(tail(tool({ content: [out("```\n\n```")] }), 4)).toBeNull();
  });

  it("cycles the modes and colours each by what it lets the agent do", () => {
    const modes = [{ id: "default" }, { id: "acceptEdits" }, { id: "plan" }];
    expect(nextMode(modes, "default")).toBe("acceptEdits");
    expect(nextMode(modes, "plan")).toBe("default");
    expect(nextMode(modes, null)).toBe("default");
    expect(nextMode([], "plan")).toBeNull();
    expect(modeTone("plan")).toBe("plan");
    expect(modeTone("acceptEdits", "accept-edits")).toBe("edits");
    expect(modeTone("bypassPermissions", "bypass")).toBe("bypass");
    expect(modeTone("default", "ask")).toBe("ask");
  });

  it("knows a question's step is in the timeline", () => {
    const entries = [{ kind: "user" as const, text: "go", images: [] }, tool({ id: "t1" })];
    expect(askedAtStep(entries, "t1")).toBe(true);
    expect(askedAtStep(entries, "t2")).toBe(false); // asked before its step was told: pinned
  });

  it("lists the files a turn changed, each with its diffs", () => {
    const a1 = { type: "diff" as const, path: "/a", oldText: "1\n", newText: "2\n" };
    const a2 = { type: "diff" as const, path: "/a", oldText: "2\n", newText: "2\n3\n" };
    const b = { type: "diff" as const, path: "/b", oldText: null, newText: "new\n" };
    const changes = turnChanges([tool({ content: [a1] }), { kind: "agent", text: "and" }, tool({ content: [b, a2] })]);
    expect(changes.map(({ path, created, added, removed, diffs }) => [path, created, added, removed, diffs.length])).toEqual([
      ["/a", false, 2, 1, 2],
      ["/b", true, 1, 0, 1],
    ]);
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
    ["#/", { view: "projects" }],
    ["", { view: "projects" }],
    ["#/projects", { view: "projects" }],
    ["#/library", { view: "library", shelf: "apps" }],
    ["#/library/notes", { view: "library", shelf: "notes" }],
    ["#/library/nope", { view: "library", shelf: "apps" }],
    ["#/library/tools/more", { view: "library", shelf: "tools", more: true }],
    ["#/library/tools/more?install=source%3Aofficial%2Fbun", { view: "library", shelf: "tools", more: true, install: "source:official/bun" }],
    ["#/library/tools/github", { view: "tool", name: "github" }],
    ["#/discover", { view: "projects" }], // Discover is each shelf's Get more
    ["#/projects/p1/agents/new?from=a1&job=1", { view: "edit-agent", project: "p1", from: "a1", job: true }],
    ["#/sessions/k1", { view: "session", key: "k1" }],
    ["#/settings", { view: "settings", section: "models" }],
    ["#/settings/areas", { view: "settings", section: "areas" }],
    ["#/tools", { view: "addons" }],
    ["#/skills", { view: "skills" }],
    ["#/skills/code-review", { view: "skill", name: "code-review" }],
    ["#/skills/new", { view: "skill", name: null }],
    ["#/skills/code-review?imported=replaced", { view: "skill", name: "code-review", imported: "replaced" }],
    ["#/skills/code-review?imported=nope", { view: "skill", name: "code-review" }],
    ["#/settings/nope", { view: "settings", section: "models" }],
    ["#/projects/p1", { view: "project", id: "p1" }],
    ["#/projects/p1?agent=a1", { view: "project", id: "p1", agent: "a1" }],
    ["#/projects/new", { view: "edit-project" }],
    ["#/projects/p1/plans", { view: "project", id: "p1", tab: "plans" }],
    ["#/projects/p1/settings", { view: "project", id: "p1", tab: "settings" }],
    ["#/projects/p1/edit", { view: "project", id: "p1" }], // no such tab: its Sessions
    ["#/projects/p1/agents/new", { view: "edit-agent", project: "p1" }],
    ["#/projects/p1/agents/a1", { view: "edit-agent", project: "p1", id: "a1" }],
    ["#/projects/p1/agents/new?from=a1", { view: "edit-agent", project: "p1", from: "a1" }],
    ["#/notes", { view: "knowledge" }],
    ["#/notes?path=projects%2Fshop", { view: "knowledge", path: "projects/shop" }],
    ["#/notes?note=me%2Ftools.md", { view: "knowledge", note: "me/tools.md" }],
  ])("parses %s", (hash, route) => {
    expect(parse(hash)).toEqual(route);
  });

  it("opens where you left off, else Projects", () => {
    // If this fails: Handler opens on a page you did not leave it on, or on nothing.
    expect(opening("", null)).toBe("#/projects");
    expect(opening("#/", "#/projects/p1")).toBe("#/projects/p1");
    expect(opening("#/", "#/")).toBe("#/projects");
    expect(opening("#/skills", "#/projects/p1")).toBe("#/skills"); // a page asked for wins
    expect(opening("#/projects", "#/projects/p1")).toBe("#/projects"); // the logo
    expect(opening("#/", "#token=x")).toBe("#/projects"); // only a page's address is kept
  });

  it("round-trips", () => {
    expect(parse(href({ view: "projects" }))).toEqual({ view: "projects" });
    expect(parse(href({ view: "library", shelf: "apps" }))).toEqual({ view: "library", shelf: "apps" });
    expect(parse(href({ view: "library", shelf: "automations" }))).toEqual({ view: "library", shelf: "automations" });
    expect(parse(href({ view: "library", shelf: "apps", more: true }))).toEqual({ view: "library", shelf: "apps", more: true });
    expect(href({ view: "library", shelf: "agents", more: true, project: "p 1" })).toBe("#/library/agents/more?project=p+1");
    expect(parse(href({ view: "library", shelf: "agents", more: true, project: "p 1" }))).toEqual({ view: "library", shelf: "agents", more: true, project: "p 1" });
    expect(parse(href({ view: "tool", name: "a b" }))).toEqual({ view: "tool", name: "a b" });
    expect(parse(href({ view: "edit-agent", project: "p1", from: "a 1", job: true }))).toEqual({ view: "edit-agent", project: "p1", from: "a 1", job: true });
    expect(parse(href({ view: "knowledge", path: "a b/c&d" }))).toEqual({ view: "knowledge", path: "a b/c&d" });
    expect(parse(href({ view: "edit-project", folder: "/home/me/x y" }))).toEqual({ view: "edit-project", folder: "/home/me/x y" });
    expect(parse(href({ view: "project", id: "p 1", tab: "automations" }))).toEqual({ view: "project", id: "p 1", tab: "automations" });
    expect(parse(href({ view: "edit-agent", project: "p1", id: "a b" }))).toEqual({ view: "edit-agent", project: "p1", id: "a b" });
    expect(parse(href({ view: "edit-agent", project: "p1" }))).toEqual({ view: "edit-agent", project: "p1" });
    expect(parse(href({ view: "settings", section: "phone" }))).toEqual({ view: "settings", section: "phone" });
    expect(parse(href({ view: "settings", section: "sandboxes" }))).toEqual({ view: "settings", section: "sandboxes" });
    expect(parse(href({ view: "agents" }))).toEqual({ view: "agents" });
    expect(parse(href({ view: "chat" }))).toEqual({ view: "chat" });
    expect(parse(href({ view: "chat", agent: "a 1", say: "a mail & more?" }))).toEqual({ view: "chat", agent: "a 1", say: "a mail & more?" });
    expect(parse(href({ view: "chat", new: true }))).toEqual({ view: "chat", new: true });
    expect(href({ view: "ask" })).toBe("#/chat/ask"); // Ask is Chat's Ask tab
    expect(parse("#/chat/ask")).toEqual({ view: "ask" });
    expect(parse("#/ask")).not.toEqual({ view: "ask" }); // gone
    expect(parse(href({ view: "agents", agent: "a 1" }))).toEqual({ view: "agents", agent: "a 1" });
    expect(parse(href({ view: "project", id: "p1", agent: "a b" }))).toEqual({ view: "project", id: "p1", agent: "a b" });
    expect(parse(href({ view: "terminal", agent: "a1", connection: "c 1" }))).toEqual({ view: "terminal", agent: "a1", connection: "c 1" });
    expect(parse(href({ view: "skill", name: "a b", imported: "new" }))).toEqual({ view: "skill", name: "a b", imported: "new" });
    expect(parse(href({ view: "agent", id: "a1" }))).toEqual({ view: "agent", id: "a1" });
    expect(parse(href({ view: "edit-ad-hoc", id: "a1" }))).toEqual({ view: "edit-ad-hoc", id: "a1" });
    expect(parse(href({ view: "settings", section: "helpers", helper: "skill-review" }))).toEqual({ view: "settings", section: "helpers", helper: "skill-review" });
    expect(href({ view: "settings", section: "helpers", helper: "skill-review" })).toBe("#/settings/helpers/skill-review"); // a helper's page
    expect(parse("#/helpers/skill-review/set-up")).not.toEqual({ view: "settings", section: "helpers", helper: "skill-review" }); // gone: its card
    expect(parse(href({ view: "setup", file: "shop-kit", project: "p1" }))).toEqual({ view: "setup", file: "shop-kit", project: "p1" });
    expect(parse(href({ view: "setup", file: "shop-kit" }))).toEqual({ view: "setup", file: "shop-kit" });
    expect(parse(href({ view: "edit-ad-hoc" }))).toEqual({ view: "edit-ad-hoc" });
    expect(parse(href({ view: "run", id: "s_1" }))).toEqual({ view: "run", id: "s_1" });
    expect(parse(href({ view: "plans" }))).toEqual({ view: "plans" });
    expect(parse(href({ view: "plan", id: "p_1" }))).toEqual({ view: "plan", id: "p_1" });
    const review = { view: "review-plan", session: "s_1", path: "plans/a b&c.md" } as const;
    expect(parse(href(review))).toEqual(review);
    expect(parse(href({ view: "review-plan", agent: "a1", path: "p.md" }))).toEqual({ view: "review-plan", agent: "a1", path: "p.md" });
    const chosen = { ...review, runner: "a2" };
    expect(parse(href(chosen))).toEqual(chosen);
    // a plan runner created for a review: back to it once saved
    const create = { view: "edit-agent", project: "p1", plan: review } as const;
    expect(href(create)).toBe(`#/projects/p1/agents/new?plan=${encodeURIComponent(href(review))}`);
    expect(parse(href(create))).toEqual(create);
    expect(parse("#/projects/p1/agents/new?plan=%23%2Fplans")).toEqual({ view: "edit-agent", project: "p1" });
    // a draft reviewed (D.27): no path; its plan runner comes back to it
    const drafted = { view: "review-plan", draft: "d_1", runner: "a2" } as const;
    expect(href(drafted)).toBe("#/plans/review?draft=d_1&runner=a2");
    expect(parse(href(drafted))).toEqual(drafted);
    const forDraft = { view: "edit-agent", project: "p1", plan: { view: "review-plan", draft: "d_1" } } as const;
    expect(parse(href(forDraft))).toEqual(forDraft);
    expect(parse("#/plans/review?path=")).toEqual({ view: "review-plan", path: "" });
  });
});

describe("plans (D.27)", () => {
  const step = (n: number, state: PlanStepView["state"]): PlanStepView => ({ n, title: `s${n}`, goal: "g", doneWhen: "d", state });
  const plan = (state: PlanView["state"], ...states: PlanStepView["state"][]): PlanView =>
    ({ id: "p_1", title: "t", source: "plans/p.md", folder: "/x", digest: "d", agentId: "a", stepTimeoutSec: 10800, approvedAt: "2026-10-31T00:00:00Z", state, steps: states.map((s, i) => step(i + 1, s)) }) as PlanView;

  it("says how far a plan went", () => {
    expect(plans.stepsDone(plan("running", "done", "running", "waiting"))).toBe("1 of 3 steps done");
    expect(plans.stepsDone(plan("done", "done"))).toBe("1 of 1 step done");
  });

  it("runs again from a step up to its first not done, never while running", () => {
    expect(plans.restartable(plan("running", "done", "running"))).toEqual([]);
    expect(plans.restartable(plan("stopped", "done", "failed", "waiting"))).toEqual([1, 2]);
    expect(plans.restartable(plan("done", "done", "done"))).toEqual([1, 2]);
  });

  const read = (extra: Partial<PlanRead> = {}): PlanRead => ({ path: "plans/p.md", digest: "d", stepTimeoutSec: 10800, text: "", ...extra });

  it("offers a fix for who runs it instead of refusing", () => {
    const runners = [
      { id: "a1", name: "dev", bypass: true },
      { id: "a2", name: "helper", bypass: false },
    ];
    expect(plans.runnerOf(read({ runners, agentId: "a2" }))?.name).toBe("helper");
    expect(plans.runnerFix(read({ runners, agentId: "a2" }))).toBe("switch"); // asks: switch it
    expect(plans.runnerFix(read({ runners, agentId: "a1" }))).toBe(null);
    expect(plans.runnerFix(read({ runners }))).toBe(null); // none chosen yet: choose one
    expect(plans.runnerFix(read({ runners: [], projectId: "p1" }))).toBe("create");
    expect(plans.runnerFix(read({ runners: [] }))).toBe(null); // a folder of no project
  });

  it("prefills a plan runner: only the sites it needs, never asking, on the project's default agent's model, a free name", () => {
    const project = {
      id: "p1",
      name: "x",
      folder: "/x",
      defaultAgent: "a2",
      agents: [
        { id: "a1", name: "plan-runner", model: { account: "claude-pro", harness: "claude-code" } },
        { id: "a2", name: "dev", model: { provider: "api", harness: "codex", model: "gpt" } },
      ],
    } as unknown as Project;
    const spec = plans.planRunner(project);
    expect(spec.name).toBe("plan-runner-2");
    expect([spec.network, spec.confinement, spec.permissions]).toEqual(["filtered", "strict", "bypass"]);
    expect(spec.egress).toBe("enforce");
    expect(spec.model).toMatchObject({ provider: "api", harness: "codex" });
    const empty = plans.planRunner({ ...project, agents: [] } as unknown as Project);
    expect(empty.name).toBe("plan-runner");
    expect(empty.model).toEqual(access.noAccess()); // its model, chosen in the form
  });

  it("tells the builder's model refused for the area from other refusals", () => {
    expect(plans.areaRefused(new ApiError(409, "not for this project's area", "account x is not for work projects"))).toBe(true);
    expect(plans.areaRefused(new ApiError(409, "it cannot build plans", "it has addons"))).toBe(false);
    expect(plans.areaRefused(new Error("not for this project's area"))).toBe(false);
  });

  it("says a step's time limit in words", () => {
    expect(plans.limit(10800)).toBe("3 hours");
    expect(plans.limit(3600)).toBe("1 hour");
    expect(plans.limit(5400)).toBe("90 minutes");
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

  it("keeps a host allowed or kept blocked, never both", () => {
    const hosts = { allow: ["a.com:443", "b.com:443"], blocked: ["c.com:443"] };
    expect(withList(hosts, "blocked", ["a.com:443", "c.com:443"])).toEqual({ allow: ["b.com:443"], blocked: ["a.com:443", "c.com:443"] });
    expect(withList(hosts, "allow", ["a.com:443", "b.com:443", "c.com:443"])).toEqual({ allow: ["a.com:443", "b.com:443", "c.com:443"], blocked: [] });
    expect(withList(hosts, "blocked", [])).toEqual({ allow: ["a.com:443", "b.com:443"], blocked: [] }); // removed: undecided
  });

  it("says what became of each request: reached, could not connect, blocked or kept blocked", () => {
    const ev = (decision: EgressEvent["decision"], host: string, more: Partial<EgressEvent> = {}): EgressEvent => ({ t: "2026-11-01T10:00:00Z", connection: "c1", decision, host, ...more });
    const events = [
      ev("allowed", "a.org:443"),
      ev("reached", "a.org:443"),
      ev("allowed", "host.containers.internal:3000"),
      ev("unreached", "host.containers.internal:3000", { error: "connection refused" }),
      ev("denied", "pypi.org:443"),
      ev("denied", "b.org:443"),
      ev("allowed", "a.org:443"), // a request on the connection already reached
      ev("allowed", "c.org:443"), // still connecting
    ];
    expect(recentLines(events, ["b.org:443"])).toEqual([
      { host: "c.org:443", outcome: "allowed" },
      { host: "a.org:443", outcome: "allowed" },
      { host: "b.org:443", outcome: "kept blocked" },
      { host: "pypi.org:443", outcome: "blocked" },
      { host: "host.containers.internal:3000", outcome: "could not connect", detail: "connection refused" },
      { host: "a.org:443", outcome: "reached" },
    ]);
    expect(recentLines(events, [], 2).map((l) => l.host)).toEqual(["c.org:443", "a.org:443"]);
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
    expect(dayOf(new Date(2026, 9, 15, 0, 5).toISOString(), now)).toBe("Today");
    expect(dayOf(new Date(2026, 9, 14, 23, 50).toISOString(), now)).toBe("Yesterday");
    expect(dayOf(new Date(2026, 9, 12, 12, 0).toISOString(), now)).not.toMatch(/Today|Yesterday/);
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
    agents: [agent("a1")],
    createdAt: "2026-09-01T00:00:00Z",
    ...extra,
  });

  it("edits an agent: its own values are copied", () => {
    const a = agent("a1", { name: "review", allow: ["a.test:443"], addons: [{ addon: "shopify", binding: "shop" }], network: "none" });
    const spec = projects.agentSpec(a, { defaultAgent: "a1" });
    expect(spec).toMatchObject({ name: "review", allow: ["a.test:443"], addons: [{ addon: "shopify", binding: "shop" }], knowledge: [], network: "none", default: true });
    expect(projects.agentBody({ ...spec, name: " Dev ", instructions: " be brief " }, { projectId: "p1" })).toMatchObject({
      projectId: "p1",
      name: "Dev",
      instructions: "be brief",
      default: true,
      confirmRisks: false,
    });
  });

  it("duplicates an agent as a copy with a free name", () => {
    const a = agent("a1", { name: "review", addons: [{ addon: "app-builder" }], network: "none" });
    const copy = projects.duplicateAgent(a, ["review", "review-copy"]);
    expect(copy).toMatchObject({ name: "review-copy-2", addons: [{ addon: "app-builder" }], network: "none", default: false });
    copy.addons.push({ addon: "x" });
    expect(a.addons).toEqual([{ addon: "app-builder" }]);
  });

  it("starts a new agent with only the sites it needs, never asking: a copy", () => {
    const spec = projects.emptyAgent({ harness: null, account: "codex", provider: null, model: null });
    expect(spec).toMatchObject({ network: "filtered", egress: "enforce", confinement: "strict", permissions: "bypass" });
    spec.network = "none";
    expect(safety.NEW_AGENT.network).toBe("filtered");
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
    expect(projects.matches(project("shop", { description: "Liquid theme" }), "liquid shop")).toBe(true);
    expect(projects.matches(project("shop", { description: "Liquid theme" }), "liquid claude")).toBe(false); // only what its row shows
    expect(projects.matches(project("shop"), "vibe")).toBe(false);
    expect(projects.shortFolder("/home/me/code/blog/")).toBe("~/code/blog");
    expect(projects.shortFolder("/Users/me/Documents/uni/thesis")).toBe("~/Documents/uni/thesis");
    expect(projects.shortFolder("/home/me/Documents/2026/talks/q4")).toBe("~/Documents/…/q4");
    expect(projects.shortFolder("/srv/data/a/b/c")).toBe("/srv/…/c");
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
    // the Library's rows: what it runs in a word or two, and its filter
    expect(automations.runsWords({ ...base, when: { every: "1h" } })).toBe("your script");
    expect(automations.runsWords({ ...base, when: { every: "1h" }, run: { agent: "reviewer" } }, "Reviewer")).toBe("Reviewer");
    expect(automations.runsWords({ ...base, when: { every: "1h" }, run: { app: "planner", call: "POST /api/x" } })).toBe("planner's route");
    expect([base, { ...base, run: { agent: "r" } }, { ...base, run: { app: "a", call: "POST /x" } }].map((d) => automations.runsKind({ ...d, when: "session.stopped" }))).toEqual(["script", "agent", "app"]);
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

  it("groups a secret by what it belongs to, and names it in words", () => {
    expect(secrets.group(info({ usedBy: ["providers/openrouter"] }))).toBe("providers");
    expect(secrets.group(info({ path: "connections/shop/theme_token", usedBy: ["connections/shop"] }))).toBe("connections");
    expect(secrets.group(info({ path: "spare/one", usedBy: [] }))).toBe("unused");
    expect(secrets.names(info({ usedBy: ["providers/openrouter"] }))).toEqual({ owner: "openrouter", slot: "key" });
    expect(secrets.names(info({ path: "connections/shop/theme_token", usedBy: ["connections/shop"] }))).toEqual({ owner: "shop", slot: "theme token" });
    expect(secrets.names(info({ path: "spare/one", usedBy: [] }))).toEqual({ owner: "spare/one", slot: "" });
  });

  it("needs you when a value is missing or an agent reads it, not when no agent gets it", () => {
    const used = { usedBy: ["providers/openrouter"] };
    expect(secrets.stateOf(info({ ...used, hasValue: false, source: "env" }))).toBe("missing");
    expect(secrets.stateOf(info({ ...used, visible: "the proxy cannot carry it: …", agents: ["blog · Dev"] }))).toBe("exposed");
    expect(secrets.stateOf(info({ ...used, visible: "no host to give it to: …", agents: [] }))).toBe("readable");
    expect(secrets.stateOf(info({ ...used, hasValue: true }))).toBe("sealed");
    expect(secrets.stateOf(info({ usedBy: [] }))).toBe("unused");
    expect(secrets.needsYou(info({ ...used, hasValue: false }))).toBe(true);
    expect(secrets.needsYou(info({ ...used, visible: "x", agents: [] }))).toBe(false);
  });

  it("links each to the page its owner is set on, by name", () => {
    expect(secrets.owner("accounts/perso")).toEqual({ page: "Model access", name: "perso", href: "#/settings/models" });
    expect(secrets.owner("connections/my-shop", { "my-shop": "shopify" })).toEqual({ page: "Tools", name: "my-shop", href: "#/library/tools/shopify" });
    expect(secrets.owner("apps/journal").href).toBe("#/apps/journal");
  });

  it("says where its value is, and why an agent reads it", () => {
    expect(secrets.source(info({ source: "env" }))).toBe("from an environment variable of Handler");
    expect(secrets.why("the proxy cannot carry it: under 8 characters, or not printable ASCII")).toBe("too short or not plain text to seal");
    expect(secrets.host("api.example.com:443")).toBe("api.example.com");
    expect(secrets.host("10.0.0.2:8080")).toBe("10.0.0.2:8080");
    expect(secrets.agent("shop-theme · Assistant")).toEqual({ name: "Assistant", project: "shop-theme" });
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
  const def = { agentName: "Order triage", addons: ["app-builder", "shopify"], knowledge: ["shop/policies"], skills: ["tidy"], network: "filtered", permissions: "bypass" } as AgentDefinition;
  const file = { name: "shop-kit", version: 3, place: "project", agents: [{ part: "order-triage", definition: def, checks: [] }, { part: "dev", definition: { agentName: "Dev" }, checks: [] }] } as unknown as AgentsFile;

  it("names an agent in an agents file as handlerd does", async () => {
    const { partName } = await import("../src/lib/setup");
    const { freeName } = await import("../src/lib/text");
    expect(partName("Order triage")).toBe("order-triage");
    expect(partName("  Été ")).toBe("t");
    expect(partName("!!")).toBe("agent");
    expect(freeName("Skill reviewer", ["skill reviewer", "Skill reviewer 2"], " ")).toBe("Skill reviewer 3");
    expect(freeName("Dev", [])).toBe("Dev");
    expect(freeName("dev-copy", ["Dev-Copy", "dev-copy-2"])).toBe("dev-copy-3");
  });

  it("asks only what an agent needs, and builds its request from the choice", async () => {
    const { fileOrigin, firstChoice, missing, projectAgentBody, outsideAgentBody } = await import("../src/lib/setup");
    // app-builder has no settings: chosen by its name; shopify's need a configuration of it
    const addons = [{ name: "app-builder" }, { name: "shopify", settings: [{ name: "store" }] }] as AddonInfo[];
    const bindings = [{ name: "broken", addon: "shopify", error: "x" }, { name: "shop-main", addon: "shopify" }] as BindingInfo[];
    const c = firstChoice(def, bindings, addons, ["shop/policies"]);
    expect(c.bindings).toEqual({ shopify: "shop-main" });
    expect(c.knowledge).toEqual({ "shop/policies": "shop/policies" });
    expect(missing(def, c, addons)).toEqual(["its model"]);
    expect(missing(def, firstChoice(def, [], addons, []), addons)).toEqual(["its model", "a connection to shopify", "a notes folder for shop/policies"]);
    c.model = { harness: null, account: "work", provider: null, model: null };
    expect(missing(def, c, addons)).toEqual([]);
    const origin = fileOrigin(file, "order-triage");
    const body = projectAgentBody(origin, file.agents[0]!.definition, c);
    expect([body.origin, body.name, body.addons, body.knowledge, body.skills, body.confirmRisks]).toEqual([
      { kind: "agents-file", name: "shop-kit", version: 3, agent: "order-triage" },
      "Order triage",
      [{ addon: "app-builder" }, { addon: "shopify", binding: "shop-main" }],
      ["shop/policies"],
      ["tidy"],
      true,
    ]);
    expect(body.model.account).toBe("work");
    const outside = outsideAgentBody(origin, file.agents[0]!.definition, c, null);
    expect([outside.scope, outside.origin]).toEqual([null, { kind: "agents-file", name: "shop-kit", version: 3, agent: "order-triage" }]);
  });

  it("asks for a tool not installed itself, never for a connection to it", async () => {
    const { firstChoice, missing } = await import("../src/lib/setup");
    const work = { harness: null, account: "work", provider: null, model: null };
    // nothing installed: each tool is to install first, none asks for a connection yet
    const c = firstChoice(def, [], [], ["shop/policies"]);
    expect(c.bindings).toEqual({});
    c.model = work;
    expect(missing(def, c, [])).toEqual(["the app-builder tool, from Library → Tools", "the shopify tool, from Library → Tools"]);
    // a helper's tool without settings, installed (the App creator's app-builder): nothing to ask
    const creator = { agentName: "App creator", addons: ["app-builder"] } as AgentDefinition;
    const helper = firstChoice(creator, [], [{ name: "app-builder" }] as AddonInfo[], []);
    helper.model = work;
    expect(missing(creator, helper, [{ name: "app-builder" }] as AddonInfo[])).toEqual([]);
  });

  it("lets a tool a source offers come along with its agent, unless it needs a connection", async () => {
    const { comesAlong, firstChoice, missing, weakens } = await import("../src/lib/setup");
    const c = firstChoice(def, [], [], ["shop/policies"]);
    c.model = { harness: null, account: "work", provider: null, model: null };
    // app-builder installed with it (G.5): only shopify is left to install first
    expect(missing(def, c, [], ["app-builder"])).toEqual(["the shopify tool, from Library → Tools"]);
    expect(comesAlong({ egress: ["fonts.gstatic.com:443"] } as AddonPreview)).toBe(true);
    expect(comesAlong({ settings: [{ name: "store" }] } as AddonPreview)).toBe(false);
    expect(comesAlong({ secretSlots: [{ name: "token" }] } as AddonPreview)).toBe(false);
    expect(weakens("never asks before acting")).toBe(true);
    expect(weakens("reach its model, its tools' hosts")).toBe(false);
  });

  it("says in Discover what an agents file's tools still ask", async () => {
    const { itemFacts } = await import("../src/lib/sources");
    const detail = {
      agents: { agents: [{ part: "web-designer", definition: { agentName: "Web designer", addons: ["taste", "shopify"] }, checks: [] }] },
    } as unknown as SourceItemDetail;
    const needs = (addons: AddonInfo[]) => itemFacts(detail, addons).needs.filter((n) => /taste|shopify/.test(n));
    expect(needs([])).toEqual(["the taste tool, from Library → Tools", "the shopify tool, from Library → Tools"]);
    expect(needs([{ name: "taste" }, { name: "shopify", settings: [{ name: "store" }] }] as AddonInfo[])).toEqual(["a connection to shopify"]);
  });

  it("says what an agent may do", async () => {
    const { mayDo } = await import("../src/lib/setup");
    expect(mayDo(def, "/home/me/shop")).toEqual(["read and write /home/me/shop", "reach its model, its tools' hosts", "never asks before acting"]);
    expect(mayDo({ ...def, modelAlone: true }, null)).toEqual(["nothing outside its call; its notes are sent to its provider"]);
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

  const empty = { projects: 0, modelReady: false };

  it("is the bell, Projects and Settings on the first run", () => {
    expect(menuShows(empty)).toEqual({ chat: false, apps: false, library: false });
  });

  it("shows Chat and Apps once a model is connected, the Library once a project exists", () => {
    expect(menuShows({ ...empty, modelReady: true })).toEqual({ chat: true, apps: true, library: false });
    expect(menuShows({ ...empty, projects: 1 })).toEqual({ chat: false, apps: false, library: true });
  });

  it("rings the bell: waiting first, then running, else quiet", () => {
    expect(bellState(0, 0)).toBe("quiet");
    expect(bellState(0, 2)).toBe("running");
    expect(bellState(1, 2)).toBe("waiting");
  });

  it("moves a pinned item to the place of the one it is dropped on", () => {
    expect(moved(["a", "b", "c"], 0, 2)).toEqual(["b", "c", "a"]);
    expect(moved(["a", "b", "c"], 2, 0)).toEqual(["c", "a", "b"]);
    expect(moved(["a", "b", "c"], 1, 1)).toEqual(["a", "b", "c"]);
  });

  it("says the count in the browser tab: its title and a dot on its icon", () => {
    expect(tabTitle(0)).toBe("Handler");
    expect(tabTitle(2)).toBe("(2) Handler");
    expect(withDot('<svg viewBox="0 0 64 64"><path/></svg>\n')).toMatch(/<path\/><circle [^>]+\/><\/svg>$/);
  });

  it("lists the Library's shelves, for you then for your agents", () => {
    const tabs = libraryTabs("skills");
    expect(tabs.map((t) => [t.group, t.label])).toEqual([
      ["For you", "Apps"],
      ["For you", "Agents"],
      ["For your agents", "Tools"],
      ["For your agents", "Skills"],
      ["For your agents", "Notes"],
      ["For your agents", "Automations"],
    ]);
    expect(tabs.filter((t) => t.active).map((t) => t.href)).toEqual(["#/library/skills"]);
    expect(libraryTabs("apps", { tools: 3, notes: 0 }).map((t) => t.count)).toEqual([undefined, undefined, 3, undefined, 0, undefined]);
  });

  it("lists your agents on the Agents shelf by where they work, each saying where it came from", () => {
    // If this fails: an app's agent, Chat's or a helper shows as yours, an agent is left out or
    // in the wrong group, or one set up from an agents file reads as made here.
    const agent = (id: string, extra: Partial<Agent> = {}): Agent => ({ ...({} as Agent), id, name: id, ...extra });
    const file = { kind: "agents-file" as const, name: "ponytail", agent: "ponytail", version: 1 };
    const all = [
      agent("Dev", { projectId: "p1" }),
      agent("Ponytail", { projectId: "p1", origin: file }),
      agent("Writer", { projectId: "p2" }),
      agent("Scratch"),
      agent("Planner", { app: "planner" }),
      agent("Assistant", { chat: true }),
      agent("Namer", { origin: { kind: "handler-need", name: "namer", version: 1 } }),
    ];
    const projects = [{ id: "p2", name: "blog" }, { id: "p1", name: "datakili" }] as Project[];
    const yours = yourAgents(all);
    expect(yours.map((a) => [a.agent.id, a.from])).toEqual([["Dev", null], ["Ponytail", "ponytail"], ["Writer", null], ["Scratch", null]]);
    const names = (filter?: AgentFilter) => agentGroups(yours, projects, filter).map((g) => [g.project?.name ?? null, g.agents.map((a) => a.agent.id)]);
    expect(names()).toEqual([["blog", ["Writer"]], ["datakili", ["Dev", "Ponytail"]], [null, ["Scratch"]]]);
    expect(names("others")).toEqual([["datakili", ["Ponytail"]]]);
    expect(names("here")).toEqual([["blog", ["Writer"]], ["datakili", ["Dev"]], [null, ["Scratch"]]]);
  });

  it("says a tool's state in one word", () => {
    // If this fails: a broken tool reads as ready, or one with nothing connected as usable.
    const tool = (extra: Partial<AddonInfo> = {}): AddonInfo => ({ name: "github", directory: "/x", state: "ready", ...extra });
    const slot = { secretSlots: [{ name: "token" }] };
    expect(tools.toolState(tool(), [])).toBe("ready");
    expect(tools.toolState(tool(slot), [])).toBe("not-set-up");
    expect(tools.toolState(tool(slot), [{ name: "mcy", addon: "github" }])).toBe("ready");
    expect(tools.toolState(tool(slot), [{ name: "mcy", addon: "github", error: "token gone" }])).toBe("broken");
    expect(tools.toolState(tool({ error: "no tool.toml" }), [])).toBe("broken");
    expect(tools.toolState(tool({ state: "failed", stateDetail: "build failed" }), [])).toBe("broken");
    expect(tools.brokenBecause(tool({ state: "failed", stateDetail: "build failed" }), [{ name: "mcy", error: "token gone" }])).toEqual(["build failed", "the connection mcy: token gone"]);
    expect(tools.sitesWords(tool({ egress: ["github.com", "api.github.com"] }))).toBe("2 sites");
  });
});

describe("a provider's test", () => {
  const reach = (over: Partial<ProviderReach>): ProviderReach => ({
    ok: true,
    at: "2026-11-01T10:00:00Z",
    urls: ["http://host.containers.internal:8080/v1/models"],
    ...over,
  });
  const info = (over: Partial<ProviderInfo>): ProviderInfo => ({ name: "llamacpp", status: "ready", ...over });

  it("knows a server on this computer by its address", () => {
    expect(providers.onThisComputer("http://host.containers.internal:8080/v1")).toBe(true);
    expect(providers.onThisComputer("http://127.0.0.1:11434/v1")).toBe(true);
    expect(providers.onThisComputer("https://openrouter.ai/api/v1")).toBe(false);
    expect(providers.onThisComputer("not a url")).toBe(false);
  });

  it("says ready with what answered, or not reached with why", () => {
    expect(providers.reachLine(reach({ models: [{ id: "a" }, { id: "b" }] }))).toBe("Ready: host.containers.internal:8080 answered, 2 models");
    expect(providers.reachLine(reach({ models: [] }))).toBe("Ready: host.containers.internal:8080 answered, serving no model yet");
    const refused = reach({ ok: false, error: "nothing answered at host.containers.internal:8080 (refused)" });
    expect(providers.reachLine(refused)).toBe("Not reached: nothing answered at host.containers.internal:8080 (refused)");
  });

  it("shows a server on this computer ready only once a test reached it", () => {
    expect(providers.statusOf(info({ local: true })).text).toBe("Not tested yet");
    expect(providers.statusOf(info({ local: true, reached: reach({ ok: false, error: "x" }) })).text).toBe("Not reached");
    expect(providers.statusOf(info({ local: true, reached: reach({}) })).text).toBe("Ready");
    expect(providers.statusOf(info({})).text).toBe("Ready"); // a hosted API: its key is set
    expect(providers.statusOf(info({ status: "incomplete", local: true })).text).toBe("To finish");
  });

  it("fills the models from what the server serves, or the context of those typed", () => {
    const served = [{ id: "qwen", contextWindow: 32768 }, { id: "small" }];
    expect(providers.fillModels([], served)).toEqual(served);
    expect(providers.fillModels([{ id: " " }], served)).toEqual(served);
    const typed = [{ id: "qwen", name: "Qwen" }, { id: "mine", contextWindow: 4096 }];
    expect(providers.fillModels(typed, served)).toEqual([{ id: "qwen", name: "Qwen", contextWindow: 32768 }, { id: "mine", contextWindow: 4096 }]);
    expect(providers.fillModels([{ id: "qwen", contextWindow: 8192 }], served)).toEqual([{ id: "qwen", contextWindow: 8192 }]);
  });
});

describe("the build a session that cannot start yet follows", () => {
  const build = (target: string, state: Build["state"], more: Partial<Build> = {}): Build => ({
    id: `${target}-${state}`,
    target,
    state,
    startedAt: "2026-11-01T10:00:00Z",
    ...more,
  });
  const refused = "2026-11-01T10:01:00Z";

  it("takes the toolbox build for the agent programs and addons it rebuilds", () => {
    expect(makes(build("codex", "running"), "codex")).toBe(true);
    expect(makes(build("toolbox", "running", { harnesses: ["codex"] }), "codex")).toBe(true);
    expect(makes(build("toolbox", "running"), "codex")).toBe(false); // codex was never built
    expect(makes(build("toolbox", "running", { addons: ["browser"] }), "addon:browser")).toBe(true);
    expect(makes(build("toolbox", "running"), "addon:browser")).toBe(false);
    expect(makes(build("toolbox", "running"), "network-filter")).toBe(false);
    expect(makes(build("claude-code", "running"), "codex")).toBe(false);
  });

  it("follows a running build that makes it, so none is started a second time", () => {
    const list = [build("claude-code", "running"), build("toolbox", "running", { harnesses: ["codex"] }), build("codex", "failed")];
    expect(following(list, "codex", refused)?.id).toBe("toolbox-running");
  });

  it("knows what was just built, and nothing older than the refused start", () => {
    const after = build("toolbox", "succeeded", { harnesses: ["codex"], endedAt: "2026-11-01T10:03:00Z" });
    expect(following([after], "codex", refused)).toBe(after);
    const before = build("codex", "succeeded", { endedAt: "2026-11-01T10:00:30Z" });
    expect(following([before], "codex", refused)).toBeNull();
    expect(following([build("toolbox", "failed", { harnesses: ["codex"], endedAt: "2026-11-01T10:03:00Z" })], "codex", refused)).toBeNull();
  });
});

describe("safety: the network's meter and what widens", () => {
  it("counts bars, more is safer, and says the network in a word", () => {
    expect([safety.barsOf("none"), safety.barsOf("filtered"), safety.barsOf("open")]).toEqual([3, 2, 1]);
    expect(safety.networkWords("filtered", 1)).toBe("1 site");
    expect(safety.networkWords("filtered", 4)).toBe("4 sites");
    expect(safety.networkWords("none", 4)).toBe("No network");
    expect(safety.networkWords("open", 4)).toBe("Any site");
  });

  it("names each setting that weakens the sandbox, never a default", () => {
    expect(safety.widenings(safety.NEW_AGENT)).toEqual([]);
    const labels = (a: Parameters<typeof safety.widenings>[0], caches?: string) => safety.widenings(a, caches).map((w) => w.label);
    expect(labels({ network: "filtered", egress: "log-only" })).toEqual(["Learning the sites"]);
    expect(labels({ network: "open", egress: "log-only" })).toEqual([]); // the meter says Any site
    expect(labels({ confinement: "nested", display: true }, "global")).toEqual(["Runs containers", "Windows on my screen", "Shared caches"]);
    expect(safety.safetyLine({ network: "filtered", confinement: "privileged" }, 3)).toBe("3 sites · Privileged");
  });

  it("lists the sites what it uses needs, each once, with why", () => {
    const infos = {
      accounts: [{ name: "perso", status: "ready", hosts: ["api.anthropic.com:443"] }],
      providers: [{ name: "mistral", status: "ready", endpoints: { chat: "https://api.mistral.ai/v1" } }],
      addons: [{ name: "github", egress: ["github.com:443", "api.anthropic.com:443"] }],
    } as unknown as Parameters<typeof safety.neededSites>[2];
    const none = { harness: null, account: null, provider: null, model: null };
    expect(safety.neededSites({ ...none, account: "perso" }, [{ addon: "github" }], infos)).toEqual([
      { host: "api.anthropic.com:443", why: "its model" },
      { host: "github.com:443", why: "the github tool" },
    ]);
    expect(safety.neededSites({ ...none, provider: "mistral", harness: "codex" }, [], infos)).toEqual([{ host: "api.mistral.ai", why: "its model" }]);
    // a saved agent unchanged: handlerd's list, its reasons in words
    const saved = [
      { host: "a:443", by: "account perso" },
      { host: "b:443", by: "the github tool: acme-bot" },
      { host: "c:443", by: "MCP server linear" },
    ];
    expect(safety.neededSites(none, [], infos, saved).map((s) => s.why)).toEqual(["its model", "the github tool", "the linear tool"]);
  });
});

describe("a project's suggested first agent", () => {
  const ready = (name: string, more = {}) => ({ name, status: "ready", ...more }) as never;
  const used = (agentModel: object, defaultAgent = "a1") =>
    ({ id: "p", name: "p", folder: "/p", createdAt: "2026-11-01T00:00:00Z", defaultAgent, agents: [{ id: "a1", model: agentModel }] }) as unknown as Project;

  it("runs on what the project used last runs on, when ready and for its area", () => {
    const accounts = [ready("perso", { harness: "claude-code" }), ready("pro", { harness: "claude-code", areas: ["Work"] })];
    const last = used({ account: "perso", harness: "claude-code", model: "sonnet" });
    expect(projects.suggestedAccess([last], accounts, [], null)).toMatchObject({ account: "perso", model: "sonnet" });
    // perso is not made for Work: then the one ready for it
    expect(projects.suggestedAccess([last], accounts, [], "Work")).toMatchObject({ account: "pro", harness: "claude-code" });
  });

  it("else the only one ready; none when two could be", () => {
    const providers = [ready("mistral", { harnesses: ["vibe"] })];
    expect(projects.suggestedAccess([], [], providers, null)).toMatchObject({ provider: "mistral", harness: "vibe" });
    expect(projects.suggestedAccess([], [ready("perso", { harness: "claude-code" })], providers, null)).toBeNull();
    expect(projects.suggestedAccess([], [{ name: "x", status: "incomplete", harness: "codex" } as never], [], null)).toBeNull();
  });
});

describe("helpers", () => {
  const definition = (more: Partial<AgentDefinition> = {}): AgentDefinition => ({ agentName: "x", network: "filtered", egress: "enforce", confinement: "strict", permissions: "bypass", ...more });

  it("shows locked what the plan builder's feature holds it to, and nothing of its own beside", () => {
    const facts = helpers.factsOf("plan-builder", definition());
    expect(facts.map((f) => [f.key, f.locked])).toEqual([
      ["project", true],
      ["writes", true],
      ["network", true],
      ["tools", true],
    ]);
  });

  it("shows the rest as the helper's own settings, a widening amber", () => {
    const facts = helpers.factsOf("skill-review", definition({ confinement: "nested", allow: ["pypi.org"] }));
    expect(facts.filter((f) => f.locked).map((f) => f.key)).toEqual(["given", "answers"]);
    const own = facts.filter((f) => !f.locked);
    expect(own[0]).toMatchObject({ key: "network", text: "only its model's sites, and 1 site of yours", warn: false });
    expect(own[1]).toMatchObject({ label: "Runs containers", warn: true });
    expect(helpers.factsOf("skill-review", definition({ network: "open" })).find((f) => f.key === "network")).toMatchObject({ text: "Any site", warn: true });
  });

  it("says the model alone as one fact, with no network", () => {
    const facts = helpers.factsOf("ask-router", definition({ modelAlone: true }));
    expect(facts.at(-1)).toMatchObject({ key: "alone", locked: false });
    expect(facts.some((f) => f.key === "network")).toBe(false);
  });

  it("says what it works with apart from what it can do: its skills, its tools' named after them", () => {
    const tools = [{ name: "app-builder", skills: ["app-builder"] }] as AddonInfo[];
    expect(helpers.factsOf("app-creator", definition({ addons: ["app-builder"] })).some((f) => f.key === "tools")).toBe(false);
    expect(helpers.usesOf("app-creator", definition({ addons: ["app-builder"] }), tools)).toEqual([
      { key: "skills", label: "Skills", text: "app-builder (from the app-builder tool)" },
      { key: "tools", label: "Tools", text: "app-builder" },
    ]);
    expect(helpers.usesOf("skill-creator", definition({ skills: ["handler-skills", "skill-creator"] }), tools)).toEqual([
      { key: "skills", label: "Skills", text: "handler-skills, skill-creator" },
      { key: "tools", label: "Tools", text: "none" },
    ]);
    // the plan builder's feature fixes it no tool (Can do says it, locked): its skills alone
    expect(helpers.usesOf("plan-builder", definition({ skills: ["handler-plan"] }), [])).toEqual([{ key: "skills", label: "Skills", text: "handler-plan" }]);
    expect(helpers.usesOf("ask-router", definition({ modelAlone: true }), tools)).toEqual([]);
  });

  it("names each helper by the feature it serves, in Settings' order", () => {
    expect(helpers.FEATURES.map((f) => f.need)).toEqual(["plan-builder", "ask-router", "prompt-writer", "app-creator", "skill-creator", "skill-review"]);
    expect(helpers.featureOf("plan-builder")).toMatchObject({ feature: "Plans", verb: "Written by" });
    expect(helpers.needLabel("skill-review")).toBe("Skill reviewer");
  });
});

describe("words made from values (text.ts)", () => {
  it("sizes, slugs and names not taken read the same on every page", async () => {
    const { formatBytes, slug } = await import("../src/lib/text");
    expect([formatBytes(512), formatBytes(2_000_000), formatBytes(143_400_000), formatBytes(1_234_000_000)]).toEqual(["512 B", "2.0 MB", "143 MB", "1.2 GB"]);
    expect(slug("  Daily news digest! ")).toBe("daily-news-digest");
  });
});
