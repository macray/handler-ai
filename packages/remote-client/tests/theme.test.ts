// Settings → Appearance: System, Light or Dark, kept in this browser and applied as `.dark`.
import { flushSync, mount, unmount } from "svelte";
import { afterEach, expect, test } from "vitest";
import { theme } from "../src/lib/theme.svelte";
import Appearance from "../src/views/Appearance.svelte";

let shown: ReturnType<typeof mount> | null = null;

afterEach(() => {
  if (shown) unmount(shown);
  shown = null;
  document.body.innerHTML = "";
  theme.set("system");
});

function pick(id: string): void {
  document.querySelector<HTMLElement>(`[data-testid="theme-${id}"]`)?.click();
  flushSync();
}

test("a choice applies at once and is kept; System forgets it", () => {
  shown = mount(Appearance, { target: document.body, props: { onback: () => undefined } });
  flushSync();
  expect(document.querySelector('[data-testid="theme-system"]')?.getAttribute("aria-checked")).toBe("true");

  pick("dark");
  expect(document.documentElement.classList.contains("dark")).toBe(true);
  expect(localStorage.getItem("handler.theme")).toBe("dark");
  expect(document.querySelector('[data-testid="theme-dark"]')?.getAttribute("aria-checked")).toBe("true");

  pick("light");
  expect(document.documentElement.classList.contains("dark")).toBe(false);
  expect(localStorage.getItem("handler.theme")).toBe("light");

  pick("system");
  expect(localStorage.getItem("handler.theme")).toBeNull();
});
