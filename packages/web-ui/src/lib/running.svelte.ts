// Running: every running session of every project and of the agents outside projects, in one
// place (Chat's conversations and an app's own agents are theirs, not here), with the terminals
// of `handler terminal` (D.16) as a line at its foot. What this browser remembers of it
// (localStorage, as the files pane): the sessions hidden, their order, the layout, the menu
// folded (full screen). The project chips only filter, and are not kept.
//
// Attaching (F.7): a session this browser opened stays attached while it runs (the session store);
// one started elsewhere (`discovered`) is attached only while its pane is on the stage, so it
// can still stop when idle once it is not shown (`watch`).
import { duration } from "@handler/acp-view/lib/tools";
import { onChange } from "./events.svelte";
import { api } from "./api";
import { terminalsOf } from "./agents";
import type { Agent } from "./contracts.gen";
import { sessions, type LiveSession, type SessionStatus } from "./sessions.svelte";

export type Layout = "one" | "columns" | "grid";
export const LAYOUTS: Layout[] = ["one", "columns", "grid"];

export interface Prefs {
  hidden: string[]; // sessions hidden from All running (ids)
  order: string[]; // the panes' order, as dragged (ids); the others follow, oldest first
  layout: Layout;
  folded: boolean; // full screen: the menu folded
}

const STORAGE = "handler.running";
export const DEFAULT_PREFS: Prefs = { hidden: [], order: [], layout: "grid", folded: false };

/** The prefs kept, whatever was stored (nothing, or something unreadable: the defaults). */
export function readPrefs(text: string | null): Prefs {
  try {
    const p = JSON.parse(text ?? "{}") as Partial<Prefs>;
    const ids = (v: unknown) => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []);
    return {
      hidden: ids(p.hidden),
      order: ids(p.order),
      layout: LAYOUTS.includes(p.layout as Layout) ? (p.layout as Layout) : DEFAULT_PREFS.layout,
      folded: p.folded === true,
    };
  } catch {
    return { ...DEFAULT_PREFS };
  }
}

/** Grid: the shape that fits every pane shown, 2 × 2 up to 4, 3 × 2 up to 6, 3 × 3 up to 9;
 *  beyond 9, three columns and rows of a third of the stage, which scrolls. */
export function gridShape(n: number): { cols: number; rows: number } {
  if (n <= 1) return { cols: 1, rows: 1 };
  if (n === 2) return { cols: 2, rows: 1 };
  if (n <= 4) return { cols: 2, rows: 2 };
  if (n <= 6) return { cols: 3, rows: 2 };
  return { cols: 3, rows: Math.max(3, Math.ceil(n / 3)) };
}

/** Each pane's width, in sixths of the stage: a full row's panes share it, and the last row's
 *  widen to fill it rather than leave a hole (three in 2 × 2: the third takes the whole row). */
export function spans(n: number, cols: number): number[] {
  const last = n % cols || cols;
  return Array.from({ length: n }, (_, i) => (i >= n - last ? 6 / last : 6 / cols));
}

/** `items` in the order dragged: those in `order` first, as there, then the others as given. */
export function ordered<T extends { key: string }>(items: T[], order: string[]): T[] {
  const at = new Map(order.map((k, i) => [k, i]));
  const placed = items.filter((x) => at.has(x.key)).sort((a, b) => at.get(a.key)! - at.get(b.key)!);
  return [...placed, ...items.filter((x) => !at.has(x.key))];
}

/** When each session that needs you started to (a rising count, not a time: never a tie), from
 *  what was noted before: those still waiting keep theirs, a new one gets `next()`, the others go. */
export function waitingSince(before: Record<string, number>, needing: string[], next: () => number): Record<string, number> {
  return Object.fromEntries(needing.map((k) => [k, before[k] ?? next()]));
}

/** The stage's order: those that need you first, the latest to ask first; then the others in the
 *  order dragged (`ordered`). Stable while you look: a tile moves only when its state changes
 *  (it asks, or is answered), never as it works or finishes a turn. */
export function byState<T extends { key: string; needsYou: boolean }>(
  items: T[],
  order: string[],
  since: Record<string, number>,
): T[] {
  const asked = (x: T) => since[x.key] ?? 0;
  const needing = items.filter((x) => x.needsYou).sort((a, b) => asked(b) - asked(a));
  return [...needing, ...ordered(items.filter((x) => !x.needsYou), order)];
}

/** The order after dragging `from` onto `to`'s place, among the `keys` shown in their order. */
export function dropped(keys: string[], from: string, to: string): string[] {
  const i = keys.indexOf(from);
  const j = keys.indexOf(to);
  if (i < 0 || j < 0 || i === j) return keys;
  const rest = keys.filter((k) => k !== from);
  rest.splice(j, 0, from);
  return rest;
}

/** What the stage shows of `items`: those of the chip's project (null: All), not hidden; a hidden
 *  one that needs you comes back while it waits (`back`), and goes again once answered. */
export function onStage<T extends { key: string; project: string | null; needsYou: boolean }>(
  items: T[],
  chip: string | null | undefined,
  hidden: string[],
): { shown: T[]; hidden: T[]; back: Set<string> } {
  const mine = items.filter((x) => chip === undefined || chip === null || (x.project ?? "") === chip);
  const isHidden = (x: T) => hidden.includes(x.key);
  return {
    shown: mine.filter((x) => !isHidden(x) || x.needsYou),
    hidden: mine.filter(isHidden),
    back: new Set(mine.filter((x) => isHidden(x) && x.needsYou).map((x) => x.key)),
  };
}

