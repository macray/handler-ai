// Rule voice.nothing-listens-until-pressed, the web UI's side: Ask's page opens no microphone until
// it is pressed, a recording stops itself at a minute and is sent, Esc drops it unsent. The page
// and `lib/voice.ts` run as they are, on a fake microphone and a fake daemon.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushSync, mount, tick, unmount } from "svelte";
import AskPanel from "../src/components/AskPanel.svelte";
import { MAX_SECONDS } from "../src/lib/voice";

const api = vi.hoisted(() => ({
  apps: vi.fn(),
  handlerNeeds: vi.fn(),
  voice: vi.fn(),
  transcribe: vi.fn(),
  ask: vi.fn(),
}));
vi.mock("../src/lib/api", () => ({ api }));

const microphone = { getUserMedia: vi.fn(), stopped: 0 };

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

const mic = () => document.querySelector<HTMLButtonElement>('[data-testid="ask-mic"]');

describe("Ask's microphone", () => {
  let page: ReturnType<typeof mount>;

  beforeEach(async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date"] });
    localStorage.clear();
    microphone.stopped = 0;
    microphone.getUserMedia.mockReset().mockResolvedValue({ getTracks: () => [{ stop: () => microphone.stopped++ }] });
    vi.stubGlobal("MediaRecorder", FakeRecorder);
    Object.defineProperty(navigator, "mediaDevices", { value: { getUserMedia: microphone.getUserMedia }, configurable: true });
    api.apps.mockResolvedValue([{ name: "planner", current: true, askable: true, actions: [{ name: "add" }] }]);
    api.handlerNeeds.mockResolvedValue([{ name: "ask-router", agentId: "router" }]);
    api.voice.mockResolvedValue({ model: "whisper", problem: null });
    api.transcribe.mockReset().mockResolvedValue({ text: "" });
    api.ask.mockReset();
    page = mount(AskPanel, { target: document.body });
    await settle();
  });

  afterEach(() => {
    unmount(page);
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("opens nothing until pressed", async () => {
    expect(mic()?.getAttribute("aria-label")).toBe("speak");
    await vi.advanceTimersByTimeAsync(10 * 60_000);
    expect(microphone.getUserMedia).not.toHaveBeenCalled();

    mic()!.click();
    await settle();
    expect(microphone.getUserMedia).toHaveBeenCalledOnce();
    expect(document.querySelector('[data-testid="ask-listening"]')).not.toBeNull();
  });

  it("stops itself at a minute and sends what was said", async () => {
    mic()!.click();
    await settle();
    await vi.advanceTimersByTimeAsync(MAX_SECONDS * 1000 - 1);
    expect(api.transcribe).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(1);
    await settle();
    expect(MAX_SECONDS).toBe(60);
    expect(api.transcribe).toHaveBeenCalledOnce();
    expect(microphone.stopped).toBe(1);
    expect(document.querySelector('[data-testid="ask-listening"]')).toBeNull();
  });

  it("drops it unsent on Esc", async () => {
    mic()!.click();
    await settle();
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    await settle();
    expect(microphone.stopped).toBe(1);
    expect(document.querySelector('[data-testid="ask-listening"]')).toBeNull();

    await vi.advanceTimersByTimeAsync(MAX_SECONDS * 1000);
    await settle();
    expect(api.transcribe).not.toHaveBeenCalled();
  });
});
