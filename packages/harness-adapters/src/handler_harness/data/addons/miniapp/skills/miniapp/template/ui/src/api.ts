// The only way the UI talks to its backend: `api("notes")` is GET /api/notes. Do not call fetch()
// yourself, nor any other host: on the computer the page may only reach its own backend (handler's
// Content-Security-Policy), and on a phone it runs in a frame with no network at all, where handler
// gives it `__handlerFetch`, which carries the call to the backend through handler's encrypted channel.
const send: typeof fetch = (globalThis as { __handlerFetch?: typeof fetch }).__handlerFetch ?? fetch;

export async function api<T>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
  const response = await send(`/api/${path}`, {
    method: init.method ?? "GET",
    headers: init.body === undefined ? {} : { "Content-Type": "application/json" },
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new Error(data?.error ?? `${response.status} ${response.statusText}`);
  return data as T;
}
