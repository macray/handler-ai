// Runs of agents with an interface (D.18): the form a run is started with, its result shown from
// its schema (two hints: "x-handler": "verdict" on an enum, the run's outcome, shown as a badge;
// "x-handler": "code-ref" on {path, lines: [from, to]}, those lines of the subject read by handlerd), and
// a built-in agent's defaults, the form it is set up with.
import type { BuiltinAgent, Session, SessionInput } from "./contracts.gen";
import { emptyAgent, type AgentSpec } from "./projects.svelte";

export type Schema = Record<string, unknown>;

/** What a run was given, in one line: its subject skill, else its fields' values. */
export function inputSummary(input: SessionInput | null | undefined): string | null {
  if (input?.subject?.skill) return `the skill ${input.subject.skill}`;
  const values = Object.values(input?.fields ?? {})
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
  kind: "text" | "number" | "boolean" | "choice" | "json";
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

export function fieldsOf(schema: Schema | null | undefined): Field[] {
  const required = Array.isArray(schema?.required) ? (schema.required as string[]) : [];
  return properties(schema).map(([key, s]) => {
    const choices = Array.isArray(s.enum) ? s.enum.map(String) : [];
    const kind: Field["kind"] = choices.length
      ? "choice"
      : s.type === "string"
        ? "text"
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

/** The form's values as a run's `fields`: empty optional ones left out; throws on bad JSON. */
export function fieldValues(fields: Field[], values: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const f of fields) {
    const v = values[f.key];
    if (v === undefined || v === "" || v === null) continue;
    if (f.kind === "number") out[f.key] = Number(v);
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

/** How a run is doing: running, then its result (valid or not), or why it has none. */
export function runState(s: Session): "running" | "done" | "invalid" | "no result" {
  if (s.state === "starting" || s.state === "running") return "running";
  if (s.output) return s.output.valid ? "done" : "invalid";
  return "no result";
}

/** A built-in agent's defaults, the form it is set up with (D.18): its models are chosen there;
 *  from then on its settings are the user's. */
export function builtinSpec(t: BuiltinAgent): AgentSpec {
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
    interface: t.interface ? JSON.stringify(t.interface, null, 2) : "",
  };
}