/** A session listed in Running: not Chat's, not an app's; stopped ones stay in their project's
 *  timeline. */
export function listed(s: LiveSession): boolean {
  return !s.agent.chat && !s.info.app && s.status !== "stopped" && !sessions.stopping.has(s.key);
}

/** Since when it is in its state, short: "6m" working or waiting for you (its turn's time),
 *  "2m ago" idle; "" when not known. */
export function sinceLabel(
  s: { status: string; conn?: { turnStartedAt: number | null } | null; endedAt?: number | null; info: { lastActivityAt?: string | null } },
  now: number,
): string {
  const short = (ms: number) => duration(ms).replace(/^(\d+[hm])\d+[ms]$/, "$1");
  if (s.status === "working" || s.status === "needs-you") {
    const from = s.conn?.turnStartedAt ?? (s.info.lastActivityAt ? Date.parse(s.info.lastActivityAt) : NaN);
    return Number.isNaN(from) ? "" : short(now - from);
  }
  if (s.status === "idle" || s.status === "replied") {
    const from = s.endedAt ?? (s.info.lastActivityAt ? Date.parse(s.info.lastActivityAt) : NaN);
    if (Number.isNaN(from)) return "";
    return now - from < 60000 ? "just now" : `${short(now - from)} ago`;
  }
  return "";
}

/** A tile's state pill: four states, whatever the session's finer one (starting works, a turn
 *  replied to is idle, as is one open in another tab; failed is stopped). */
export type Pill = "needs-you" | "working" | "idle" | "stopped";
export const PILL_LABEL: Record<Pill, string> = { "needs-you": "Needs you", working: "Working", idle: "Idle", stopped: "Stopped" };
export function pillOf(status: SessionStatus): Pill {
  if (status === "needs-you") return "needs-you";
  if (status === "working" || status === "starting") return "working";
  if (status === "stopped" || status === "failed") return "stopped";
  return "idle";
}

/** The new-session pane ("+"): its form, until Start makes it the session. */
export interface NewPane {
  key: string; // "new:<n>"
  project: string | null; // chosen at first: the chip's project, else the last used
}

export type Terminal = ReturnType<typeof terminalsOf>[number];

class Running {
  prefs = $state<Prefs>(readPrefs(typeof localStorage === "undefined" ? null : localStorage.getItem(STORAGE)));
  /** The pane that has the focus (its full composer); One shows it alone. */
  focus = $state<string | null>(null);
  /** The project chip chosen: undefined All, "" outside projects, else a project's id. */
  chip = $state<string | undefined>(undefined);
  drafts = $state<NewPane[]>([]);
  terminals = $state<Terminal[]>([]);
  private made = 0;
  private following = false;

  /** The sessions listed (every project's and outside projects', running), oldest first. */
  get sessions(): LiveSession[] {
    return sessions.list.filter(listed);
  }

  /** What the menu's entry counts: the sessions and terminals running. */
  get count(): number {
    return sessions.list.filter(listed).length + this.terminals.length;
  }

  private save(): void {
    try {
      localStorage.setItem(STORAGE, JSON.stringify(this.prefs));
    } catch {
      /* storage unavailable: kept until the page is left */
    }
  }

  setLayout(layout: Layout): void {
    this.prefs = { ...this.prefs, layout };
    this.save();
  }

  setFolded(folded: boolean): void {
    this.prefs = { ...this.prefs, folded };
    this.save();
  }

  hide(key: string): void {
    if (this.prefs.hidden.includes(key)) return;
    this.prefs = { ...this.prefs, hidden: [...this.prefs.hidden, key] };
    if (this.focus === key) this.focus = null;
    this.save();
  }

  show(key: string): void {
    this.prefs = { ...this.prefs, hidden: this.prefs.hidden.filter((k) => k !== key) };
    this.save();
  }

  showAll(): void {
    this.prefs = { ...this.prefs, hidden: [] };
    this.save();
  }

  /** A pane dragged onto another's place; `keys`: the panes shown, in their order. */
  move(keys: string[], from: string, to: string): void {
    const now = dropped(keys, from, to);
    const rest = this.prefs.order.filter((k) => !now.includes(k));
    this.prefs = { ...this.prefs, order: [...now.filter((k) => !k.startsWith("new:")), ...rest] };
    this.save();
  }

  /** Ids no longer running leave what is kept, so it does not grow. */
  prune(running: string[]): void {
    const keep = (k: string) => running.includes(k);
    const hidden = this.prefs.hidden.filter(keep);
    const order = this.prefs.order.filter(keep);
    if (hidden.length === this.prefs.hidden.length && order.length === this.prefs.order.length) return;
    this.prefs = { ...this.prefs, hidden, order };
    this.save();
  }

  /** "+": a new-session pane, focused. */
  add(project: string | null): NewPane {
    const pane = { key: `new:${++this.made}`, project };
    this.drafts = [...this.drafts, pane];
    this.focus = pane.key;
    return pane;
  }

  /** The new-session pane gone: removed (×), or made the session `into` (Start). */
  drop(key: string, into?: string): void {
    this.drafts = this.drafts.filter((d) => d.key !== key);
    if (this.focus === key) this.focus = into ?? null;
  }

  /** The terminals open now, read from the agents on each change of them (none of Chat's). */
  start(): void {
    if (this.following) return;
    this.following = true;
    const load = () =>
      void api.agents().then(
        (all: Agent[]) => (this.terminals = terminalsOf(all.filter((a) => !a.chat))),
        () => {},
      );
    onChange(["agents"], load);
    load();
  }
}

export const running = new Running();
