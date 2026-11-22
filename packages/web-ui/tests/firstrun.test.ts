// Setting Handler up (E1): which steps are done, read from what handlerd lists (nothing stored),
// the next one, and where the menu's Set up Handler card shows: until the first project exists,
// never on Projects (the steps are large there).
import { describe, expect, it, vi } from "vitest";
import type { AccountInfo, ProviderInfo, WorkFolderInfo } from "../src/lib/contracts.gen";
import { firstRun, setupFacts, setupOf, showsCard, STEP_NAMES } from "../src/lib/firstrun.svelte";

const answers = vi.hoisted(() => ({}) as Record<string, (...args: unknown[]) => Promise<unknown>>);
vi.mock("../src/lib/api", () => ({
  ApiError: class extends Error {},
  api: new Proxy({}, { get: (_, name: string) => answers[name] ?? (() => new Promise(() => {})) }),
}));

const account = (name: string, status: AccountInfo["status"] = "ready"): AccountInfo => ({ name, status });
const provider = (name: string, extra: Partial<ProviderInfo> = {}): ProviderInfo => ({ name, status: "ready", ...extra }) as ProviderInfo;
const folder = (root: string, exists = true): WorkFolderInfo => ({ root, path: root, exists });

describe("the set-up's steps", () => {
  it("starts at connecting a model, none done", () => {
    const s = setupOf(setupFacts([], [], [folder("~/code", false)]));
    expect(s).toEqual({ model: false, folders: false, next: "model", done: 0, total: 3 });
  });

  it("counts a work folder that exists as step 2 done, even before a model", () => {
    const s = setupOf(setupFacts([], [], [folder("~/code")]));
    expect(s).toMatchObject({ model: false, folders: true, next: "model", done: 1 });
  });

  it("goes to the folder, then to the first project, once a model is ready", () => {
    expect(setupOf(setupFacts([account("claude-perso")], [], [folder("~/code", false)])).next).toBe("folders");
    const s = setupOf(setupFacts([account("claude-perso")], [], [folder("~/code")]));
    expect(s).toMatchObject({ next: "project", done: 2 });
    expect(STEP_NAMES[s.next]).toBe("Your first project");
  });

  it("does not count an account not logged in, nor a local model server not reached", () => {
    const f = setupFacts(
      [account("codex-work", "incomplete")],
      [provider("ollama", { local: true, reached: { ok: false } } as Partial<ProviderInfo>), provider("openrouter")],
      [folder("~/code"), folder("/srv", false)],
    );
    expect(f).toEqual({ ready: ["openrouter"], unready: 2, unreached: ["ollama"], roots: ["~/code", "/srv"], existing: ["~/code"] });
  });
});

describe("the menu's Set up Handler card", () => {
  it("shows on every page but Projects while there is no project", () => {
    expect(showsCard(true, 0, true, "library")).toBe(true);
    expect(showsCard(true, 0, true, "settings")).toBe(true);
    expect(showsCard(true, 0, true, "projects")).toBe(false);
  });

  it("is gone once a project exists, and waits until both are read", () => {
    expect(showsCard(true, 1, true, "library")).toBe(false);
    expect(showsCard(false, 0, true, "library")).toBe(false);
    expect(showsCard(true, 0, false, "library")).toBe(false);
  });
});

describe("reading the facts again", () => {
  it("drops an answer to a read asked for before the last one", async () => {
    // If this fails: a slow answer to a page's first read undoes a newer one (a model connected
    // since): the card says a step done is still to do.
    let older: (accounts: AccountInfo[]) => void = () => {};
    answers.accounts = () => new Promise<AccountInfo[]>((resolve) => (older = resolve));
    answers.providers = async () => [];
    answers.folders = async () => ({ folders: [] });
    firstRun.load();
    answers.accounts = async () => [account("claude-perso")];
    firstRun.load();
    await vi.waitFor(() => expect(firstRun.facts?.ready).toEqual(["claude-perso"]));
    older([]);
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(firstRun.facts?.ready).toEqual(["claude-perso"]);
  });
});
