// An agent's form (its interface, D.18) as the editor shows it: what a session is started with (a
// form; a skill field, one at most, picks a skill of the library to work on), and for a job, what
// it gives back (always a status and a summary, as automations read them, I.3, then fields of its
// own) and how long a turn may take. A brief is the form alone. The editor writes the JSON Schemas;
// an interface it cannot write back exactly (other keywords, nesting, other hints) is edited as
// JSON instead.
import type { AgentInterface } from "./contracts.gen";
import type { Field, Schema } from "./runs";

/** How an agent is used (D.18): chatted with, started from its brief then chatted with, or given
 *  a job (a form in, a result out, unattended). */
export type Use = "chat" | "brief" | "job";

/** Its name, the same everywhere: the editor's cards, the chip on an agent, its line in a list. */
export const USE_LABEL: Record<Use, string> = { chat: "Chat", brief: "Brief", job: "Job" };

/** How a saved agent is used. */
export function useOfAgent(a: { interface?: AgentInterface | null }): Use {
  return a.interface?.result ? "job" : a.interface ? "brief" : "chat";
}

/** The use an interface typed as JSON says: none, a chat; a result, a job; else a brief. */
export function useOf(text: string): Use {
  if (!text.trim()) return "chat";
  try {
    return (JSON.parse(text) as AgentInterface | null)?.result ? "job" : "brief";
  } catch {
    return /"result"\s*:/.test(text) ? "job" : "brief"; // being typed
  }
}

export type FieldType = "text" | "long-text" | "number" | "yes-no" | "choice" | "list" | "skill" | "items";

export const FIELD_TYPES: { type: FieldType; label: string }[] = [
  { type: "text", label: "Short text" },
  { type: "long-text", label: "Long text" },
  { type: "number", label: "Number" },
  { type: "yes-no", label: "Yes / no" },
  { type: "choice", label: "Choice" },
  { type: "list", label: "List of texts" },
  { type: "skill", label: "Skill" },
  { type: "items", label: "List of items" },
];

/** The types a form's field may have, a result's, and an item's: one level, no list of items. */
export const FORM_TYPES: FieldType[] = ["text", "long-text", "number", "yes-no", "choice", "list", "skill"];
export const RESULT_TYPES: FieldType[] = ["text", "long-text", "number", "yes-no", "choice", "list", "items"];
export const ITEM_TYPES: FieldType[] = ["text", "long-text", "number", "yes-no", "choice"];

export type FieldDef = {
  key: string; // its name in the JSON: kept once saved, else made from its title
  saved: boolean;
  title: string;
  description: string;
  type: FieldType;
  choices: string; // "low, medium, high": as typed
  required: boolean;
  items: FieldDef[]; // a list of items: each item's fields
};

export type Job = {
  fields: FieldDef[];
  status: Schema; // the result's status and summary, kept as they were written
  summary: Schema;
  result: FieldDef[]; // what else it gives back
  timeoutSec: number;
};

export const STATUS: Schema = { enum: ["ok", "attention", "failed"], title: "Status", "x-handler": "verdict" };
export const SUMMARY: Schema = { type: "string", title: "Summary" };

export function newField(type: FieldType = "text"): FieldDef {
  return { key: "", saved: false, title: "", description: "", type, choices: "", required: true, items: [] };
}

/** A new job: no form (the person names its fields), a result saying how it went. */
export function newJob(): Job {
  return { fields: [], status: STATUS, summary: SUMMARY, result: [], timeoutSec: 1800 };
}

/** "Due date" → "dueDate"; "field" when nothing is left. */
export function keyOf(title: string): string {
  const words = title
    .normalize("NFKD")
    .replace(/[^A-Za-z0-9 ]+/g, " ")
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  if (!words.length) return "field";
  const [first, ...rest] = words.map((w) => w.toLowerCase());
  const key = first! + rest.map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join("");
  return /^[0-9]/.test(key) ? `field${key}` : key;
}

function choicesOf(f: FieldDef): string[] {
  return f.choices
    .split(",")
    .map((c) => c.trim())
    .filter(Boolean);
}

function fieldSchema(f: FieldDef): Schema {
  const s: Schema = {};
  if (f.type === "choice") s.enum = choicesOf(f);
  else if (f.type === "text" || f.type === "long-text" || f.type === "skill") s.type = "string";
  else if (f.type === "number") s.type = "number";
  else if (f.type === "yes-no") s.type = "boolean";
  else if (f.type === "list") Object.assign(s, { type: "array", items: { type: "string" } });
  else Object.assign(s, { type: "array", items: objectSchema(f.items) });
  if (f.title.trim()) s.title = f.title.trim();
  if (f.description.trim()) s.description = f.description.trim();
  if (f.type === "long-text" || f.type === "skill") s["x-handler"] = f.type;
  return s;
}

