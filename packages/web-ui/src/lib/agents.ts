// Agents: what sessions open on. One goal: its models, harnesses on accounts or providers (what,
// one per session), working in a folder (where; an ad-hoc agent may have none: each session gets its own), with its settings:
// network (mode, log-only, extra hosts), permission mode, addon configurations, knowledge
// folders, confinement, display, and an interface (D.18: its runs take an input and give a
// result back). Its home, never changed: a project, an app (or Chat), or none (Other folders:
// made there or by the CLI). Their requests are built by projects.svelte.ts (`agentBody`).
//
// Also the helpers shared by agent forms and lists (badges, folder names, "2 hours ago").
import { accessOf, requested } from "./access";
import { api } from "./api";
import type { Agent, AgentOrigin, Connection, ModelAccess } from "./contracts.gen";
import { harnesses } from "./harnesses.svelte";

export type PermissionMode = Agent["permissions"];

/** The permission modes as handler names them: in the agent form and in a session's mode selector. */
export const PERMISSION_LABEL: Record<PermissionMode, string> = {
  ask: "Ask first",
  "accept-edits": "Auto edits",
  bypass: "Auto-approve",
};

/** A harness's ACP session modes that are handler's permission modes (B.3): session mode id → mode. */
export async function permissionModes(harness: string): Promise<Record<string, PermissionMode>> {
  const modes = (await harnesses.load()).find((h) => h.name === harness)?.sessionModes ?? {};
  return Object.fromEntries(Object.entries(modes).map(([mode, id]) => [id, mode as PermissionMode]));
}

/** What a session mode lets the agent do, as its colour says it: plan mode (teal), edits without
 *  asking (violet), everything without asking (amber: it weakens what the sandbox asks), asking
 *  first (neutral). `kind`: the permission mode it is, when it is one of handler's. */
export function modeTone(id: string, kind?: PermissionMode): "plan" | "edits" | "bypass" | "ask" {
  if (kind === "bypass") return "bypass";
  if (kind === "accept-edits") return "edits";
  if (kind === "ask") return "ask";
  return /plan/i.test(id) ? "plan" : "ask";
}

/** The mode after `current`, in the harness's order (Shift+Tab), back to the first after the last. */
export function nextMode(modes: { id: string }[], current: string | null): string | null {
  if (!modes.length) return null;
  const at = modes.findIndex((m) => m.id === current);
  return modes[(at + 1) % modes.length]!.id;
}

/** The agents' terminals (`handler terminal`, D.16) handlerd knows, newest first. */
export function terminalsOf(agents: Agent[]): { agent: Agent; conn: Connection & { terminal: ModelAccess } }[] {
  return agents
    .flatMap((agent) => agent.connections.flatMap((conn) => (conn.terminal ? [{ agent, conn: { ...conn, terminal: conn.terminal } }] : [])))
    .sort((a, b) => b.conn.since.localeCompare(a.conn.since));
}

/** The app an agent is one of the parts of (its home, H.14): listed and opened on its page
 *  only, started by the app. */
export function appOf(a: Pick<Agent, "app">): string | null {
  return a.app ?? null;
}

/** Someone you talk to in Chat: an agent whose home is Chat (D.1). */
export function isChat(a: Pick<Agent, "chat">): boolean {
  return a.chat ?? false;
}

/** `path` is `folder` or below it. */
export function inFolder(path: string, folder: string): boolean {
  return path === folder || path.startsWith(folder.endsWith("/") ? folder : `${folder}/`);
}

/** Where an agent works: its folder, or a new one each session (folderless, D.18). */
export function whereLabel(a: Pick<Agent, "scope">): string {
  return a.scope ?? "a new folder each session";
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

/** The day a time falls on, as a timeline or the inbox heads it: "Today", "Yesterday", a weekday
 *  this week, else its date (with its year, another year's). */
export function dayOf(iso: string, now = new Date()): string {
  const d = new Date(iso);
  const start = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const days = Math.round((start(now) - start(d)) / 86_400_000);
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 7) return d.toLocaleDateString(undefined, { weekday: "long" });
  const year = d.getFullYear() === now.getFullYear() ? undefined : "numeric";
  return d.toLocaleDateString(undefined, { day: "numeric", month: "long", year });
}

/** The time of day, as a timeline shows it: "14:02". */
export function clockTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
}

/** What an agent was set up from, by name: an agents file (D.23) or one of Handler's needs
 *  (D.18); null for an app's need (it is the app's part) or none. */
export function setUpFrom(origin: AgentOrigin | null | undefined): string | null {
  return origin && origin.kind !== "app" ? origin.name : null;
}
