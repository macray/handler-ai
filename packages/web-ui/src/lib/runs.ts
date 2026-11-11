// Runs of agents with an interface (D.18): the form a run is started with ("x-handler": "long-text"
// on a string: several lines; "skill": a skill of the library, the run's subject), its result shown from its schema (two hints: "x-handler": "verdict"
// on an enum, the run's outcome, shown as a badge; "x-handler": "code-ref" on {path, lines: [from,
// to]}, those lines of the subject read by handlerd), and
// a definition's defaults, the form it is set up with.
import type { AgentDefinition, AgentInterface, Session } from "./contracts.gen";
import { emptyAgent, type AgentSpec } from "./projects.svelte";

export type Schema = Record<string, unknown>;

/** What a run was given, in one line: the skill it works on, else its fields' values. */
export function inputSummary(run: Session): string | null {
  if (run.subject) return `the skill ${run.subject.skill}`;
  const values = Object.values(run.input?.fields ?? {})
    .filter((v) => ["string", "number", "boolean"].includes(typeof v) && String(v).trim())
    .map((v) => String(v).trim().replace(/\s+/g, " "));
  if (!values.length) return null;
  const line = values.join(" · ");
  return line.length > 120 ? `${line.slice(0, 119)}…` : line;
}

/** One input of a run's form, from its `fields` schema. */
export type Field = {
  key: string;
  title: string;
  description?: string;
  kind: "text" | "long-text" | "skill" | "number" | "boolean" | "choice" | "list" | "json";
  choices: string[];
  required: boolean;
};

export function properties(schema: Schema | null | undefined): [string, Schema][] {
  const props = schema?.properties;
  return props && typeof props === "object" ? (Object.entries(props) as [string, Schema][]) : [];
}

export function titleOf(key: string, schema: Schema): string {
  if (typeof schema.title === "string") return schema.title;
  const words = key.replace(/([a-z])([A-Z])/g, "$1 $2").replace(/[_-]+/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1).toLowerCase();
}

/** The key of an interface's skill field (one at most): a skill of the library to work on. */
export function skillField(iface: AgentInterface | null | undefined): string | null {
  return properties(iface?.fields as Schema | undefined).find(([, s]) => s["x-handler"] === "skill")?.[0] ?? null;
}

export function fieldsOf(schema: Schema | null | undefined): Field[] {
  const required = Array.isArray(schema?.required) ? (schema.required as string[]) : [];
  return properties(schema).map(([key, s]) => {
    const choices = Array.isArray(s.enum) ? s.enum.map(String) : [];
    const kind: Field["kind"] = choices.length
      ? "choice"
      : s.type === "string"
        ? s["x-handler"] === "long-text"
          ? "long-text"
          : s["x-handler"] === "skill"
            ? "skill"
            : "text"
        : s.type === "array" && (s.items as Schema | undefined)?.type === "string"
          ? "list"
          : s.type === "number" || s.type === "integer"
          ? "number"
          : s.type === "boolean"
            ? "boolean"
            : "json";
    return {
      key,
      title: titleOf(key, s),
      ...(typeof s.description === "string" ? { description: s.description } : {}),
      kind,
      choices,
      required: required.includes(key),
    };
  });
}

/** The form's values as a run's `fields`: empty optional ones left out (a list: one per line);
 *  throws on bad JSON. */
export function fieldValues(fields: Field[], values: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const f of fields) {
    const v = values[f.key];
    if (v === undefined || v === "" || v === null) continue;
    if (f.kind === "number") out[f.key] = Number(v);
    else if (f.kind === "list") {
      const items = String(v)
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean);
      if (items.length) out[f.key] = items;
    }
    else if (f.kind === "json") {
      try {
        out[f.key] = JSON.parse(String(v));
      } catch {
        throw new Error(`${f.title}: not JSON`);
      }
    } else out[f.key] = v;
  }
  return out;
}

/** A run's `fields` back in the form: a list one per line, JSON as text. */
export function formValues(fields: Field[], input: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(input).map(([k, v]) => {
      const kind = fields.find((f) => f.key === k)?.kind;
      if (kind === "list" && Array.isArray(v)) return [k, v.join("\n")];
      return [k, kind === "json" ? JSON.stringify(v) : v];
    }),
  );
}

export type Tone = "ok" | "warn" | "danger" | "muted";

/** An enum's value as a tone: its first value is the best, its last the worst. */
export function toneOf(schema: Schema, value: unknown): Tone {
  const values = Array.isArray(schema.enum) ? schema.enum : [];
  const i = values.indexOf(value);
  if (i < 0 || values.length < 2) return "muted";
  if (i === 0) return "ok";
  return i === values.length - 1 ? "danger" : "warn";
}

/** The run's outcome: its result's top-level "verdict" property, if its schema has one. */
export function verdictOf(schema: Schema | null | undefined, value: unknown): { value: string; tone: Tone } | null {
  if (!value || typeof value !== "object") return null;
  for (const [key, s] of properties(schema)) {
    const v = (value as Record<string, unknown>)[key];
    if (s["x-handler"] === "verdict" && typeof v === "string") return { value: v, tone: toneOf(s, v) };
  }
  return null;
}

/** A code reference of a result ({path, lines: [from, to]}), or null when it is not one. */
export function codeRef(value: unknown): { path: string; from: number; to: number } | null {
  if (!value || typeof value !== "object") return null;
  const { path, lines } = value as { path?: unknown; lines?: unknown };
  if (typeof path !== "string" || !Array.isArray(lines) || lines.length !== 2) return null;
  const [from, to] = lines.map(Number);
  if (!Number.isInteger(from) || !Number.isInteger(to) || from! < 1 || to! < from!) return null;
  return { path, from: from!, to: to! };
}

/** Who started a run, in words: "you", "an automation", "the app planner". */
export function startedBy(s: Session): string {
  if (s.origin === "automation") return "by an automation";
  if (s.origin === "app") return `by the app ${s.app ?? ""}`.trimEnd();
  if (s.origin === "check") return "by its checks";
  if (s.origin === "plan") return `by a plan, step ${s.plan?.step ?? ""}`.trimEnd();
  return "by you";
}

/** How a run is going; a run waiting for its turn (one run of an agent at a time) is running. */
export function runState(s: Session): "running" | "done" | "invalid" | "no result" {
  if (s.state === "starting" || s.state === "running") return "running";
  if (s.output) return s.output.valid ? "done" : "invalid";
  return "no result";
}

/** A definition's defaults (D.18: an agents file's agent, D.23, a need's of Handler, or an app's, H.2), the form it
 *  is set up with: its models are chosen there; from then on its settings are the user's. */
export function definitionSpec(t: AgentDefinition): AgentSpec {
  return {
    ...emptyAgent(),
    name: t.agentName,
    description: t.agentDescription ?? "",
    instructions: t.instructions ?? "",
    network: t.network ?? "filtered",
    egress: t.egress ?? "enforce",
    confinement: t.confinement ?? "strict",
    permissions: t.permissions ?? "bypass",
    allow: [...(t.allow ?? [])],
    skills: [...(t.skills ?? [])],
    knowledge: [...(t.knowledge ?? [])],
    display: t.display ?? false,
    interface: t.interface ? JSON.stringify(t.interface, null, 2) : "",
    modelAlone: t.modelAlone ?? false,
  };
}
