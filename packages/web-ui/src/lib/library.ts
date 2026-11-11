// The Library: what you get and manage, on shelves by who they are for (For you: Apps, Agents;
// For your agents: Tools, Skills, Notes, Automations). Each shelf is a tab of the same header, with its
// count; the pages that were in the menu (addons, skills, knowledge, automations) are its
// shelves, at their address too. A shelf shows yours, or what you can get more of (the sources'
// items, Handler's examples: what Discover was, by shelf); Notes has nothing to get. One column
// for all of them, so the tabs stay put from one shelf to the next.
import AppWindow from "@lucide/svelte/icons/app-window";
import Bot from "@lucide/svelte/icons/bot";
import BookOpen from "@lucide/svelte/icons/book-open";
import CalendarClock from "@lucide/svelte/icons/calendar-clock";
import Sparkles from "@lucide/svelte/icons/sparkles";
import Wrench from "@lucide/svelte/icons/wrench";
import type { Component } from "svelte";
import type { PageTab } from "../components/PageHeader.svelte";
import type { Agent, Project } from "./contracts.gen";
import { href, LIBRARY_SHELVES, type LibraryShelf } from "./router.svelte";

export const LIBRARY_WIDTH = "max-w-5xl";

/** The shelves with something to get more of. */
export const GETS_MORE: Record<LibraryShelf, boolean> = { apps: true, agents: true, tools: true, skills: true, notes: false, automations: true };

const ICONS: Record<LibraryShelf, Component> = { apps: AppWindow, agents: Bot, tools: Wrench, skills: Sparkles, notes: BookOpen, automations: CalendarClock };

export function libraryTabs(active: LibraryShelf, counts: Partial<Record<LibraryShelf, number>> = {}): PageTab[] {
  return LIBRARY_SHELVES.map((s) => ({
    label: s.label,
    href: href({ view: "library", shelf: s.id }),
    active: s.id === active,
    count: counts[s.id],
    icon: ICONS[s.id],
    group: s.for === "you" ? "For you" : "For your agents",
    testid: `shelf-${s.id}`,
  }));
}

/** The Agents shelf's Yours: who they are (the agents of your projects and those outside
 *  projects; not an app's, Chat's nor Handler's helpers, kept where they are used), and where
 *  each came from: an agents file (D.23, from a source or a file: its name), else made here. */
export type ShelfAgent = { agent: Agent; from: string | null };
export type AgentGroup = { project: Project | null; agents: ShelfAgent[] }; // null: outside projects
export type AgentFilter = "all" | "others" | "here";

export function yourAgents(agents: Agent[]): ShelfAgent[] {
  return agents
    .filter((a) => !a.app && !a.chat && a.origin?.kind !== "handler-need")
    .map((agent) => ({ agent, from: agent.origin?.kind === "agents-file" ? agent.origin.name : null }));
}

/** By project (by name), then outside projects; each group by name; a group with none shown is left out. */
export function agentGroups(agents: ShelfAgent[], projects: Project[], filter: AgentFilter = "all"): AgentGroup[] {
  const kept = agents.filter((a) => filter === "all" || (filter === "others") === (a.from !== null));
  const named = (list: ShelfAgent[]) => [...list].sort((x, y) => (x.agent.name ?? x.agent.scope ?? "").localeCompare(y.agent.name ?? y.agent.scope ?? ""));
  const groups: AgentGroup[] = [...projects]
    .sort((a, b) => a.name.localeCompare(b.name))
    .map((project) => ({ project, agents: named(kept.filter((a) => a.agent.projectId === project.id)) }));
  groups.push({ project: null, agents: named(kept.filter((a) => !a.agent.projectId || !projects.some((p) => p.id === a.agent.projectId))) });
  return groups.filter((g) => g.agents.length);
}
