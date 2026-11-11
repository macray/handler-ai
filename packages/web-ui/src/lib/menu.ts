// The menu's rules: each pinned project shows one dot for its sessions, the most urgent state
// winning; what an install's menu shows as it grows; the bell's three states; Pinned reordered
// by dragging.
import type { SessionStatus } from "./sessions.svelte";

/** A place's sessions, most urgent first; stopped and failed ones say nothing on the place. */
const RANK: SessionStatus[] = ["needs-you", "replied", "working", "starting", "idle", "elsewhere"];

export interface PlaceDot {
  status: SessionStatus | null; // none: nothing runs there
  needYou: number; // more than one: a count instead of the dot
  title: string; // what each state counts, "2 need you · 1 working"
}

export function placeDot(statuses: SessionStatus[]): PlaceDot {
  const counted = RANK.map((s) => [s, statuses.filter((x) => x === s).length] as const).filter(([, n]) => n);
  const said = (s: SessionStatus, n: number) => (s === "needs-you" ? (n > 1 ? "need you" : "needs you") : s === "elsewhere" ? "open elsewhere" : s);
  return {
    status: counted[0]?.[0] ?? null,
    needYou: statuses.filter((s) => s === "needs-you").length,
    title: counted.map(([s, n]) => `${n} ${said(s, n)}`).join(" · "),
  };
}

/** What the menu holds beyond the bell, Projects, Pinned and Settings: Chat and Apps once a
 *  model is connected (an account or a provider ready), Library once a project exists. Hidden
 *  is never unreachable: each page still opens by its address. */
export interface MenuUse {
  projects: number;
  modelReady: boolean;
}

export function menuShows(use: MenuUse): { chat: boolean; apps: boolean; library: boolean } {
  return { chat: use.modelReady, apps: use.modelReady, library: use.projects > 0 };
}

/** The bell: quiet, running (a green dot), or waiting (amber, with the count). */
export type BellState = "quiet" | "running" | "waiting";

export function bellState(waiting: number, running: number): BellState {
  return waiting ? "waiting" : running ? "running" : "quiet";
}

/** The list with the item at `from` moved to `to` (Pinned, reordered by dragging). */
export function moved<T>(items: T[], from: number, to: number): T[] {
  if (from === to || from < 0 || from >= items.length) return items;
  const rest = items.filter((_, i) => i !== from);
  rest.splice(Math.max(0, Math.min(to, rest.length)), 0, items[from]!);
  return rest;
}
