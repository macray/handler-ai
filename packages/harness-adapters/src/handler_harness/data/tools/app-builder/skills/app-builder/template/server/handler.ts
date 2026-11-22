// What the backend may ask handler: notifications (needs.notify), nudges ([nudges.<name>]), runs
// of its jobs ([jobs.<name>]), the folders the person gave (needs.files) and the history of those
// it writes, documents in structured markdown in those folders (schemas).

/** The folders given for its files needs, by need: `files().tasks`. */
export function files(): Record<string, string> {
  return JSON.parse(process.env.HANDLER_APP_FILES ?? "{}");
}

/** Tell a person (the owner by default): on the computer and, content-free, on their phones. */
export async function notify(title: string, opts: { body?: string; person?: string } = {}): Promise<void> {
  const [status, answer] = await call("POST", "/notify", { title, ...opts });
  if (status !== 200) throw new Error(`notify: ${answer.error ?? status}`);
}

/** Which one a nudge is among those of its name: 1–100 letters, digits and - _ . : (Handler
 * refuses any other character). Make it from ids or dates (`2026-11-16`, `role:acme-2024`),
 * never from text the person wrote. */
export type NudgeKey = string;

/** Ask a person to do something: one of the nudges app.toml declares (`[nudges.<name>]`), open
 * in their inbox until its action succeeds, `nudgeDone`, they dismiss it, or `until` passes.
 * The same name and `key` replace the open one. Returns its id; null when the person turned that
 * nudge off on the app's page (nothing sent: not an error). */
export async function nudge(
  name: string,
  title: string,
  opts: {
    body?: string;
    key?: NudgeKey;
    fields?: Record<string, unknown>;
    until?: string; // ISO time with its offset
    person?: string;
  } = {},
): Promise<string | null> {
  const [status, answer] = await call("POST", "/nudge", { name, title, ...opts });
  if (status !== 200) throw new Error(`nudge: ${answer.error ?? status}`);
  return answer.id as string | null;
}

/** What a nudge's `prepare` route answers (app.toml `[nudges.<name>] when` + `prepare`), at one
 * of its times: `Response.json(prepared)` for one, a list for several of its name (each with
 * its own key, at most 10), or `new Response(null, { status: 204 })` for none this time. */
export type PreparedNudge = {
  title: string; // ≤ 120
  body?: string; // ≤ 1000
  fields?: Record<string, unknown>; // its action's form, filled in
  key?: NudgeKey; // none: the time's (`2026-W47`, `2026-11-16`)
};

/** Which nudge to close: its id (`nudge()` returned it), or its name and key, for one whose id
 * your code never learnt (one Handler sent at its `when`, from your `prepare`). */
export type NudgeRef = string | { name: string; key: NudgeKey };

/** The person did what a nudge asked another way than its action (on the app's page): it is
 * done. By its name and key: the open ones of that name and key, whoever they went to. Returns
 * the ids it ended ([] when none of that name and key is open: not an error). */
export async function nudgeDone(ref: NudgeRef): Promise<string[]> {
  const [status, answer] =
    typeof ref === "string"
      ? await call("POST", `/nudge/${encodeURIComponent(ref)}/done`)
      : await call("POST", "/nudge/done", ref);
  if (status !== 200) throw new Error(`nudgeDone: ${answer.error ?? status}`);
  return typeof ref === "string" ? [ref] : (answer.ids as string[]);
}

/** A nudge no longer needed: gone from the person's inbox. By its name and key: the open ones of
 * that name and key. Returns the ids it withdrew ([] when none is open). */
export async function withdrawNudge(ref: NudgeRef): Promise<string[]> {
  const [status, answer] =
    typeof ref === "string"
      ? await call("DELETE", `/nudge/${encodeURIComponent(ref)}`)
      : await call("DELETE", "/nudge", ref);
  if (status !== 200) throw new Error(`withdrawNudge: ${answer.error ?? status}`);
  return typeof ref === "string" ? [ref] : (answer.ids as string[]);
}

/** The nudge an action's request answers (the person sent its form from the inbox), from its
 * X-HANDLER-Nudge header (set by handler, cannot be forged by the page): its id and its key, or
 * null when the action was not done from a nudge. */
export function answeredNudge(request: Request): { id: string; key?: NudgeKey } | null {
  const header = request.headers.get("x-handler-nudge");
  if (!header) return null;
  const [id, key] = header.split("; key=");
  return key === undefined ? { id } : { id, key };
}

/** Where an action's request was asked, from its X-HANDLER-Via header (set by handler): Ask's
 * pick, its form filled by the person ("try"), or a nudge; null for a request that is not an
 * action's. The same as a job's `startedBy.via`. */
