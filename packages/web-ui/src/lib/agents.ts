// Agents: what sessions open on. One goal: its models, harnesses on accounts or providers (what,
// one per session), working in a folder (where; an ad-hoc agent may have none: each session gets its own), with its settings:
// network (mode, log-only, extra hosts), permission mode, addon configurations, knowledge
// folders, confinement, display, and an interface (D.18: its runs take an input and give a
// result back). Agents of projects are edited through their project (projects.svelte.ts);
// ad-hoc ones (no project) come from the CLI or the Agents page.
//
// Also the helpers shared by agent forms and lists (badges, folder names, "2 hours ago").
import { accessOf, requested } from "./access";
import { api } from "./api";
import type { AdHocAgentRequest, Agent, Connection, ModelAccess } from "./contracts.gen";
import { harnesses } from "./harnesses.svelte";

export type NetworkMode = Agent["network"];
export type PermissionMode = Agent["permissions"];

/** The permission modes as handler names them: in the agent form and in a session's mode selector. */
export const PERMISSION_LABEL: Record<PermissionMode, string> = {
  ask: "Ask first",
  "accept-edits": "Auto edits",
  bypass: "Auto-approve",
};

/** A harness's ACP session modes named as handler's permission modes (B.3): session mode id → label. */
export async function modeLabels(harness: string): Promise<Record<string, string>> {
  const modes = (await harnesses.load()).find((h) => h.name === harness)?.sessionModes ?? {};
  return Object.fromEntries(Object.entries(modes).map(([mode, id]) => [id, PERMISSION_LABEL[mode as PermissionMode]]));
}

/** What an ad-hoc agent is set to: the body of a full update. */
export type AdHocSpec = Required<Omit<AdHocAgentRequest, "name" | "confirmRisks">> & { name: string };

/** The settings of an existing agent, to edit them. */
export function specOf(a: Agent): AdHocSpec {
  return {
    models: a.models.map((m) => requested(accessOf(m))) as AdHocSpec["models"],
    scope: a.scope ?? null,
    name: a.name ?? "",
    description: a.description ?? null,
    instructions: a.instructions ?? null,
    skills: [...(a.skills ?? [])],
    network: a.network,
    allow: [...(a.allow ?? [])],
    egress: a.egress ?? "enforce",
    confinement: a.confinement,
    permissions: a.permissions,
    bindings: [...(a.bindings ?? [])],
    knowledge: [...(a.knowledge ?? [])],
    display: a.display ?? false,
    interface: a.interface ?? null,
    origin: a.origin ?? null,
  };
}

/** Replace an ad-hoc agent's settings (same id): hosts and log-only apply to its running
 *  sandboxes at once. */
export function saveAdHoc(id: string, spec: AdHocSpec): Promise<Agent> {
  return api.updateAdHocAgent(id, { ...spec, name: spec.name.trim() || null });
}

/** Where an agent works: its folder's name, or "a folder per session" (folderless, D.18). */
/** The agents' terminals (`handler terminal`, D.16) handlerd knows, newest first. */
export function terminalsOf(agents: Agent[]): { agent: Agent; conn: Connection & { terminal: ModelAccess } }[] {
  return agents
    .flatMap((agent) => agent.connections.flatMap((conn) => (conn.terminal ? [{ agent, conn: { ...conn, terminal: conn.terminal } }] : [])))
    .sort((a, b) => b.conn.since.localeCompare(a.conn.since));
}

/** `path` is `folder` or below it. */
export function inFolder(path: string, folder: string): boolean {
  return path === folder || path.startsWith(folder.endsWith("/") ? folder : `${folder}/`);
}

export function whereLabel(a: Pick<Agent, "scope">): string {
  return a.scope ? folderName(a.scope) : "a folder per session";
}

/** Badge status for how an agent is sandboxed: "container" is the strict default;
 *  anything else (nested containers, privileged) is worth a warning. */
export function sandboxStatus(s: { confinement?: string | null }): string {
  return s.confinement && s.confinement !== "strict" ? s.confinement : "container";
}

export function folderName(scope: string): string {
  return scope.replace(/\/+$/, "").split("/").at(-1) || scope;
}

/** "2 hours ago"-style, for "last used"; "in 7 days" for a time to come. */
export function ago(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "never";
  const delta = (now - Date.parse(iso)) / 1000;
  const steps: [number, string][] = [
    [60, "second"],
    [60, "minute"],
    [24, "hour"],
    [30, "day"],
    [12, "month"],
  ];
  let value = Math.abs(delta);
  let unit = "year";
  for (const [size, name] of steps) {
    if (value < size) {
      unit = name;
      break;
    }
    value /= size;
  }
  if (unit === "second") return delta >= 0 ? "just now" : "in a moment";
  const n = Math.floor(value);
  const span = `${n} ${unit}${n === 1 ? "" : "s"}`;
  return delta >= 0 ? `${span} ago` : `in ${span}`;
}

/** The exact time, for a hover over an `ago`: "Oct 4, 2026, 4:03 PM". */
export function exactTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}
