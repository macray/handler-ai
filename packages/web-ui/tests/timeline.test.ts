// The timeline while an answer streams: its message is rendered (markdown, sanitized: tens of ms
// for a long one) a few times a second, not on each chunk; a session kept a core busy that way.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushSync, mount, unmount } from "svelte";
import type { SessionUpdate } from "@agentclientprotocol/sdk";
import Timeline from "@handler/acp-view/components/Timeline.svelte";
import PermissionPrompt from "@handler/acp-view/components/PermissionPrompt.svelte";
import type { PendingPermission } from "@handler/acp-view/lib/connection.svelte";
import { SessionState } from "@handler/acp-view/lib/session.svelte";
import * as render from "@handler/acp-view/lib/render";

const chunk = (text: string) => ({ sessionUpdate: "agent_message_chunk", content: { type: "text", text } }) as SessionUpdate;

describe("an answer being streamed", () => {
  let target: HTMLElement;
  beforeEach(() => {
    vi.useFakeTimers();
    target = document.createElement("div");
    document.body.append(target);
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    target.remove();
  });

  it("is rendered a few times a second, not on each chunk, and whole at once when it ends", () => {
    const session = new SessionState();
    session.addUserPrompt("write a lot");
    const rendered = vi.spyOn(render, "markdown");
    const view = mount(Timeline, { target, props: { session, busy: true } });
    const message = () => target.querySelector('[data-testid="agent-message"]')?.textContent ?? "";
    for (let i = 0; i < 200; i++) {
      session.apply(chunk(`word${i} `));
      flushSync();
    }
    expect(rendered.mock.calls.length).toBeLessThan(5); // not 200
    expect(message()).toContain("word0");
    vi.advanceTimersByTime(200);
    flushSync();
    expect(message()).toContain("word199"); // caught up
    unmount(view);
    const ended = mount(Timeline, { target, props: { session, busy: false } }); // its turn ended
    expect(target.querySelectorAll('[data-testid="agent-message"]')[0]?.textContent).toContain("word199");
    unmount(ended);
  });
});

describe("a Grid tile's body", () => {
  let target: HTMLElement;
  beforeEach(() => {
    target = document.createElement("div");
    document.body.append(target);
  });
  afterEach(() => target.remove());
  const shown = (id: string) => target.querySelectorAll(`[data-testid="${id}"]`).length;
  const ask = (answered: string[] = []): PendingPermission => ({
    request: {
      sessionId: "s",
      toolCall: { toolCallId: "t1", title: "rm -rf dist/", kind: "execute", rawInput: { command: "rm -rf dist/", description: "Clear the old build" } },
      options: [
        { optionId: "always", name: "Always Allow", kind: "allow_always" },
        { optionId: "yes", name: "Allow", kind: "allow_once" },
        { optionId: "no", name: "Reject", kind: "reject_once" },
      ],
    },
    answer: (o) => answered.push(o.outcome === "selected" ? o.optionId : "cancelled"),
  });

  it("asks with what, why and command, Reject | Allow first and equal, then the remembered answer", () => {
    const answered: string[] = [];
    const view = mount(PermissionPrompt, { target, props: { pending: ask(answered) } });
    expect(target.querySelector('[data-testid="permission-why"]')?.textContent).toContain("Clear the old build");
    expect(target.querySelector('[data-testid="permission-what"]')?.textContent).toBe("rm -rf dist/");
    const pair = [...target.querySelectorAll<HTMLButtonElement>(".pair button")];
    expect(pair.map((b) => b.textContent?.trim())).toEqual(["Reject", "Allow"]);
    const all = [...target.querySelectorAll<HTMLButtonElement>('[data-testid="permission-answer"]')];
    expect(all.map((b) => b.dataset.kind)).toEqual(["reject_once", "allow_once", "allow_always"]);
    all[1]!.click();
    expect(answered).toEqual(["yes"]);
    unmount(view);
  });

  it("on the phone, names the agent, what it touches and where it runs", () => {
    const pending = ask();
    pending.request.toolCall.locations = [{ path: "/home/me/shop/dist" }];
    const place = { project: "shop-theme", folder: "/home/me/shop" };
    const view = mount(PermissionPrompt, { target, props: { pending, root: "/home/me/shop", agent: "Dev", place } });
    expect(target.querySelector(".head")?.textContent).toContain("Dev asks to run a command");
    expect(target.querySelector('[data-testid="permission-touches"]')?.textContent).toBe("Touches dist");
    expect(target.querySelector('[data-testid="permission-where"]')?.textContent?.trim()).toBe("In shop-theme · ~/shop");
    unmount(view);
    const desk = mount(PermissionPrompt, { target, props: { pending: ask() } });
    expect(target.querySelector(".head")?.textContent).toContain("The agent asks");
    expect(shown("permission-where")).toBe(0);
    unmount(desk);
  });
});
