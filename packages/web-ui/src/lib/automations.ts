// Automations (contract I): when a session stops or at a time, handler runs a script, an agent or an
// app's route. What the pages say of one in words: when it runs, what it runs, a run.
import type { Automation, AutomationRun, Schedule } from "./contracts.gen";
import { slug } from "./text";

/** When it runs, as a sentence: "Every 1h", "At 08:30 on mon, fri", "When a session of project shop stops". */
export function whenSentence(definition: Automation | null | undefined): string {
  if (!definition) return "";
  const when = definition.when;
  if (typeof when !== "string") {
    if (when.every) return `Every ${when.every}`;
    return `At ${when.at}${when.days?.length ? ` on ${when.days.join(", ")}` : ""}`;
  }
  const only = definition.only;
  const who: string[] = [];
  if (only?.project?.length) who.push(`of project ${only.project.join(", ")}`);
  if (only?.agent?.length) who.push(`of agent ${only.agent.join(", ")}`);
  return who.length ? `When a session ${who.join(" and ")} stops` : "When any session stops";
}

export function onSchedule(definition: Automation | null | undefined): boolean {
  return !!definition && typeof definition.when !== "string";
}

export const RUN_STATE: Record<AutomationRun["state"], string> = {
  queued: "waiting",
  running: "running",
  succeeded: "succeeded",
  failed: "failed",
  cancelled: "cancelled",
  interrupted: "interrupted",
};

export function ended(run: AutomationRun): boolean {
  return run.state !== "queued" && run.state !== "running";
}

/** Its model use in short: "2 calls · 1 200 tokens"; empty when it is not a script's. */
export function usage(run: AutomationRun): string {
  const llm = run.llm;
  if (!llm?.calls) return "";
  const tokens = (llm.inTokens ?? 0) + (llm.outTokens ?? 0);
  return `${llm.calls} call${llm.calls === 1 ? "" : "s"} · ${tokens.toLocaleString()} tokens`;
}

/** What a scheduled run says of the slots before it: "3 missed before (handler was not running)". */
export function missedSentence(run: AutomationRun): string {
  const n = run.missed ?? 0;
  if (!n) return "";
  return `${n} slot${n === 1 ? "" : "s"} missed before it (Handler was not running): only the latest runs`;
}

export type Day = "mon" | "tue" | "wed" | "thu" | "fri" | "sat" | "sun";
export const DAYS: Day[] = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
export const WEEKDAYS: Day[] = ["mon", "tue", "wed", "thu", "fri"];

/** A schedule's form (I.2): every N minutes or hours, or at a time on some days. */
export type ScheduleForm = { kind: "every"; n: number; unit: "m" | "h" } | { kind: "at"; at: string; days: Day[] };

export const SCHEDULE_PRESETS: { label: string; form: ScheduleForm }[] = [
  { label: "Every hour", form: { kind: "every", n: 1, unit: "h" } },
  { label: "Every morning at 08:30", form: { kind: "at", at: "08:30", days: [...DAYS] } },
  { label: "Weekdays at 08:30", form: { kind: "at", at: "08:30", days: [...WEEKDAYS] } },
  { label: "Mondays at 09:00", form: { kind: "at", at: "09:00", days: ["mon"] } },
];

/** The form as automation.toml's `when`; every day is `days` left out. */
export function scheduleOf(form: ScheduleForm): Schedule {
  if (form.kind === "every") return { every: `${form.n}${form.unit}` };
  return form.days.length === DAYS.length ? { at: form.at } : { at: form.at, days: DAYS.filter((d) => form.days.includes(d)) };
}

/** Why the schedule's form cannot be saved (I.2), or null. */
export function scheduleProblem(form: ScheduleForm): string | null {
  if (form.kind === "every") {
    if (!Number.isInteger(form.n) || form.n < 1 || form.n > 9999) return "Give a whole number.";
    return form.unit === "m" && form.n < 5 ? "At least every 5 minutes." : null;
  }
  if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(form.at)) return "Give a time, like 08:30.";
  return form.days.length ? null : "Choose at least one day.";
}

/** An agent run's result must say how it went and what it found (I.3), as the server checks. */
export function resultProblems(result: unknown): string[] {
  const schema = (result && typeof result === "object" ? result : {}) as Record<string, unknown>;
  const props = (schema.properties ?? {}) as Record<string, Record<string, unknown> | undefined>;
  const required = Array.isArray(schema.required) ? (schema.required as string[]) : [];
  const found: string[] = [];
  const status = props.status?.enum;
  if (!required.includes("status") || !Array.isArray(status) || !status.length) found.push("a required status (ok, attention, failed)");
  else if (status.some((v) => !["ok", "attention", "failed"].includes(v as string))) found.push("a status of only ok, attention, failed");
  if (!required.includes("summary") || props.summary?.type !== "string") found.push("a required summary (a string)");
  return found;
}