export function askedVia(request: Request): "ask" | "try" | "nudge" | null {
  const via = request.headers.get("x-handler-via");
  return via === "ask" || via === "try" || via === "nudge" ? via : null;
}

export type Run = {
  id: string;
  job: string; // one of its [jobs.<name>]
  // what started it: this code (runJob), one of its actions and how the person asked it, or an
  // automation
  startedBy:
    | { by: "code" }
    | { by: "action"; action: string; via: "ask" | "try" | "nudge" }
    | { by: "automation"; automation: string };
  // what it was asked: the fields its run got (runJob's, an action's form, an automation's);
  // {} for a job with no form
  fields: Record<string, unknown>;
  sessionId: string;
  state: "waiting" | "running" | "succeeded" | "failed" | "cancelled";
  at: string; // when it was started
  endedAt?: string; // once it ended
  result?: { status: "ok" | "attention" | "failed"; summary: string; [key: string]: unknown };
  error?: string; // failed: why
  thenError?: string; // its job's `then` route failed: why (never called again)
};

/** Start a run of one of its jobs (`[jobs.<job>]`), run by the Who works the person chose, with
 * its form's fields. Only while answering the owner's request: pass that request, whose
 * X-HANDLER-Start header lets it start. Its result also goes to the person's inbox when it ends. */
export async function runJob(
  request: Request,
  job: string,
  fields: Record<string, unknown> = {},
): Promise<Run> {
  const start = request.headers.get("x-handler-start");
  if (!start) throw new Error("runJob: only while answering the owner's request");
  const [status, answer] = await call("POST", "/runs", { job, fields, start });
  if (status !== 202) throw new Error(`runJob: ${answer.error ?? status}`);
  return answer as Run;
}

/** How a run goes now: poll it (every few seconds) until it is no longer waiting or running. */
export async function getRun(id: string): Promise<Run> {
  const [status, answer] = await call("GET", `/runs/${encodeURIComponent(id)}`);
  if (status !== 200) throw new Error(`getRun: ${answer.error ?? status}`);
  return answer as Run;
}

/** Its runs Handler keeps (the last 50), newest first: keep no list of your own. */
export async function listRuns(): Promise<Run[]> {
  const [status, answer] = await call("GET", "/runs");
  if (status !== 200) throw new Error(`listRuns: ${answer.error ?? status}`);
  return answer.runs as Run[];
}

/** Stop a run that is waiting or running: it ends `cancelled`, and its job's `then` is not called. */
export async function cancelRun(id: string): Promise<Run> {
  const [status, answer] = await call("POST", `/runs/${encodeURIComponent(id)}/cancel`);
  if (status !== 200) throw new Error(`cancelRun: ${answer.error ?? status}`);
  return answer as Run;
}

/** What a job's `then` route receives (app.toml `[jobs.<name>] then = "POST /api/…"`), once
 * when one of its runs ended, whatever started it: as the owner, with no X-HANDLER-Start (it
 * cannot start a job). Save what the run produced there; answer 2xx. */
export type JobEnded<R = Run["result"]> = {
  runId: string;
  job: string;
  state: "succeeded" | "failed";
  fields: Record<string, unknown>; // the form it was started with
  result: R | null; // its result once it succeeded; null when it failed
};

/** What a route doing an action answers (app.toml `[actions.<name>] route`), within 30 s. */
export type ActionResult = {
  status: "ok" | "attention" | "failed";
  summary: string; // one or two plain sentences, readable aloud (≤ 500)
  data?: unknown;
  open?: string; // "/?line=…": the page of its UI showing what it did (Ask's Open goes there)
};

/** A problem of a document, located: its file, line, and where in the document's model. */
export type Diagnostic = {
  file: string;
  line: number;
  path: string; // "title", "items[1].fields.status"
  severity: "error" | "warning" | "info";
  code: string; // "missing-required-field", "invalid-enum", "broken-ref"…
  message: string;
};

/** A document in structured markdown, as handler reads it: the frontmatter, the `# title`, the
 * text before the first item, its items (`## title`) with their `key: value` fields, their body
 * or, when it is only a bullet list, its entries, and their `### sections`; each with the line
 * where it is in the file. */
export type SmdDocument = {
  meta: Record<string, unknown>; // the frontmatter: { schema: "cv@1", … }
  title: string | null;
  preamble: string | null;
  items: {
    title: string;
    slug: string;
    line: number;
    fields: Record<string, string | string[] | null>; // typed by its schema: dates as "2026-11-16"
    field_lines: Record<string, number>;
    body: string | null;
    entries: SmdEntry[] | null; // its body when it is only a bullet list (`- [ ] 10:00 Call #work`)
    sections: Record<string, { heading: string; line: number; content: string }>; // by the schema's key
  }[];
};

