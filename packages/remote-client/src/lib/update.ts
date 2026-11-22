// A new client on the gateway is used without the person doing anything. A launch already gets it
// (the gateway has the browser check its files on each use); this is for a page left open: a
// phone keeps it in the background for days.
// - Back on the page: the gateway's index names another script than the one running → reload.
// - A part loaded later (a screen, `import()`) is gone from the gateway: it belongs to the
//   previous client → reload (once: a gateway that really lacks it must not loop).
// Drafts are kept across a reload (`saveDraft`), and the reload happens when the person comes back,
// not while they type.

const CHECK_EVERY = 60_000;
const RELOADED_AT = "handler-reloaded-at";

let checked = 0;

function running(doc: Document): string | null {
  const src = doc.querySelector<HTMLScriptElement>('script[type="module"][src]')?.getAttribute("src");
  return src ? new URL(src, location.origin).pathname : null;
}

/** The script the gateway's index names now, or null when it cannot tell (offline, no index). */
export async function deployed(): Promise<string | null> {
  try {
    const r = await fetch("/", { cache: "no-cache" });
    if (!r.ok) return null;
    return running(new DOMParser().parseFromString(await r.text(), "text/html"));
  } catch {
    return null;
  }
}

function reload(): void {
  const last = Number(sessionStorage.getItem(RELOADED_AT) ?? 0);
  if (Date.now() - last < 30_000) return; // just reloaded for it: not again
  sessionStorage.setItem(RELOADED_AT, String(Date.now()));
  location.reload();
}

export async function checkForUpdate(): Promise<void> {
  if (Date.now() - checked < CHECK_EVERY) return;
  checked = Date.now();
  const now = await deployed();
  const mine = running(document);
  if (now && mine && now !== mine) reload();
}

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") void checkForUpdate();
});

window.addEventListener("vite:preloadError", (event) => {
  event.preventDefault();
  reload();
});
