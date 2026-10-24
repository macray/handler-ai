// What the backend may ask handler: notifications (needs.notify), runs of the agents the person
// gave its needs (needs.agents), the folders they gave (needs.files).

/** The folders given for its files needs, by need: `files().tasks`. */
export function files(): Record<string, string> {
  return JSON.parse(process.env.HANDLER_APP_FILES ?? "{}");
}

/** Tell a person (the owner by default): on the computer and, content-free, on their phones. */
export async function notify(title: string, opts: { body?: string; person?: string } = {}): Promise<void> {
  const [status, answer] = await call("POST", "/notify", { title, ...opts });
  if (status !== 200) throw new Error(`notify: ${answer.error ?? status}`);
}

export type Run = {
  id: string;
  agent: string; // the need
  sessionId: string;
  state: "waiting" | "running" | "succeeded" | "failed" | "cancelled";
  at: string;
  result?: { status: "ok" | "attention" | "failed"; summary: string; [key: string]: unknown };
  error?: string;
};

/** Start a run of the agent the person gave one of its needs (`needs.agents.<agent>`), with its
 * form's fields. Only while answering the owner's request: pass that request, whose
 * X-HANDLER-Start header lets it start. Its result also goes to the person's inbox when it ends. */
export async function runAgent(
  request: Request,
  agent: string,
  fields: Record<string, unknown> = {},
): Promise<Run> {
  const start = request.headers.get("x-handler-start");
  if (!start) throw new Error("runAgent: only while answering the owner's request");
  const [status, answer] = await call("POST", "/runs", { agent, fields, start });
  if (status !== 202) throw new Error(`runAgent: ${answer.error ?? status}`);
  return answer as Run;
}

/** How a run goes now: poll it (every few seconds) until it is no longer waiting or running. */
export async function getRun(id: string): Promise<Run> {
  const [status, answer] = await call("GET", `/runs/${encodeURIComponent(id)}`);
  if (status !== 200) throw new Error(`getRun: ${answer.error ?? status}`);
  return answer as Run;
}

export async function cancelRun(id: string): Promise<Run> {
  const [status, answer] = await call("POST", `/runs/${encodeURIComponent(id)}/cancel`);
  if (status !== 200) throw new Error(`cancelRun: ${answer.error ?? status}`);
  return answer as Run;
}

/** One request to handler's socket: its status and its JSON answer. */
async function call(method: string, path: string, payload?: unknown): Promise<[number, Record<string, unknown>]> {
  const socket = process.env.HANDLER_APP_API;
  if (!socket) throw new Error("add `notify = true` or [needs.agents.<name>] to app.toml");
  const res = await fetch(`http://handler${path}`, {
    method,
    unix: socket,
    headers: { "content-type": "application/json" },
    body: payload === undefined ? undefined : JSON.stringify(payload),
  });
  return [res.status, (await res.json().catch(() => ({}))) as Record<string, unknown>];
}
