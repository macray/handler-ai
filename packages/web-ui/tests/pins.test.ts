// The pins store keeps a change made here over a list the daemon answered before it: the menu asks
// for the list on a load, and a slower answer must not undo a pin made meanwhile. The store runs
// as it is, on a fake daemon.
import { beforeEach, expect, it, vi } from "vitest";
import type { Pin } from "../src/lib/contracts.gen";
import { pins } from "../src/lib/pins.svelte";

const answers = vi.hoisted(() => ({}) as Record<string, (...args: unknown[]) => Promise<unknown>>);
vi.mock("../src/lib/api", () => ({
  ApiError: class extends Error {},
  api: new Proxy({}, { get: (_, name: string) => answers[name] ?? (() => new Promise(() => {})) }),
}));

const shop: Pin = { kind: "project", id: "p1" };
const planner: Pin = { kind: "app", id: "planner" };

beforeEach(() => {
  pins.items = [shop];
});

it("a list asked for before a pin changed does not undo it", async () => {
  // If this fails: a project unpinned just after the page loads comes back in the menu.
  let answer!: (list: { items: Pin[] }) => void;
  let now: Pin[] = [shop];
  answers.pins = vi
    .fn()
    .mockImplementationOnce(() => new Promise((resolve) => (answer = resolve))) // asked before
    .mockImplementation(async () => ({ items: now })); // asked again: the daemon's list now
  answers.setPins = async (body) => {
    now = (body as { items: Pin[] }).items;
    return { items: now };
  };

  const loaded = pins.load();
  await pins.unpin("project", "p1");
  answer({ items: [shop] }); // what the daemon had before the change
  await loaded;

  expect(pins.items).toEqual([]);
});

it("pins last, reorders, and goes back to what it showed when the daemon fails", async () => {
  // If this fails: the menu shows an order, or a pin, that handlerd does not keep.
  answers.setPins = async (body) => body;
  await pins.pin("app", "planner");
  expect(pins.items).toEqual([shop, planner]);
  await pins.move(1, 0);
  expect(pins.items).toEqual([planner, shop]);

  answers.setPins = async () => {
    throw new Error("handlerd is not running");
  };
  await expect(pins.pin("app", "gone")).rejects.toThrow("handlerd is not running");
  expect(pins.items).toEqual([planner, shop]);
  expect(pins.error).toBe("handlerd is not running");
});

it("shows the list the daemon kept: a pin of something deleted elsewhere goes", async () => {
  // If this fails: pinning does nothing after a pinned project was deleted elsewhere, or the menu
  // keeps showing it.
  pins.items = [shop, planner]; // shop deleted elsewhere since
  answers.setPins = async (body) => ({ items: (body as { items: Pin[] }).items.filter((p) => p.id !== "p1") });
  const blog: Pin = { kind: "project", id: "p2" };
  await pins.pin(blog.kind, blog.id);
  expect(pins.items).toEqual([planner, blog]);
});
