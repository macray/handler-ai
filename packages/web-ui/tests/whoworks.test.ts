// Who works (E2): the rows of its first menu, what is folded and why, the program part, the
// models, the default choice, a session's change and the unattended line.
import { describe, expect, it } from "vitest";
import type { AccountInfo, AgentModel, HarnessInfo, ProviderInfo } from "../src/lib/contracts.gen";
import * as ww from "../src/lib/whoworks";

const login = (unattended: "allowed" | "check-terms" | "refused") => ({ subscription: "a plan", unattended, terms: "https://example.com/terms" });
const harnesses: HarnessInfo[] = [
  { name: "claude-code", product: "Claude Code", image: "x", login: login("refused") },
  { name: "codex", product: "Codex", image: "x", login: login("check-terms") },
  { name: "pi", product: "pi", image: "x" },
];
const account = (name: string, harness: string, extra: Partial<AccountInfo> = {}): AccountInfo => ({ name, harness, status: "ready", areas: ["any"], ...extra });
const provider = (name: string, extra: Partial<ProviderInfo> = {}): ProviderInfo => ({ name, status: "ready", areas: ["any"], harnesses: ["pi", "claude-code"], ...extra });
const none: AgentModel = { harness: null, account: null, provider: null, model: null };

function place(extra: Partial<ww.Place> & { model?: AgentModel; area?: string | null; modelAlone?: boolean } = {}): ww.Place {
  const { model = none, area = null, modelAlone = false, ...rest } = extra;
  return { agent: { name: "Dev", model, area, modelAlone }, accounts: [], providers: [], harnesses, loaded: true, form: false, switchKind: false, ...rest };
}

const now = Date.parse("2026-11-15T12:00:00Z");

describe("who works: the account menu (E2)", () => {
  const p = place({
    area: "Work",
    accounts: [account("codex-work", "codex"), account("claude-perso", "claude-code", { areas: ["Personal"] })],
    providers: [
      provider("anthropic-api", { modelAlone: true, models: [{ id: "claude-sonnet-4-5" }, { id: "claude-opus-4-5" }, { id: "claude-haiku-4-5" }, { id: "whisper", speech: true }] }),
      provider("ollama-local", { local: true, harnesses: ["pi"], modelAlone: true }),
      provider("mistral-key", { status: "incomplete", problems: ["its key is not set"] }),
    ],
  });
  const rows = ww.rowsOf(p);

  it("lists one row per account or provider, subscriptions first, each with its programs and kind", () => {
    expect(rows.map((r) => [r.name, r.group, r.kind])).toEqual([
      ["codex-work", "subscriptions", "subscription"],
      ["anthropic-api", "keys", "API key"],
      ["ollama-local", "keys", "local"],
    ]);
    expect(rows.map((r) => r.worksWith)).toEqual(["works with Codex", "works with Claude Code, pi", "works with pi"]);
    expect(rows.map((r) => r.kindWords)).toEqual(["for your own use", "pay per use", "a local model on this computer"]);
  });

  it("orders a provider's programs alphabetically, the model alone last and greyed where this agent cannot be on it", () => {
    const api = rows.find((r) => r.name === "anthropic-api")!;
    expect(api.programs).toEqual([
      { harness: "claude-code", label: "Claude Code", offered: true, why: null },
      { harness: "pi", label: "pi", offered: true, why: null },
      { harness: "", label: "The model alone", offered: false, why: "not for this agent" },
    ]);
    expect(ww.programPart(api)).toBe("menu");
    expect(ww.programPart(rows[0]!)).toBe("text");
    // a provider without the model alone does not list it
    expect(ww.rowsOf(place({ providers: [provider("k")] }))[0]!.programs.map((x) => x.harness)).toEqual(["claude-code", "pi"]);
  });

  it("offers the model alone where the agent is on it, or in the agent form that may switch", () => {
    const alone = ww.rowsOf({ ...p, agent: { ...p.agent, modelAlone: true } });
    const api = alone.find((r) => r.name === "anthropic-api")!;
    expect(api.programs.filter((x) => x.offered).map((x) => x.label)).toEqual(["The model alone"]);
    expect(ww.programPart(api)).toBe("text"); // its kind is fixed: nothing to choose
    expect(api.worksWith).toBe("works with the model alone");
    // a subscription has no model alone: greyed in place
    expect(alone.find((r) => r.name === "codex-work")!.why).toBe("needs an API key");
    const form = ww.rowsOf({ ...p, form: true, switchKind: true });
    expect(form.find((r) => r.name === "anthropic-api")!.programs.every((x) => x.offered)).toBe(true);
  });

  it("gives a row its models: the default first (the provider's first beside it), speech left out", () => {
    const api = rows.find((r) => r.name === "anthropic-api")!;
    expect(api.models.map((m) => [m.value, m.label, m.detail])).toEqual([
      ["", "default model", "claude-sonnet-4-5"],
      ["claude-opus-4-5", "claude-opus-4-5", null],
      ["claude-haiku-4-5", "claude-haiku-4-5", null],
    ]);
    expect(api.short).toBe("claude-sonnet-4-5, claude-opus-4-5, claude-haiku-4-5");
    expect(rows[0]!.models.map((m) => m.label)).toEqual(["default model"]);
  });

  it("folds what is not for the area and what is not ready, with a count and why", () => {
    const folds = ww.foldsOf(p, now);
    expect(folds.area).toEqual({
      label: "Not for Work projects",
      count: 1,
      rows: [{ name: "claude-perso", kind: "subscription", why: "made for Personal", action: null, own: false, anyway: "handler run claude-perso --anyway" }],
    });
    expect(folds.notReady?.count).toBe(1);
    expect(folds.notReady?.rows[0]).toMatchObject({ name: "mistral-key", why: "Its key is not set" });
    expect(folds.areaHint).toBeNull();
    // the agent form: no command (the project's agent runs only what its area allows)
    const form = ww.foldsOf({ ...p, form: true }, now);
    expect(form.area?.rows[0]?.anyway).toBeNull();
    expect(form.areaHint).toContain("Settings → Model access");
  });

  it("says a not-ready account in its login's words", () => {
    const folds = ww.foldsOf(
      place({ accounts: [account("a", "codex", { status: "incomplete", expiresAt: "2026-11-13T12:00:00Z" }), account("b", "pi", { status: "incomplete", problems: ["not logged in"] })] }),
      now,
    );
    expect(folds.notReady?.rows.map((r) => [r.why, r.action])).toEqual([
      ["Logged out 2 days ago", "Log in again"],
      ["Not logged in", "Log in"],
    ]);
  });
});

