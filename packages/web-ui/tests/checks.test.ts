// Rule check.a-check-run-is-a-run, the web UI's side: a session of origin `check` is its agent's
// checks', left out of the agent's runs and of the open sessions found running elsewhere. The
// store and the component run as they are, on a fake daemon (whatever it is not asked here never
// answers).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushSync, mount, tick, unmount } from "svelte";
import AgentWorkspace from "../src/components/AgentWorkspace.svelte";
import type { Agent, Session } from "../src/lib/contracts.gen";
import { sessions } from "../src/lib/sessions.svelte";

const answers = vi.hoisted(() => ({}) as Record<string, (...args: unknown[]) => Promise<unknown>>);
vi.mock("../src/lib/api", () => ({
  ApiError: class extends Error {},
  api: new Proxy({}, { get: (_, name: string) => answers[name] ?? (() => new Promise(() => {})) }),
}));

const agent: Agent = {
  id: "a1",
  name: "reviewer",
  model: { harness: "claude-code", account: "claude-perso" },
  scope: "/work",
  network: "open",
  confinement: "strict",
  permissions: "bypass",
  acpUrl: "",
  connections: [],
  createdAt: "2026-09-01T00:00:00Z",
  interface: { fields: { type: "object", properties: {} }, result: { type: "object", properties: {} } },
};

const session = (id: string, origin: Session["origin"], unattended: boolean): Session =>
  ({
    id,
    agentId: agent.id,
    origin,
    unattended,
    state: "running",
    scope: "/work",
    acpUrl: `ws://localhost/v1/sessions/${id}/acp`,
    createdAt: "2026-10-31T09:00:00Z",
    lastActivityAt: "2026-10-31T09:00:00Z",
  }) as unknown as Session;

describe("a check's run in the web UI", () => {
  beforeEach(() => {
    for (const name of Object.keys(answers)) delete answers[name];
  });

  afterEach(() => {
    document.body.innerHTML = "";
  });

  it("is not one of the agent's runs", async () => {
    const page = mount(AgentWorkspace, {
      target: document.body,
      props: { agent, list: [session("run-1", "automation", true), session("check-1", "check", true)], automations: [], edit: "#/agent/a1/edit" },
    });
    await tick();
    flushSync();
    const runs = [...document.querySelectorAll<HTMLAnchorElement>('[data-testid="run-link"]')].map((a) => a.getAttribute("href"));
    expect(runs).toHaveLength(1);
    expect(runs[0]).toContain("run-1");
    unmount(page);
  });

  it("is not adopted as an open session", async () => {
    answers.sessions = async () => [session("cli-1", "cli", false), session("check-1", "check", true)];
    answers.agents = async () => [agent];
    await sessions.discover();
    expect(sessions.list.map((s) => s.key)).toEqual(["cli-1"]);
  });
});
