// The web UI is signed in by a cookie (HttpOnly: this page never reads it): `handler ui` opens a
// one-time link that sets it, then redirects here, on the page it names (`/#/setup/x`). The
// browser keeps it a year, so a bookmark opens the UI; handlerd takes it only on requests from
// this page's own origin. The token itself never reaches the browser.

/** Whether this browser is signed in (its cookie opens the UI). */
export async function signedIn(): Promise<boolean> {
  try {
    return (await fetch("/v1/ui/signed-in")).status === 204;
  } catch {
    return false;
  }
}
