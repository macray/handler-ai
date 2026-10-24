// The menu's two rules about the pinned projects: they are grouped under their area's name (each
// area named once, in its colour, instead of a tag on every row), and each shows one dot for its
// sessions, the most urgent state winning.
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

export interface AreaGroup<T> {
  area: string | null; // null: no area (or one no longer defined)
  items: T[];
}

/** The items by area, in the areas' order, those of no area last; empty groups left out. */
export function byArea<T extends { area?: string | null }>(items: T[], areaOrder: string[]): AreaGroup<T>[] {
  const known = new Set(areaOrder);
  const groups: AreaGroup<T>[] = areaOrder.map((area) => ({ area, items: items.filter((i) => i.area === area) }));
  groups.push({ area: null, items: items.filter((i) => !i.area || !known.has(i.area)) });
  return groups.filter((g) => g.items.length);
}
