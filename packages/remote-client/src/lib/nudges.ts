// Nudges on the phone (H.17): what an app asks the person to do, in their inbox. An action's
// nudge is its form, drawn here from the action's JSON Schema (`nudge.form`, the same hints as the
// web UI's: "x-handler": "long-text" on a string, several lines), filled in beforehand by the app
// (`nudge.fields`) or from what the person said; a page's opens the app there. How often it alerts
// again is the person's, per `<app>/<nudge>` (`nudge.setting`), stepped from "As the app says" to "Never alert me".
import type { InboxMessage, InboxNudge, NudgeSettingParams } from "./remote.gen";

export type Schema = Record<string, unknown>;

/** One input of a nudge's form, from its action's `fields` schema. */
export type Field = {
  key: string;
  title: string;
  description?: string;
  kind: "text" | "long-text" | "number" | "boolean" | "choice" | "list" | "json";
  choices: string[];
  required: boolean;
};

function titleOf(key: string, schema: Schema): string {
  if (typeof schema.title === "string") return schema.title;
  const words = key.replace(/([a-z])([A-Z])/g, "$1 $2").replace(/[_-]+/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1).toLowerCase();
}

/** The form's inputs, in the schema's order. */
export function fieldsOf(schema: Schema | null | undefined): Field[] {
  const props = schema?.properties;
  if (!props || typeof props !== "object") return [];
  const required = Array.isArray(schema?.required) ? (schema.required as string[]) : [];
  return (Object.entries(props) as [string, Schema][]).map(([key, s]) => {
    const choices = Array.isArray(s.enum) ? s.enum.map(String) : [];
    const kind: Field["kind"] = choices.length
      ? "choice"
      : s.type === "string"
        ? s["x-handler"] === "long-text"
          ? "long-text"
          : "text"
        : s.type === "number" || s.type === "integer"
          ? "number"
          : s.type === "boolean"
            ? "boolean"
            : s.type === "array" && (s.items as Schema | undefined)?.type === "string"
              ? "list"
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

/** `fields` (the app's draft, or what was said) as the form shows them: a list one per line,
 *  JSON as text, a number as typed; what the form has no input for is left out. */
export function formValues(fields: Field[], input: Record<string, unknown> | null | undefined): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const f of fields) {
    const v = input?.[f.key];
    if (v === undefined || v === null) continue;
    if (f.kind === "list") out[f.key] = Array.isArray(v) ? v.map(String).join("\n") : String(v);
    else if (f.kind === "json") out[f.key] = JSON.stringify(v);
    else if (f.kind === "boolean") out[f.key] = v === true;
    else out[f.key] = String(v);
  }
  return out;
}

/** The form's values as the action's `fields`: empty optional ones left out, a number as a
 *  number, a list one per line; throws on a number or JSON that is not one, or a required
 *  field left empty. */
export function fieldValues(fields: Field[], values: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const f of fields) {
    const v = values[f.key];
    if (f.kind === "boolean") {
      if (v === true || f.required) out[f.key] = v === true;
      continue;
    }
    const text = v === undefined || v === null ? "" : String(v).trim();
    if (!text) {
      if (f.required) throw new Error(`${f.title}: needed`);
      continue;
    }
    if (f.kind === "number") {
      const n = Number(text);
      if (Number.isNaN(n)) throw new Error(`${f.title}: not a number`);
      out[f.key] = n;
    } else if (f.kind === "list") {
      out[f.key] = text
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean);
    } else if (f.kind === "json") {
      try {
        out[f.key] = JSON.parse(text);
      } catch {
        throw new Error(`${f.title}: not JSON`);
      }
    } else out[f.key] = f.kind === "long-text" ? String(v) : text;
  }
  return out;
}

export type Setting = NudgeSettingParams["setting"];

/** How often a nudge alerts again, most to least. */
export const SETTINGS: readonly Setting[] = ["default", "once", "silent"];

export const SETTING_WORDS: Record<Setting, string> = {
  default: "As the app says",
  once: "No reminders",
  silent: "Never alert me (it stays here)",
};

/** "Remind me less": one step down, null at the lowest. */
export function less(setting: Setting): Setting | null {
  return SETTINGS[SETTINGS.indexOf(setting) + 1] ?? null;
}

/** "Remind me more": one step up, null at the highest. */
export function more(setting: Setting): Setting | null {
  const i = SETTINGS.indexOf(setting);
  return i > 0 ? SETTINGS[i - 1]! : null;
}

/** The inbox once a nudge's setting changed: every open nudge of that app and name has it, as
 *  the host made them. */
export function withSetting(inbox: InboxMessage[], app: string, name: string, setting: Setting): InboxMessage[] {
  return inbox.map((m) =>
    m.app === app && m.nudge?.name === name && (m.nudge.state ?? "open") === "open" ? { ...m, nudge: { ...m.nudge, setting } } : m,
  );
}

/** An ended nudge's state in words (an open one: null). */
export function endedWords(nudge: InboxNudge): string | null {
  switch (nudge.state ?? "open") {
    case "done":
      return "Done";
    case "dismissed":
      return "Dismissed";
    case "expired":
      return nudge.ifIgnored ? `Expired: ${nudge.ifIgnored}` : "Expired";
    default:
      return null;
  }
}
