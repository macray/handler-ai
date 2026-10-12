// The token reaches the page in the URL fragment (`/#token=…`, opened by `handler ui`): browsers
// never send fragments to the server. It is kept in sessionStorage (this tab only) and removed
// from the address bar right away.

const KEY = "handler.token";

export function captureToken(): void {
  const match = /^#token=([A-Za-z0-9_-]+)/.exec(window.location.hash);
  if (!match?.[1]) return;
  try {
    sessionStorage.setItem(KEY, match[1]);
  } catch {
    memoryToken = match[1];
  }
  history.replaceState(null, "", `${window.location.pathname}#/`);
}

let memoryToken: string | null = null;

export function token(): string | null {
  try {
    return sessionStorage.getItem(KEY) ?? memoryToken;
  } catch {
    return memoryToken;
  }
}
