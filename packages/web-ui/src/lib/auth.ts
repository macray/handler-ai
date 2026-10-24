// The token reaches the page in the URL fragment (`/#token=…`, opened by `handler ui`): browsers
// never send fragments to the server. It is kept in sessionStorage (this tab only) and removed
// from the address bar right away; `&then=/route` opens that page (`handler project
// import-agents` prints one for the set-up page).

const KEY = "handler.token";

export function captureToken(): void {
  const match = /^#token=([A-Za-z0-9_-]+)(?:&then=(\/[^&]*))?/.exec(window.location.hash);
  if (!match?.[1]) return;
  try {
    sessionStorage.setItem(KEY, match[1]);
  } catch {
    memoryToken = match[1];
  }
  history.replaceState(null, "", `${window.location.pathname}#${match[2] ?? "/"}`);
}

let memoryToken: string | null = null;

export function token(): string | null {
  try {
    return sessionStorage.getItem(KEY) ?? memoryToken;
  } catch {
    return memoryToken;
  }
}
