// Who works, the control (E2), mounted: what it shows from the accounts and providers handlerd
// gives: one ready chosen by itself, several asked for, the program as text or a menu, the folds.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushSync, mount, unmount } from "svelte";
import type { AccountInfo, AgentModel, ProviderInfo } from "../src/lib/contracts.gen";
import WhoWorksChoice from "../src/components/WhoWorksChoice.svelte";
import { connect } from "../src/lib/connect.svelte";

const api = vi.hoisted(() => ({
  accounts: vi.fn(async (): Promise<AccountInfo[]> => []),
  providers: vi.fn(async (): Promise<ProviderInfo[]> => []),
  harnesses: vi.fn(async () => [
    { name: "claude-code", product: "Claude Code", image: "x" },
    { name: "codex", product: "Codex", image: "x" },
    { name: "pi", product: "pi", image: "x" },
  ]),
}));
vi.mock("../src/lib/api", () => ({ api }));

const none: AgentModel = { harness: null, account: null, provider: null, model: null };
const agent = (model: AgentModel = none, area: string | null = null) => ({ id: "", name: "Dev", model, area, modelAlone: false });
const account = (name: string, harness: string, extra: Partial<AccountInfo> = {}): AccountInfo => ({ name, harness, status: "ready", areas: ["any"], ...extra });
const provider = (name: string, extra: Partial<ProviderInfo> = {}): ProviderInfo => ({ name, status: "ready", areas: ["any"], harnesses: ["pi", "claude-code"], ...extra });

