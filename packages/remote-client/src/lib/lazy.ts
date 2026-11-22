// What only an open session or app needs, in chunks of their own: the startup chunk paints Home
// without the ACP SDK, its schemas, the Markdown renderer, the sanitizer and the diff. Each is
// asked once (the same promise again), and fetched ahead once the browser is idle.
type Loader<T> = () => Promise<T>;

function once<T>(load: Loader<T>): Loader<T> {
  let p: Promise<T> | null = null;
  return () => (p ??= load().catch((e: unknown) => {
    p = null; // asked again next time (a network hiccup)
    throw e;
  }));
}

export const acp = once(() => import("@handler/acp-view/lib/connection.svelte"));
export const sessionScreen = once(() => import("../views/SessionScreen.svelte"));
export const appScreen = once(() => import("../views/AppScreen.svelte"));

let prefetched = false;

/** Once per launch. */
export function prefetch(): void {
  if (prefetched) return;
  prefetched = true;
  const all = () => void Promise.all([acp(), sessionScreen(), appScreen()]).catch(() => undefined);
  if ("requestIdleCallback" in window) requestIdleCallback(all, { timeout: 4_000 });
  else setTimeout(all, 1_500);
}