/** A bullet of an item's list: its checkbox, its line, the `key: value` lines under it, its
 * notes. Typed by its schema: `title` is the line without the value it starts with and its
 * `#tags`, which are fields (`time`, `area`); to change one, change `title` and `fields`. */
export type SmdEntry = {
  text: string; // the line as written (after the bullet and the checkbox)
  title: string | null; // null until a schema read it
  slug: string;
  line: number;
  checked: boolean | null; // [ ] false, [x] true, no checkbox null
  fields: Record<string, string | string[] | null>;
  field_lines: Record<string, number>;
  notes: string | null;
};

/** A document of a folder the person gave (`schemas` in app.toml): its model and its problems.
 * No `document` when it cannot be read (not UTF-8). */
export async function smdParse(path: string): Promise<{ document?: SmdDocument; diagnostics: Diagnostic[] }> {
  const [status, answer] = await call("POST", "/smd/parse", { path });
  if (status !== 200) throw new Error(`smdParse: ${answer.error ?? status}`);
  return answer as { document?: SmdDocument; diagnostics: Diagnostic[] };
}

/** The problems of a document, or of every `.md` file of a folder, against their schemas. */
export async function smdCheck(path: string): Promise<Diagnostic[]> {
  const [status, answer] = await call("POST", "/smd/check", { path });
  if (status !== 200) throw new Error(`smdCheck: ${answer.error ?? status}`);
  return answer.diagnostics as Diagnostic[];
}

/** Write a document (one `smdParse` gave, changed) in its canonical form, in a folder given
 * `mode = "rw"`; then its problems (it is written with them). Its frontmatter stays as the person
 * wrote it while its fields are the same. */
export async function smdWrite(path: string, document: SmdDocument): Promise<Diagnostic[]> {
  const [status, answer] = await call("POST", "/smd/write", { path, document });
  if (status !== 200) throw new Error(`smdWrite: ${answer.error ?? status}`);
  return answer.diagnostics as Diagnostic[];
}

/** Who could write a folder when it changed: an agent (`agentId`) or an app (`app`). */
export type Writer = { agentId?: string; app?: string; name: string };

/** A file a change touched: its lines added and removed, and the heading they are under, when it
 * is text (said for a change's first files only). */
export type FileChange = {
  path: string; // relative to the folder
  change: "added" | "changed" | "deleted";
  link: boolean;
  added?: number;
  removed?: number;
  under?: string;
};

/** One change of a folder, as Handler kept it: `first` the history's start, `changes` what
 * changed in a few minutes, `while-off` while Handler was not running, `undo` one put back. */
export type Change = {
  id: string;
  at: string; // ISO time
  kind: "first" | "changes" | "while-off" | "undo";
  couldWrite: Writer[];
  undoes?: string;
  files: FileChange[];
  fileCount: number;
};

/** The history of a folder given to a files need `mode = "rw"` (by its need's name): its last
 * 100 changes, newest first. Read only: Undo is the person's, on the app's page in Handler.
 * Throws when Handler has not looked at the folder yet (just installed). */
export async function history(need: string): Promise<{ folder: string; commits: Change[] }> {
  const [status, answer] = await call("GET", `/history?files=${encodeURIComponent(need)}`);
  if (status !== 200) throw new Error(`history: ${answer.error ?? status}`);
  return answer as { folder: string; commits: Change[] };
}

/** One change of that folder: its files, each with what changed in its lines (`diff`, a unified
 * diff without its header; none when it is not text or too large). */
export async function historyChange(
  need: string,
  id: string,
): Promise<{ commit: Change; files: (FileChange & { linkTarget?: string; diff?: string })[] }> {
  const [status, answer] = await call("GET", `/history/${encodeURIComponent(id)}?files=${encodeURIComponent(need)}`);
  if (status !== 200) throw new Error(`historyChange: ${answer.error ?? status}`);
  return answer as { commit: Change; files: (FileChange & { linkTarget?: string; diff?: string })[] };
}

/** One request to handler's socket: its status and its JSON answer. */
async function call(method: string, path: string, payload?: unknown): Promise<[number, Record<string, unknown>]> {
  const socket = process.env.HANDLER_APP_API;
  if (!socket) throw new Error("add `notify = true`, [nudges.<name>], [jobs.<name>], `schemas` or a files need `mode = \"rw\"` to app.toml");
  const res = await fetch(`http://handler${path}`, {
    method,
    unix: socket,
    headers: { "content-type": "application/json" },
    body: payload === undefined ? undefined : JSON.stringify(payload),
  });
  return [res.status, (await res.json().catch(() => ({}))) as Record<string, unknown>];
}
