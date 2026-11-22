// The phone's Settings → Notifications (a page of its own): a switch per kind of notification (H.10), the one for a
// session needing you only on a phone that sees sessions.
import { flushSync, mount, unmount } from "svelte";
import { afterEach, expect, test } from "vitest";
import { app } from "../src/lib/app.svelte";
import Settings from "../src/views/Settings.svelte";

let shown: ReturnType<typeof mount> | null = null;

afterEach(() => {
  if (shown) unmount(shown);
  shown = null;
  document.body.innerHTML = "";
});

function switches(scope: "all" | "apps"): string[] {
  app.scope = scope;
  shown = mount(Settings, { target: document.body });
  flushSync();
  document.querySelector<HTMLElement>('[data-testid="open-notifications"]')!.click(); // its own page
  flushSync();
  return [...document.querySelectorAll<HTMLElement>('[role="switch"]')].map((s) => s.dataset.testid ?? "");
}

test("an owner's phone has both switches", () => {
  expect(switches("all")).toEqual(["push-toggle-needs-you", "push-toggle-app-news"]);
  expect(document.body.textContent).toContain("When a session needs you");
  expect(document.body.textContent).toContain("When an app has news");
});

test("a phone for apps only has the app-news one alone", () => {
  expect(switches("apps")).toEqual(["push-toggle-app-news"]);
  expect(document.body.textContent).not.toContain("When a session needs you");
});

test("a switch shows on only while subscribed with that kind", () => {
  app.pushOn = true;
  app.pushKinds = ["app-news"];
  switches("all");
  const on = (kind: string) => document.querySelector(`[data-testid="push-toggle-${kind}"]`)?.getAttribute("aria-checked");
  expect([on("needs-you"), on("app-news")]).toEqual(["false", "true"]);
  app.pushOn = false;
});
