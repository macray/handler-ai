// A disabled main action says why, with its fix (E1): what is missing → the reason and the fix,
// and the sentence beside the button, whose fix brings the control into view or goes to its page.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushSync, mount, unmount } from "svelte";
import DisabledReason from "../src/components/DisabledReason.svelte";
import { noAccess } from "../src/lib/access";
import { connect } from "../src/lib/connect.svelte";
import { helperBlocked, installBlocked, NO_MODEL, PAIR_BLOCKED, unattendedBlocked, type Blocked } from "../src/lib/blocked";
import type { AddonInfo, AgentDefinition } from "../src/lib/contracts.gen";
import type { Choice } from "../src/lib/setup";

const PICKER = '[data-testid="model-choice-access"]';
const def = (extra: Partial<AgentDefinition> = {}): AgentDefinition => ({ agentName: "plan builder", ...extra });
const choice = (extra: Partial<Choice> = {}): Choice => ({ model: noAccess(), bindings: {}, knowledge: {}, ...extra });
const account = { ...noAccess(), account: "claude-perso" };
const tool = (name: string, settings = false): AddonInfo => ({ name, directory: `/t/${name}`, ...(settings ? { settings: [{ name: "store" }] } : {}) }) as AddonInfo;

describe("a helper's Turn on", () => {
  it("asks who works first, Choose opening its picker (Model access when it is not there)", () => {
    expect(helperBlocked(def(), choice(), [], PICKER)).toEqual({
      reason: "Choose who works first",
      fix: { label: "Choose", focus: PICKER, open: true, href: "#/settings/models" },
    });
  });

  it("asks a tool not installed before anything else, from Library → Tools", () => {
    const b = helperBlocked(def({ addons: ["shopify"] }), choice(), [], PICKER);
    expect(b?.reason).toBe("Install the shopify tool first");
    expect(b?.fix).toEqual({ label: "Library → Tools", href: "#/library/tools/more" });
  });

  it("then a connection to a tool, then a notes folder; nothing once all is given", () => {
    const d = def({ addons: ["shopify"], knowledge: ["recipes"] });
    const tools = [tool("shopify", true)];
    expect(helperBlocked(d, choice({ model: account, bindings: { shopify: "" }, knowledge: { recipes: "" } }), tools, PICKER)?.reason).toBe("Connect the shopify tool first");
    expect(helperBlocked(d, choice({ model: account, bindings: { shopify: "shop" }, knowledge: { recipes: "" } }), tools, PICKER)).toEqual({ reason: "It needs a notes folder for recipes" });
    expect(helperBlocked(d, choice({ model: account, bindings: { shopify: "shop" }, knowledge: { recipes: "/n/recipes" } }), tools, PICKER)).toBeNull();
  });

  it("on the model alone, a provider is who works", () => {
    const alone = def({ modelAlone: true });
    expect(helperBlocked(alone, choice({ model: account }), [], PICKER)?.reason).toBe("Choose who works first");
    expect(helperBlocked(alone, choice({ model: { ...noAccess(), provider: "mistral" } }), [], PICKER)).toBeNull();
  });
});

describe("an app's Install", () => {
  it("says all that is still to choose, Choose going to the first", () => {
    expect(installBlocked([])).toBeNull();
    expect(installBlocked([{ text: "Planner's folder", at: "#a" }, { text: "the secret TOKEN", at: "#b" }])).toEqual({
      reason: "Still to choose:",
      what: "Planner's folder, the secret TOKEN",
      fix: { label: "Choose", focus: "#a" },
    });
  });
});

describe("the sentence beside a disabled button", () => {
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
    vi.restoreAllMocks();
  });

  const show = (blocked: Blocked) => {
    view = mount(DisabledReason, { target, props: { blocked } });
    flushSync();
    return target.querySelector<HTMLElement>('[data-testid="disabled-fix"]');
  };

  it("says the reason and what is missing, neutral, never amber", () => {
    show({ reason: "Still to choose:", what: "Planner's folder", fix: { label: "Choose", focus: "#x" } });
    const reason = target.querySelector('[data-testid="disabled-reason"]')!;
    expect(reason.textContent?.replace(/\s+/g, " ").trim()).toBe("Still to choose: Planner's folder · Choose");
    expect(reason.innerHTML).not.toContain("warn");
  });

  it("brings its step's control into view and focuses it", () => {
    const step = document.createElement("div");
    step.id = "gateway";
    step.innerHTML = '<label>Address</label><input id="gateway-url">';
    document.body.append(step);
    const input = step.querySelector("input")!;
    input.scrollIntoView = vi.fn();
    show(PAIR_BLOCKED)!.click(); // Step 1 ↑: the gateway's address
    expect(document.activeElement).toBe(input);
    expect(input.scrollIntoView).toHaveBeenCalled();
    step.remove();
  });

  it("opens a picker when asked to", () => {
    const chip = document.createElement("button");
    chip.dataset.testid = "model-choice-access";
    chip.scrollIntoView = vi.fn();
    const opened = vi.fn();
    chip.addEventListener("click", opened);
    document.body.append(chip);
    const fix = show({ reason: "Choose who works first", fix: { label: "Choose", focus: PICKER, open: true, href: "#/settings/models" } })!;
    const event = new MouseEvent("click", { bubbles: true, cancelable: true });
    fix.dispatchEvent(event);
    expect(opened).toHaveBeenCalled();
    expect(event.defaultPrevented).toBe(true); // stays on the page
    chip.remove();
  });

  it("goes to the fix's page when it is elsewhere", () => {
    const fix = show({ reason: "Install the shopify tool first", fix: { label: "Library → Tools", href: "#/library/tools/more" } })!;
    expect(fix.tagName).toBe("A");
    expect(fix.getAttribute("href")).toBe("#/library/tools/more");
  });

  it("opens its Connect over the page when the fix is connecting a model", () => {
    const fix = show(NO_MODEL)!;
    expect(fix.tagName).toBe("BUTTON");
    expect(fix.textContent).toBe("Connect…");
    fix.click();
    expect(connect.current?.kind).toBe("both");
    connect.close();
  });
});

describe("an app's suggested automation its account cannot run (H.1, I.7)", () => {
  const accounts = [
    { name: "max", harness: "claude-code" },
    { name: "plus", harness: "codex" },
  ];
  const login = (unattended: "allowed" | "check-terms" | "refused") => ({ subscription: "S", unattended }) as never;
  const harnesses = [
    { name: "claude-code", login: login("refused") },
    { name: "codex", login: login("check-terms") },
  ];

  it("is blocked on an account whose terms refuse runs nobody follows, its fix Who works", () => {
    expect(unattendedBlocked({ account: "max" }, accounts, harnesses, PICKER)).toEqual({
      reason: "max's terms don't allow runs nobody follows",
      fix: { label: "Choose an API key in Who works", focus: PICKER, open: true },
    });
  });

  it("is not on terms to check, a provider, or no choice yet", () => {
    expect(unattendedBlocked({ account: "plus" }, accounts, harnesses, PICKER)).toBeNull();
    expect(unattendedBlocked({ provider: "anthropic", harness: "claude-code" } as never, accounts, harnesses, PICKER)).toBeNull();
    expect(unattendedBlocked(null, accounts, harnesses, PICKER)).toBeNull();
  });
});
