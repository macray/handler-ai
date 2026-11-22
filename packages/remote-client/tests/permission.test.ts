// The phone's permission sheet: an ask the computer says is safe gets Reject and Allow; any other
// (risky, or one it said nothing of) says why, its scope is picked first, then a slide confirms it (a press, then a second
// press, for a keyboard and a screen reader); Reject stays a tap.
import type { RequestPermissionOutcome } from "@agentclientprotocol/sdk";
import { flushSync, mount, unmount } from "svelte";
import { afterEach, expect, test } from "vitest";
import type { SessionAsk } from "../src/lib/remote.gen";
import { reachOf, riskOf } from "../src/lib/risk";
import PermissionSheet from "../src/views/PermissionSheet.svelte";

let shown: ReturnType<typeof mount> | null = null;

afterEach(() => {
  if (shown) unmount(shown);
  shown = null;
  document.body.innerHTML = "";
});

const OPTIONS = [
  { optionId: "once", name: "Allow once", kind: "allow_once" as const },
  { optionId: "always", name: "Always allow", kind: "allow_always" as const },
  { optionId: "no", name: "Reject", kind: "reject_once" as const },
];

function ask(kind: "execute" | "read", risk: SessionAsk["risk"] | null = kind === "read" ? "safe" : "risky"): RequestPermissionOutcome[] {
  const answered: RequestPermissionOutcome[] = [];
  const toolCall = { toolCallId: "t", title: kind === "execute" ? "npm test" : "Read notes.md", kind };
  const pending = { request: { sessionId: "s", toolCall, options: OPTIONS }, answer: (o: RequestPermissionOutcome) => answered.push(o) };
  const listed: SessionAsk | null = risk && { toolCallId: "t", kind, risk };
  shown = mount(PermissionSheet, { target: document.body, props: { pending, agent: "coder", ask: listed } });
  flushSync();
  return answered;
}

const $ = (id: string) => document.querySelector<HTMLElement>(`[data-testid="${id}"]`);
const click = (el: HTMLElement | null) => {
  el!.click();
  flushSync();
};

test("the computer says which asks are safe; one it said nothing of is risky", () => {
  const tool = { toolCallId: "t", kind: "read" };
  expect(riskOf(tool, { toolCallId: "t", risk: "safe" })).toBeNull();
  expect(riskOf(tool, { toolCallId: "t", risk: "risky" })).toContain("cannot tell");
  expect(riskOf(tool, { toolCallId: "other", risk: "safe" })).not.toBeNull(); // another ask's word
  expect(riskOf(tool, null)).not.toBeNull();
  expect(riskOf({ toolCallId: "t", kind: "execute" }, { toolCallId: "t", risk: "risky" })).toContain("command");
  // where it acts, only as far as it is known
  expect(reachOf(tool, { toolCallId: "t", risk: "safe" })).toBe("in the folder");
  expect(reachOf({ toolCallId: "t", kind: "fetch" }, null)).toBe("uses the network");
  expect(reachOf(tool, null)).toBeNull();
});

test("a safe ask: Reject and Allow, the rest a link", () => {
  const answered = ask("read");
  expect($("permission-risk")).toBeNull();
  expect($("permission-slide")).toBeNull();
  expect($("permission-reach")?.textContent).toBe("in the folder");
  const buttons = [...document.querySelectorAll<HTMLElement>('[data-testid="permission-answer"]')];
  expect(buttons.map((b) => b.textContent)).toEqual(["Reject", "Allow once", "Always allow"]);
  expect(buttons[1]!.className).toContain("allow");
  click(buttons[1]!);
  expect(answered).toEqual([{ outcome: "selected", optionId: "once" }]);
});

test("a risky ask: why, the scope first, then the slide confirms it", () => {
  const answered = ask("execute");
  expect($("permission-risk")?.textContent).toContain("command");
  expect([...document.querySelectorAll('[data-testid="permission-answer"]')].map((b) => b.textContent)).toEqual(["Reject"]);
  click(document.querySelector<HTMLElement>('[data-testid="permission-scope"][data-kind="allow_always"]'));
  const slide = $("permission-slide")!;
  expect(slide.textContent).toContain("slide to always allow");
  click(slide); // a press asks again
  expect(answered).toEqual([]);
  expect(slide.getAttribute("aria-label")).toBe("Always allow? Press again to confirm.");
  click(slide);
  expect(answered).toEqual([{ outcome: "selected", optionId: "always" }]);
});

test("an ask the computer said nothing of takes the slide", () => {
  ask("read", null);
  expect($("permission-risk")?.textContent).toContain("cannot tell");
  expect($("permission-slide")).not.toBeNull();
  expect($("permission-reach")).toBeNull();
});
