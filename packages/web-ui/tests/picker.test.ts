// The model picker, shown once per agent on a page (a blueprint's set-up, an app's install): each
// label names its own field, so clicking one focuses that picker's, and a screen reader reads it.
import { afterEach, describe, expect, it, vi } from "vitest";
import { flushSync, mount, unmount } from "svelte";
import ModelAccessPicker from "../src/components/ModelAccessPicker.svelte";
import { noAccess } from "../src/lib/access";

const api = vi.hoisted(() => ({ accounts: vi.fn(async () => []), providers: vi.fn(async () => []) }));
vi.mock("../src/lib/api", () => ({ api }));

describe("two model pickers on one page", () => {
  const target = document.createElement("div");
  document.body.append(target);
  afterEach(() => target.replaceChildren());

  it("each label names its own picker's field", () => {
    const views = [0, 1].map(() => mount(ModelAccessPicker, { target, props: { value: { ...noAccess(), account: "fake" } } }));
    flushSync();
    const fields = [...target.querySelectorAll('[data-testid="access-model"]')];
    expect(fields).toHaveLength(2);
    const labelled = [...target.querySelectorAll("label")]
      .filter((l) => l.textContent?.trim() === "Model")
      .map((l) => document.getElementById(l.htmlFor));
    expect(labelled).toHaveLength(2);
    expect(labelled[0]).toBe(fields[0]);
    expect(labelled[1]).toBe(fields[1]);
    for (const v of views) unmount(v);
  });
});
