// Nudges (H.17) in the web UI: the choices of Reminders and what each means, the app's
// reminders in words, which messages the bell counts; and an open nudge's card, mounted on a fake
// daemon: what was said fills its form and never sends it (rule nudge.voice-fills-never-sends),
// Send runs the action with the nudge's id, Dismiss dismisses it.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushSync, mount, tick, unmount } from "svelte";
import type { InboxMessage } from "../src/lib/contracts.gen";
import { SETTINGS, SETTING_WORDS, durationWords, endedWords, isOpen, remindWords, settingMeaning, waitsForYou, whenWords } from "../src/lib/nudges";

const api = vi.hoisted(() => ({
  transcribe: vi.fn(),
  fillNudge: vi.fn(),
  act: vi.fn(),
  actionRun: vi.fn(),
  dismissNudge: vi.fn(),
  openNudge: vi.fn(),
  setNudgeWhen: vi.fn(),
}));
vi.mock("../src/lib/api", () => ({ api }));

const { default: NudgeCard } = await import("../src/components/NudgeCard.svelte");

function message(nudge: Partial<NonNullable<InboxMessage["nudge"]>> = {}, more: Partial<InboxMessage> = {}): InboxMessage {
  return {
    id: "n1",
    source: "app",
    name: "worktracker",
    app: "worktracker",
    person: "owner",
    title: "Add what you did today",
    at: "2026-11-12T18:00:00Z",
    kind: "nudge",
    nudge: { name: "daily-log", state: "open", alerts: 1, ...nudge },
    ...more,
  };
}

describe("a nudge's reminders", () => {
  it("offers three choices, each said with what it means for this nudge", () => {
    // If this fails: you cannot tell what "As the app says" does, or "No reminders" is hidden.
    expect(SETTINGS).toEqual(["default", "once", "silent"]);
    expect(SETTINGS.map((s) => SETTING_WORDS[s])).toEqual(["As the app says", "No reminders", "Never alert me"]);
    const daily = { every: "1d", times: 2 };
    expect(settingMeaning("default", daily)).toBe("reminds you every day, 2 times");
    expect(settingMeaning("once", daily)).toBe("it alerts you once");
    expect(settingMeaning("silent", daily)).toBe("it comes to your inbox quietly");
    expect(settingMeaning("default", null)).toBe("alerts you once, no reminders");
  });

  it("says the app's schedule in words", () => {
    expect(durationWords("30m")).toBe("30 minutes");
    expect(durationWords("1h")).toBe("an hour");
    expect(durationWords("2h")).toBe("2 hours");
    expect(durationWords("1d")).toBe("a day");
    expect(durationWords("3d")).toBe("3 days");
    expect(remindWords({ every: "2h", times: 2 })).toBe("reminds you every 2 hours, 2 times");
    expect(remindWords({ every: "90m", times: 1 })).toBe("reminds you once more after 90 minutes");
    expect(remindWords({ every: "1h" })).toBe("reminds you once more after an hour");
    expect(remindWords(null)).toBe("alerts you once, no reminders");
  });
});

describe("when Handler sends a nudge", () => {
  it("says its time in words", () => {
    expect(whenWords({ at: "16:00", days: ["fri"] })).toBe("Fridays at 16:00");
    expect(whenWords({ at: "16:00", days: ["fri", "mon"] })).toBe("Mondays and Fridays at 16:00");
    expect(whenWords({ at: "09:00" })).toBe("every day at 09:00");
    expect(whenWords({ at: "08:30", days: ["mon", "tue", "wed", "thu", "fri"] })).toBe("weekdays at 08:30");
    expect(whenWords({ every: "1d" })).toBe("every day");
    expect(whenWords({ every: "2d" })).toBe("every 2 days");
    expect(whenWords({ every: "30m" })).toBe("every 30 minutes");
  });
});

describe("a nudge in the inbox", () => {
  it("is open until it ends, and says how it ended", () => {
    expect(isOpen(message())).toBe(true);
    expect(isOpen(message({ state: "done" }))).toBe(false);
    expect(isOpen({ ...message(), kind: "message", nudge: null })).toBe(false);
    expect(endedWords({ name: "x", state: "done" })).toBe("Done");
    expect(endedWords({ name: "x", state: "expired" })).toBe("Expired");
    expect(endedWords({ name: "x", state: "open" })).toBeNull();
  });

  it("waits for you on the bell while open and unread, as a failure does", () => {
    expect(waitsForYou(message())).toBe(true);
    expect(waitsForYou(message({}, { read: true }))).toBe(false);
    expect(waitsForYou(message({ state: "dismissed" }))).toBe(false);
    expect(waitsForYou({ ...message(), kind: "message", nudge: null, status: "failed" })).toBe(true);
    expect(waitsForYou({ ...message(), kind: "message", nudge: null, status: "ok" })).toBe(false);
  });
});

// ── the card ───────────────────────────────────────────────────────────

