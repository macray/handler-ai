// The projects store takes the daemon's list as it is (projects made elsewhere show). The store
// runs as it is, on a fake daemon.
import { beforeEach, expect, it, vi } from "vitest";
import type { Project } from "../src/lib/contracts.gen";
import { projects } from "../src/lib/projects.svelte";

const answers = vi.hoisted(() => ({}) as Record<string, (...args: unknown[]) => Promise<unknown>>);
vi.mock("../src/lib/api", () => ({
  ApiError: class extends Error {},
  api: new Proxy({}, { get: (_, name: string) => answers[name] ?? (() => new Promise(() => {})) }),
}));

const project = (): Project => ({ id: "p1", name: "shop" }) as Project;

beforeEach(() => {
  projects.list = [project()];
});

it("a list asked for with no change made since is taken as it is", async () => {
  // If this fails: the menu misses projects made elsewhere (another tab, the CLI).
  answers.projects = async () => [project(), { ...project(), id: "p2", name: "blog" }];

  await projects.refresh();

  expect(projects.list.map((p) => p.id)).toEqual(["p1", "p2"]);
});