/** Each field's key: its saved one, else from its title, unique among them. */
function keysOf(fields: FieldDef[], taken: string[] = []): string[] {
  const keys = [...taken];
  for (const f of fields) {
    let key = f.saved ? f.key : keyOf(f.title);
    for (let n = 2; keys.includes(key); n++) key = `${f.saved ? f.key : keyOf(f.title)}${n}`;
    keys.push(key);
  }
  return keys.slice(taken.length);
}

function objectSchema(fields: FieldDef[], first: [string, Schema][] = []): Schema {
  const keys = keysOf(fields, first.map(([k]) => k));
  const properties = Object.fromEntries([...first, ...fields.map((f, i) => [keys[i]!, fieldSchema(f)] as [string, Schema])]);
  const required = [...first.map(([k]) => k), ...keys.filter((_, i) => fields[i]!.required)];
  return { type: "object", properties, ...(required.length ? { required } : {}) };
}

/** The interface the job is (D.18); a brief's: its form alone. */
export function interfaceOf(job: Job, brief = false): AgentInterface {
  const form = job.fields.length ? { fields: objectSchema(job.fields) } : {};
  if (brief) return form;
  return {
    ...form,
    result: objectSchema(job.result, [
      ["status", job.status],
      ["summary", job.summary],
    ]),
    timeoutSec: job.timeoutSec,
  };
}

function typeOf(s: Schema): FieldType | null {
  if (Array.isArray(s.enum)) return "choice";
  if (s.type === "string") return s["x-handler"] === "long-text" ? "long-text" : s["x-handler"] === "skill" ? "skill" : "text";
  if (s.type === "number") return "number";
  if (s.type === "boolean") return "yes-no";
  const items = s.items as Schema | undefined;
  if (s.type === "array" && items?.type === "string") return "list";
  if (s.type === "array" && items?.type === "object") return "items";
  return null;
}

function fieldsFrom(schema: Schema | null | undefined, skip: string[] = []): FieldDef[] {
  const props = (schema?.properties ?? {}) as Record<string, Schema>;
  const required = Array.isArray(schema?.required) ? (schema.required as string[]) : [];
  return Object.entries(props)
    .filter(([key]) => !skip.includes(key))
    .map(([key, s]) => ({
      key,
      saved: true,
      title: typeof s.title === "string" ? s.title : "",
      description: typeof s.description === "string" ? s.description : "",
      type: typeOf(s) ?? "text", // checked by the round trip
      choices: Array.isArray(s.enum) ? s.enum.map(String).join(", ") : "",
      required: required.includes(key),
      items: typeOf(s) === "items" ? fieldsFrom(s.items as Schema) : [],
    }));
}

/** JSON with objects' keys sorted and `required` lists as sets: two schemas saying the same. */
function canonical(v: unknown, key = ""): unknown {
  if (Array.isArray(v)) {
    const items = v.map((x) => canonical(x));
    return key === "required" ? items.map(String).sort() : items;
  }
  if (v && typeof v === "object") {
    return Object.fromEntries(
      Object.entries(v as Record<string, unknown>)
        .filter(([, x]) => x !== null && x !== undefined)
        .sort(([a], [b]) => (a < b ? -1 : 1))
        .map(([k, x]) => [k, canonical(x, k)]),
    );
  }
  return v;
}

/** The job an interface is, or null when the editor cannot show it as it is (edited as JSON). */
export function jobOf(iface: AgentInterface | null | undefined): Job | null {
  if (!iface || typeof iface !== "object") return null;
  const brief = !iface.result;
  const result = (iface.result ?? {}) as Schema;
  const props = (result.properties ?? {}) as Record<string, Schema>;
  if (!brief && (!props.status || !props.summary)) return null;
  const job: Job = {
    fields: fieldsFrom(iface.fields as Schema | null | undefined),
    status: props.status ?? STATUS,
    summary: props.summary ?? SUMMARY,
    result: brief ? [] : fieldsFrom(result, ["status", "summary"]),
    timeoutSec: typeof iface.timeoutSec === "number" ? iface.timeoutSec : 1800,
  };
  const all = [...job.fields, ...job.result];
  if (job.fields.some((f) => !FORM_TYPES.includes(f.type))) return null;
  if (job.result.some((f) => !RESULT_TYPES.includes(f.type))) return null;
  if (all.some((f) => f.items.some((i) => !ITEM_TYPES.includes(i.type)))) return null;
  const same = JSON.stringify(canonical(interfaceOf(job, brief))) === JSON.stringify(canonical(brief ? iface : { timeoutSec: 1800, ...iface }));
  return same ? job : null;
}