/** Whether an automation runs that agent: the one its names were bound to (I.1), by id. */
export function runsAgent(automation: { agentId?: string | null }, agentId: string): boolean {
  return automation.agentId === agentId;
}

/** A name for a new automation: "reviewer-hourly" from the agent's name and its schedule. */
export function suggestName(what: string, form: ScheduleForm | null): string {
  const when = !form
    ? "on-stop"
    : form.kind === "every"
      ? form.n === 1 && form.unit === "h"
        ? "hourly"
        : `every-${form.n}${form.unit}`
      : form.days.length === DAYS.length
        ? "daily"
        : form.days.length === 5 && WEEKDAYS.every((d) => form.days.includes(d))
          ? "weekdays"
          : form.days.join("-");
  return `${slug(what) || "automation"}-${when}`.slice(0, 64).replace(/-+$/, "");
}

/** The automations that are on and run that agent (by id, I.1). */
export function schedulesOf<T extends { enabled?: boolean; agentId?: string | null }>(list: T[], agentId: string): T[] {
  return list.filter((a) => a.enabled && runsAgent(a, agentId));
}

/** What the new-automation form holds; `definitionOf` reads it back from a definition. */
export type AutomationForm = {
  on: "time" | "stop";
  schedule: ScheduleForm; // with on = "time"
  stopProject: string; // with on = "stop": "" any session
  what: "agent" | "app";
  agent: { name: string; project: string | null; fields: Record<string, unknown> } | null;
  app: string;
  call: string;
  opens: string; // an agent run's: the app its inbox messages open ("" none)
  description: string;
};

/** A definition as the form shows it; null when the form cannot say it (a script, `only` with
 *  agents or several projects): its file is then where it is edited. */
export function formOf(definition: Automation | null | undefined): AutomationForm | null {
  if (!definition || typeof definition.run === "string") return null;
  const only = definition.only;
  if (only?.agent?.length || (only?.project?.length ?? 0) > 1) return null;
  const when = definition.when;
  let schedule: ScheduleForm = { kind: "at", at: "08:30", days: [...DAYS] };
  if (typeof when !== "string") {
    if (when.every) {
      const m = /^(\d+)([mh])$/.exec(when.every);
      if (!m) return null;
      schedule = { kind: "every", n: Number(m[1]), unit: m[2] as "m" | "h" };
    } else schedule = { kind: "at", at: when.at ?? "08:30", days: when.days?.length ? DAYS.filter((d) => when.days?.includes(d)) : [...DAYS] };
  }
  const run = definition.run;
  return {
    on: typeof when === "string" ? "stop" : "time",
    schedule,
    stopProject: only?.project?.[0] ?? "",
    what: "agent" in run ? "agent" : "app",
    agent:
      "agent" in run
        ? { name: run.agent, project: run.project ?? null, fields: { ...(run.input?.fields ?? {}) } }
        : null,
    app: "app" in run ? run.app : "",
    call: "app" in run ? run.call : "POST /api/",
    opens: definition.app ?? "",
    description: definition.description ?? "",
  };
}

/** How often a schedule runs, in words: "about 24 runs a day", "5 runs a week". */
export function howOften(form: ScheduleForm): string {
  if (form.kind === "at") return `${form.days.length} run${form.days.length === 1 ? "" : "s"} a week`;
  const minutes = form.n * (form.unit === "h" ? 60 : 1);
  if (minutes <= 1440) {
    const day = Math.round(1440 / minutes);
    return `${1440 % minutes ? "about " : ""}${day} run${day === 1 ? "" : "s"} a day`;
  }
  const week = Math.round((7 * 1440) / minutes);
  return week >= 1 ? `about ${week} run${week === 1 ? "" : "s"} a week` : "less than one run a week";
}

/** What it runs, as the Library's filters say it: one of your agents, an app's route, or your
 *  script; null while its definition cannot be read. */
export type RunsKind = "agent" | "app" | "script";
export function runsKind(definition: Automation | null | undefined): RunsKind | null {
  const run = definition?.run;
  if (run === undefined) return null;
  if (typeof run === "string") return "script";
  return "agent" in run ? "agent" : "app";
}

/** What it runs, in a word or two: the agent's name ("Reviewer"), "Planner's route", "your
 *  script". `agentName`: the name of the agent it is bound to (I.1), when there is one. */
export function runsWords(definition: Automation | null | undefined, agentName?: string): string {
  const run = definition?.run;
  if (run === undefined) return "";
  if (typeof run === "string") return "your script";
  if ("agent" in run) return agentName || run.agent;
  return `${run.app}'s route`;
}