describe("who works: the choice (E2)", () => {
  const accounts = [account("claude-perso", "claude-code"), account("codex-work", "codex")];
  const providers = [provider("anthropic-api", { models: [{ id: "sonnet" }, { id: "opus" }] })];

  it("chooses the one row that can run, and never one of two or more", () => {
    const one = place({ accounts: [accounts[1]!] });
    const rows = ww.rowsOf(one);
    expect(ww.initial(one, rows)).toEqual({ key: "account:codex-work", harness: "codex", model: "" });
    const two = place({ accounts, providers });
    expect(ww.initial(two, ww.rowsOf(two))).toBeNull();
    expect(ww.stateOf(ww.rowsOf(two), null)).toBe("ask");
    expect(ww.stateOf([], null)).toBe("none");
  });

  it("chooses the agent's own as it is, first in the menu, its model marked", () => {
    const p = place({ accounts, providers, model: { harness: "pi", account: null, provider: "anthropic-api", model: "opus" } });
    const rows = ww.rowsOf(p);
    expect(rows[0]).toMatchObject({ name: "anthropic-api", own: true });
    expect(ww.initial(p, rows)).toEqual({ key: "provider:anthropic-api", harness: "pi", model: "opus" });
    expect(rows[0]!.models.filter((m) => m.own).map((m) => m.value)).toEqual(["opus"]);
    expect(ww.sessionValue(p, rows, ww.initial(p, rows))).toBeUndefined();
    expect(ww.sessionNote(p, rows, ww.initial(p, rows))).toBeNull();
  });

  it("keeps the program when the new row has it, else its first; the model back to default", () => {
    const p = place({ accounts, providers });
    const rows = ww.rowsOf(p);
    const onClaude = ww.pickRow(p, rows, null, "account:claude-perso")!;
    const api = ww.pickRow(p, rows, { ...onClaude, model: "x" }, "provider:anthropic-api")!;
    expect(api).toEqual({ key: "provider:anthropic-api", harness: "claude-code", model: "" });
    expect(ww.pickRow(p, rows, ww.pickRow(p, rows, null, "account:codex-work"), "provider:anthropic-api")!.harness).toBe("claude-code");
    const piOpus = ww.pickModel(ww.pickProgram(rows, api, "pi"), "opus");
    expect(piOpus).toEqual({ key: "provider:anthropic-api", harness: "pi", model: "opus" });
    expect(ww.pickProgram(rows, api, "codex")).toBe(api); // not a program of that row
    expect(ww.modelLabel(api)).toBe("default model");
    expect(ww.accessOfChoice(rows, piOpus)).toEqual({ harness: "pi", account: null, provider: "anthropic-api", model: "opus" });
  });

  it("says a change is for this session only, and offers to make it the agent's own", () => {
    const p = place({ accounts, providers, model: { harness: "claude-code", account: "claude-perso", provider: null, model: null } });
    const rows = ww.rowsOf(p);
    const other = ww.pickModel(ww.pickRow(p, rows, ww.initial(p, rows), "provider:anthropic-api")!, "opus");
    expect(ww.sessionValue(p, rows, other)).toEqual({ harness: "claude-code", account: null, provider: "anthropic-api", model: "opus" });
    expect(ww.sessionNote(p, rows, other)).toEqual({ text: "opus on anthropic-api, for this session only. Dev stays on claude-perso · default model.", makeDefault: "Make it Dev's default" });
    // an account's request leaves its harness out
    const back = ww.pickRow(p, rows, other, "account:claude-perso")!;
    expect(ww.sessionValue(p, rows, back)).toBeUndefined();
  });

  it("keeps the agent's own listed when it cannot start now, with why; and before the lists are loaded", () => {
    const own = { harness: "codex", account: "codex-work", provider: null, model: null, problem: "not logged in" };
    const p = place({ accounts: [account("codex-work", "codex", { status: "incomplete" })], model: own });
    const rows = ww.rowsOf(p);
    expect(rows.map((r) => [r.name, r.problem])).toEqual([["codex-work", "not logged in"]]);
    expect(ww.foldsOf(p, now).notReady).toBeNull();
    const early = place({ loaded: false, model: own });
    expect(ww.rowsOf(early).map((r) => [r.name, r.worksWith])).toEqual([["codex-work", "works with Codex"]]);
  });

  it("takes its own row's first program when its program is not one of them (the kind just switched)", () => {
    const p = place({ providers, switchKind: true, form: true, model: { harness: null, account: null, provider: "anthropic-api", model: "opus" } });
    expect(ww.initial(p, ww.rowsOf(p))).toEqual({ key: "provider:anthropic-api", harness: "claude-code", model: "" });
  });

  it("does not offer the agent's own when its area does not allow it: it is folded", () => {
    const p = place({ area: "Work", accounts: [account("claude-perso", "claude-code", { areas: ["Personal"] })], model: { harness: "claude-code", account: "claude-perso", provider: null } });
    expect(ww.rowsOf(p)).toEqual([]);
    expect(ww.foldsOf(p, now).area?.rows[0]).toMatchObject({ name: "claude-perso", own: true });
  });
});