describe("the Who works control", () => {
  let target: HTMLElement;
  let view: ReturnType<typeof mount> | null = null;
  beforeEach(() => {
    target = document.createElement("div");
    document.body.append(target);
  });
  afterEach(() => {
    if (view) unmount(view);
    view = null;
    target.remove();
  });

  async function show(accounts: AccountInfo[], providers: ProviderInfo[], props: Record<string, unknown> = {}) {
    api.accounts.mockResolvedValue(accounts);
    api.providers.mockResolvedValue(providers);
    view = mount(WhoWorksChoice, { target, props: { agent: agent(), ...props } });
    await vi.waitFor(() => {
      flushSync();
      expect(api.providers).toHaveBeenCalled();
    });
    await new Promise((r) => setTimeout(r));
    flushSync();
  }
  const text = (id: string) => target.querySelector(`[data-testid="${id}"]`)?.textContent?.trim() ?? null;
  const open = (id: string) => {
    (target.ownerDocument.querySelector(`[data-testid="${id}"]`) as HTMLButtonElement).click();
    flushSync();
  };
  const all = (id: string) => [...document.querySelectorAll(`[data-testid="${id}"]`)].map((x) => x.textContent?.replace(/\s+/g, " ").trim());

  it("chooses the one that is ready, its program as text, the model at its default", async () => {
    const onchange = vi.fn();
    await show([account("codex-work", "codex")], [], { own: true, onchange });
    expect(text("model-choice-access")).toContain("codex-work");
    const program = target.querySelector('[data-testid="model-choice-harness"]');
    expect(program?.tagName).toBe("SPAN"); // text, not a menu
    expect(program?.textContent?.trim()).toBe("Codex");
    expect(text("model-choice-model-name")).toBe("default model");
    expect(onchange).toHaveBeenCalledWith({ harness: "codex", account: "codex-work", provider: null, model: null });
  });

  it("asks when two or more could run it, and picks none", async () => {
    const onchange = vi.fn();
    await show([account("codex-work", "codex")], [provider("anthropic-api")], { own: true, onchange });
    expect(target.querySelector(".who")?.getAttribute("data-state")).toBe("ask");
    expect(text("model-choice-access")).toBe("Choose an account");
    expect(onchange).not.toHaveBeenCalled();
    open("model-choice-access");
    expect(all("model-choice-access-row")).toEqual(["C codex-work works with Codex · for your own use", "A anthropic-api works with Claude Code, pi · pay per use"]);
    (document.querySelectorAll('[data-testid="model-choice-access-row"]')[1] as HTMLButtonElement).click();
    flushSync();
    expect(onchange).toHaveBeenLastCalledWith({ harness: "claude-code", account: null, provider: "anthropic-api", model: null });
    // several programs: a menu, alphabetical
    const program = target.querySelector('[data-testid="model-choice-harness"]');
    expect(program?.tagName).toBe("BUTTON");
    open("model-choice-harness");
    expect(all("model-choice-program")).toEqual(["Claude Code", "pi"]);
  });

  it("folds what is not for the area and what is not ready, with a count and why", async () => {
    await show(
      [account("claude-perso", "claude-code", { areas: ["Personal"] }), account("codex-work", "codex"), account("codex-old", "codex", { status: "incomplete", problems: ["not logged in"] })],
      [],
      { agent: agent({ harness: "codex", account: "codex-work", provider: null, model: null }, "Work") },
    );
    open("model-choice-access");
    expect(document.querySelector('[data-testid="model-choice-hidden"] summary')?.textContent).toContain("Not for Work projects: 1");
    expect(all("who-works-folded")).toEqual([
      "claude-perso · made for Personal. Starting it here anyway is CLI only: handler run claude-perso --anyway",
      "codex-old · Not logged in Log in",
    ]);
    expect(document.querySelector('[data-testid="model-choice-not-ready"] summary')?.textContent).toContain("Not ready: 1");
    expect(all("who-works-connect")[0]).toBe("Connect another…");
  });

  it("says a change is for this session only; an unattended run on a subscription is recommended an API key", async () => {
    const own = { harness: "claude-code", account: "claude-perso", provider: null, model: null };
    await show([account("claude-perso", "claude-code")], [provider("anthropic-api")], { agent: { ...agent(own), id: "a1" }, unattended: true, ondefault: vi.fn(async () => {}) });
    expect(text("who-works-unattended")).toContain("An API key is recommended here.");
    open("who-works-unattended-switch");
    expect(text("who-works-unattended")).toBeNull();
    expect(text("model-choice-access")).toContain("anthropic-api");
    expect(target.querySelector('[data-testid="model-choice-changed"]')).not.toBeNull();
    open("model-choice-access");
    expect(all("model-choice-session-only")[0]).toContain("default model on anthropic-api, for this session only. Dev stays on claude-perso · default model.");
  });

  it("says when nothing can run here, its Connect opened over the page", async () => {
    await show([], []);
    expect(text("model-choice-none")).toBe("Connect a model to start");
    open("model-choice-none");
    expect(connect.current?.kind).toBe("both");
    connect.close();
  });

  it("chooses the one Connect another… made, over the page", async () => {
    const onchange = vi.fn();
    await show([account("codex-work", "codex")], [provider("anthropic-api")], { own: true, onchange });
    expect(text("model-choice-access")).toBe("Choose an account");
    open("model-choice-access");
    open("who-works-connect");
    expect(connect.current?.kind).toBe("both");
    expect(document.querySelector('[data-testid="who-works-connect"]')).toBeNull(); // its menu closed
    api.providers.mockResolvedValue([provider("anthropic-api"), provider("local-llama", { harnesses: ["pi"] })]);
    connect.done({ kind: "provider", name: "local-llama" });
    expect(connect.current).toBeNull();
    await vi.waitFor(() => {
      flushSync();
      expect(text("model-choice-access")).toContain("local-llama");
    });
    expect(onchange).toHaveBeenLastCalledWith({ harness: "pi", account: null, provider: "local-llama", model: null });
  });

  it("asks for an API key from its unattended line, over the page", async () => {
    await show([account("claude-perso", "claude-code")], [], { agent: { ...agent({ harness: "claude-code", account: "claude-perso", provider: null, model: null }), id: "a2" }, unattended: true });
    open("who-works-unattended-connect");
    expect(connect.current?.kind).toBe("provider");
    connect.close();
  });
});