// a field of the form named in the instructions, filled in with its value when a session starts
const PLACEHOLDER = /\{\{\s*([^{}\s]+)\s*\}\}/g;

/** The keys the instructions name, `{{key}}`, once each. */
export function placeholders(text: string): string[] {
  return [...new Set([...text.matchAll(PLACEHOLDER)].map((m) => m[1]!))];
}

/** The instructions in pieces, to show the form's fields in them: plain text, a field of the
 *  form (`keys`), or a placeholder naming none (`unknown`). Joined, the pieces are the text. */
export type TextPart = { text: string; kind: "text" | "field" | "unknown"; key?: string };
export function textParts(text: string, keys: string[]): TextPart[] {
  const parts: TextPart[] = [];
  let at = 0;
  for (const m of text.matchAll(PLACEHOLDER)) {
    if (m.index > at) parts.push({ text: text.slice(at, m.index), kind: "text" });
    parts.push({ text: m[0], kind: keys.includes(m[1]!) ? "field" : "unknown", key: m[1]! });
    at = m.index + m[0].length;
  }
  if (at < text.length) parts.push({ text: text.slice(at), kind: "text" });
  return parts;
}

/** The instructions with `{{from}}` written `{{to}}`: a field whose key follows its label. */
export function renamed(text: string, from: string, to: string): string {
  return text.replace(PLACEHOLDER, (all, key: string) => (key === from ? `{{${to}}}` : all));
}

/** A new brief: one long text, what the request box of a chat asks. */
export function newBrief(): Job {
  return { ...newJob(), fields: [{ ...newField("long-text"), title: "What should it do?" }] };
}

/** The interface typed as JSON, made a brief (its result and time limit dropped) or a job (a
 *  new job's result added when it has none); a new one's when it is not JSON. */
export function switchedTo(use: "brief" | "job", text: string): string {
  let iface: AgentInterface | null = null;
  try {
    iface = JSON.parse(text) as AgentInterface;
  } catch {
    // not JSON (being typed): a new one
  }
  if (!iface || typeof iface !== "object") iface = interfaceOf(use === "brief" ? newBrief() : newJob(), use === "brief");
  const { result, timeoutSec, ...form } = iface;
  const fresh = interfaceOf(newJob());
  const next = use === "brief" ? form : { ...form, result: result ?? fresh.result, timeoutSec: timeoutSec ?? fresh.timeoutSec };
  if (use === "brief" && !next.fields) return JSON.stringify(interfaceOf(newBrief(), true), null, 2);
  return JSON.stringify(next, null, 2);
}

/** The job with no key kept: an agent not saved with it yet, whose keys follow the labels. */
export function unsaved(job: Job): Job {
  const all = (fields: FieldDef[]): FieldDef[] => fields.map((f) => ({ ...f, saved: false, items: all(f.items) }));
  return { ...job, fields: all(job.fields), result: all(job.result) };
}

/** Made-up values of a schema, to show a result card before any run: neutral words, never a
 *  field's own label (read as the field's name, not its value). */
export function sampleOf(schema: Schema | undefined, key = ""): unknown {
  const s = schema ?? {};
  if (key === "status" && Array.isArray(s.enum)) return s.enum[0];
  if (key === "summary") return "What it did, in a sentence or two.";
  if (Array.isArray(s.enum)) return s.enum[0] ?? "";
  if (s.type === "string") return s["x-handler"] === "long-text" ? "Sample text\nover a few lines." : "Sample text";
  if (s.type === "number" || s.type === "integer") return 3;
  if (s.type === "boolean") return true;
  if (s.type === "array") return [sampleOf(s.items as Schema, key), sampleOf(s.items as Schema, key)];
  if (s.type === "object") {
    const props = (s.properties ?? {}) as Record<string, Schema>;
    return Object.fromEntries(Object.entries(props).map(([k, sub]) => [k, sampleOf(sub, k)]));
  }
  return null;
}

/** Made-up values of a run's form, so its preview reads as a filled-in form. */
export function sampleInput(fields: Field[]): Record<string, unknown> {
  const sample = (f: Field): unknown =>
    ({ text: "Sample text", "long-text": "Sample text\nover a few lines.", skill: "", number: 3, boolean: true, choice: f.choices[0] ?? "", list: "First\nSecond", json: "{}" })[f.kind];
  return Object.fromEntries(fields.map((f) => [f.key, sample(f)]));
}