class FakeRecorder {
  static isTypeSupported = (type: string) => type.startsWith("audio/webm");
  state: "inactive" | "recording" = "inactive";
  mimeType = "audio/webm;codecs=opus";
  ondataavailable: ((e: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;
  start(): void {
    this.state = "recording";
  }
  stop(): void {
    this.state = "inactive";
    this.ondataavailable?.({ data: new Blob(["said"], { type: this.mimeType }) });
    this.onstop?.();
  }
}

async function settle(): Promise<void> {
  for (let i = 0; i < 10; i++) await Promise.resolve();
  await tick();
  flushSync();
}

const $ = <T extends Element = HTMLElement>(id: string) => document.querySelector<T>(`[data-testid="${id}"]`);

const FORM = {
  type: "object",
  properties: { done: { type: "string", title: "What you did" }, hours: { type: "number" } },
  required: ["done"],
};

describe("an open nudge's card", () => {
  let card: ReturnType<typeof mount> | null = null;
  const changed = vi.fn();

  function show(m: InboxMessage, listens = true): void {
    card = mount(NudgeCard, {
      target: document.body,
      props: { m, nudge: m.nudge!, setting: "default", listens, answer: undefined, onran: () => {}, onchanged: changed, onsetting: async () => {} },
    });
    flushSync();
  }

  beforeEach(() => {
    for (const f of Object.values(api)) f.mockReset();
    changed.mockReset();
    vi.stubGlobal("MediaRecorder", FakeRecorder);
    Object.defineProperty(navigator, "mediaDevices", { value: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [{ stop: () => {} }] }) }, configurable: true });
  });

  afterEach(() => {
    if (card) unmount(card);
    card = null;
    vi.unstubAllGlobals();
  });

  it("draws the action's form filled with what the app drafted", () => {
    show(message({ action: "log", form: FORM, fields: { done: "Reviewed the PR" } }));
    expect($<HTMLInputElement>("run-field-done")!.value).toBe("Reviewed the PR");
    expect($("nudge-send")).not.toBeNull();
    expect($("nudge-open")).toBeNull();
  });

  it("fills the form from what was said, and never sends it", async () => {
    api.transcribe.mockResolvedValue({ text: "I fixed the login and spent 3 hours" });
    api.fillNudge.mockResolvedValue({ said: "I fixed the login and spent 3 hours", fields: { done: "Fixed the login", hours: 3 }, question: "Which project?" });
    show(message({ action: "log", form: FORM, fields: { done: "Reviewed the PR" } }));

    $<HTMLButtonElement>("nudge-mic")!.click();
    await settle();
    expect($("nudge-listening")).not.toBeNull();
    $<HTMLButtonElement>("nudge-mic")!.click();
    await settle();

    expect(api.fillNudge).toHaveBeenCalledWith("n1", "I fixed the login and spent 3 hours", expect.any(String));
    expect($<HTMLInputElement>("run-field-done")!.value).toBe("Fixed the login");
    expect($("nudge-question")!.textContent).toBe("Which project?");
    expect(api.act).not.toHaveBeenCalled();
  });

  it("sends the action with the nudge's id", async () => {
    api.act.mockResolvedValue({ app: "worktracker", action: "log", state: "succeeded", result: { status: "ok", summary: "Logged." } });
    show(message({ action: "log", form: FORM, fields: { done: "Reviewed the PR" } }));
    $<HTMLFormElement>("nudge-form")!.requestSubmit();
    await settle();
    expect(api.act).toHaveBeenCalledWith("worktracker", "log", { done: "Reviewed the PR" }, "n1");
    expect($("action-answer")!.textContent).toContain("Logged.");
    expect(changed).toHaveBeenCalled();
  });

  it("offers no microphone, but where to set one up, when voice is off", () => {
    show(message({ action: "log", form: FORM }), false);
    expect($("nudge-mic")).toBeNull();
    expect($("nudge-mic-setup")).not.toBeNull();
  });

  it("opens a page's nudge, and dismisses", async () => {
    api.dismissNudge.mockResolvedValue(message({ state: "dismissed" }));
    show(message({ open: "/log" }));
    expect($("nudge-form")).toBeNull();
    expect($("nudge-open")).not.toBeNull();
    $<HTMLButtonElement>("nudge-dismiss")!.click();
    await settle();
    expect(api.dismissNudge).toHaveBeenCalledWith("n1");
    expect(changed).toHaveBeenCalled();
  });

  it("says what the app said happens once it expired", () => {
    show(message({ state: "expired", ifIgnored: "The day stays empty in your log." }));
    expect($("nudge-if-ignored")!.textContent).toContain("The day stays empty in your log.");
    expect($("nudge-dismiss")).toBeNull();
  });

  it("says when it comes, and changes it to yours or back to the app's", async () => {
    api.setNudgeWhen.mockResolvedValue({});
    show(message({ action: "log", form: FORM, when: { at: "16:00", days: ["fri"] } }));
    expect($("nudge-when-words")!.textContent).toContain("Fridays at 16:00");
    expect($("nudge-when-app")).toBeNull();
    $<HTMLButtonElement>("nudge-when-change")!.click();
    flushSync();
    $<HTMLButtonElement>("schedule-every")!.click();
    flushSync();
    $<HTMLButtonElement>("nudge-when-save")!.click();
    await settle();
    expect(api.setNudgeWhen).toHaveBeenCalledWith("worktracker", "daily-log", { every: "1d" });
    expect(changed).toHaveBeenCalled();
    unmount(card!);
    show(message({ action: "log", form: FORM, when: { at: "16:00", days: ["fri"] }, ownWhen: { every: "2d" } }));
    expect($("nudge-when-words")!.textContent).toContain("every 2 days (yours; the app says Fridays at 16:00)");
    $<HTMLButtonElement>("nudge-when-app")!.click();
    await settle();
    expect(api.setNudgeWhen).toHaveBeenLastCalledWith("worktracker", "daily-log", null);
  });

  it("says no time for a nudge its app sends itself", () => {
    show(message({ action: "log", form: FORM }));
    expect($("nudge-when")).toBeNull();
  });
});