describe("who works: unattended on a subscription (E2, vendors' terms)", () => {
  const p = place({ accounts: [account("claude-perso", "claude-code"), account("codex-work", "codex")], providers: [provider("ollama", { local: true, harnesses: ["pi"] }), provider("anthropic-api")] });
  const rows = ww.rowsOf(p);
  const claude = ww.pickRow(p, rows, null, "account:claude-perso");

  it("recommends an API key, with a switch to one that works with the same program", () => {
    const line = ww.unattendedLine(p, rows, claude, true)!;
    expect(line.text).toBe("A subscription is for sessions you follow. An API key is recommended here.");
    expect(line.verdict).toBe("refused");
    expect(line.terms).toBeNull();
    expect(line.switchName).toBe("anthropic-api");
    expect(line.switchTo).toEqual({ key: "provider:anthropic-api", harness: "claude-code", model: "" });
  });

  it("links the terms when they are to check, and switches to another key when none has the program", () => {
    const line = ww.unattendedLine(p, rows, ww.pickRow(p, rows, null, "account:codex-work"), true)!;
    expect(line.terms).toBe("https://example.com/terms");
    expect(line.switchName).toBe("ollama");
    expect(line.switchTo?.harness).toBe("pi");
  });

  it("says nothing for a session followed, or on an API key", () => {
    expect(ww.unattendedLine(p, rows, claude, false)).toBeNull();
    expect(ww.unattendedLine(p, rows, ww.pickRow(p, rows, null, "provider:anthropic-api"), true)).toBeNull();
    const noKey = place({ accounts: [account("claude-perso", "claude-code")] });
    const r = ww.rowsOf(noKey);
    expect(ww.unattendedLine(noKey, r, ww.initial(noKey, r), true)).toMatchObject({ switchTo: null, switchName: null });
  });
});

describe("who works on an app's job (H.2): what cannot do it, greyed with why", () => {
  const p = (limits: ww.Limits) =>
    place({
      switchKind: true,
      form: true,
      limits,
      accounts: [account("claude-perso", "claude-code"), account("codex-work", "codex")],
      providers: [provider("anthropic-api", { modelAlone: true })],
    });

  it("greys the model alone for a job reaching folders, saying why", () => {
    const why = "“Writes your CV” reaches folders, schemas or hosts: it needs a program";
    const api = ww.rowsOf(p({ alone: why })).find((r) => r.name === "anthropic-api")!;
    expect(api.programs.at(-1)).toEqual({ harness: "", label: "The model alone", offered: false, why });
    expect(ww.programPart(api)).toBe("menu"); // the model alone shown greyed, so it is known
    expect(ww.rowsOf(p({})).find((r) => r.name === "anthropic-api")!.programs.at(-1)!.offered).toBe(true);
  });

  it("greys a subscription whose terms refuse runs nobody follows when an automation runs it", () => {
    const why = "its terms refuse automations' runs";
    const rows = ww.rowsOf(p({ unattended: why }));
    expect(rows.map((r) => [r.name, r.why])).toEqual([
      ["claude-perso", why], // refused (I.7)
      ["codex-work", null], // its terms to check: a warning line, not greyed
      ["anthropic-api", null],
    ]);
    expect(ww.stateOf(rows, null)).toBe("ask");
    expect(ww.rowsOf(p({})).every((r) => r.why === null)).toBe(true);
  });
});
