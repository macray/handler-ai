// Agents set up from definitions: those of an agents file (D.23: a project's agents exported,
// read again to be set up elsewhere), the one of Handler's needs (D.18: its helpers), an app's
// (H.2). Set up on one page that asks each agent for what it needs (its model, a configuration
// of each addon, a knowledge folder for each it reads), then creates its agents with the origin
// of what they were set up from.
import { chosen, noAccess, type ModelAccess } from "./access";
import type { AgentDefinition, AgentOrigin, AgentRequest, AgentsFile, BindingInfo, HandlerNeed } from "./contracts.gen";
import { agentBody, type AgentSpec } from "./projects.svelte";
import { definitionSpec } from "./runs";

/** An agent's name in an agents file, as handlerd makes it (agents_files.slug): "Order triage" →
 *  "order-triage". */
export function slug(name: string): string {
  return (name.toLowerCase().match(/[a-z0-9]+/g) ?? []).join("-").slice(0, 60) || "agent";
}

/** What one agent set up from a definition needs from you, in words. */
export function needsOf(d: AgentDefinition): string[] {
  return [
    d.modelAlone ? "a provider" : "its model",
    ...(d.addons ?? []).map((a) => `a configuration of ${a}`),
    ...(d.knowledge ?? []).map((k) => `a knowledge folder: ${k}`),
  ];
}

/** What you choose for one agent when setting it up. */
export type Choice = {
  model: ModelAccess;
  bindings: Record<string, string>; // addon → the configuration given ("": none yet)
  knowledge: Record<string, string>; // the name it reads → the folder given ("": none yet)
};

/** Its first choices: a configuration of each addon when you have one, the knowledge folder of
 *  the same name when you have it; its model is always yours to choose. */
export function firstChoice(d: AgentDefinition, bindings: BindingInfo[], folders: string[]): Choice {
  const valid = bindings.filter((b) => !b.error);
  return {
    model: noAccess(),
    bindings: Object.fromEntries((d.addons ?? []).map((a) => [a, valid.find((b) => b.addon === a)?.name ?? ""])),
    knowledge: Object.fromEntries((d.knowledge ?? []).map((k) => [k, folders.includes(k) ? k : ""])),
  };
}

/** What is still to choose before it can be set up, in words (none: ready). */
export function missing(d: AgentDefinition, c: Choice): string[] {
  return [
    ...(chosen(c.model, d.modelAlone ?? false) ? [] : [d.modelAlone ? "a provider" : "its model"]),
    ...Object.entries(c.bindings).flatMap(([addon, b]) => (b ? [] : [`a configuration of ${addon}`])),
    ...Object.entries(c.knowledge).flatMap(([name, k]) => (k ? [] : [`a knowledge folder for ${name}`])),
  ];
}

/** An agent's settings: its definition's (an agents file's agent, a need's), with what you
 *  chose. */
export function chosenSpec(d: AgentDefinition, c: Choice): AgentSpec {
  return {
    ...definitionSpec(d),
    model: { ...c.model },
    bindings: Object.values(c.bindings).filter(Boolean),
    knowledge: Object.values(c.knowledge).filter(Boolean),
  };
}

/** The origin of an agent set up from an agents file's agent (D.23). */
export function fileOrigin(f: Pick<AgentsFile, "name" | "version">, part: string): AgentOrigin {
  return { kind: "agents-file", name: f.name, version: f.version, agent: part };
}

/** The origin of an agent set up for one of Handler's needs (D.18, its current version). */
export function needOrigin(n: Pick<HandlerNeed, "name" | "version">): AgentOrigin {
  return { kind: "handler-need", name: n.name, version: n.version };
}

/** The request that makes it an agent of a project (D.8), set up from `d`. What it may do was
 *  shown beside the page's button: pressing it confirms (D.8). */
export function projectAgentBody(origin: AgentOrigin, d: AgentDefinition, c: Choice, projectId?: string): AgentRequest {
  return { ...agentBody(chosenSpec(d, c), { projectId }, true), origin };
}

/** The request that makes it an agent outside projects (D.2): in `folder`, else a folder per
 *  session. */
export function outsideAgentBody(origin: AgentOrigin, d: AgentDefinition, c: Choice, folder: string | null): AgentRequest {
  return { ...agentBody(chosenSpec(d, c), { scope: folder }, true), origin };
}

/** What an agent set up from a definition may do, in one line each: what the set-up page shows beside its
 *  button. */
export function mayDo(d: AgentDefinition, folder: string | null): string[] {
  if (d.modelAlone) return [`nothing outside its call${d.knowledge?.length ? `; its knowledge is sent to its provider` : ""}`];
  const hosts = d.allow ?? [];
  return [
    folder ? `read and write ${folder}` : "a new folder each session",
    d.network === "none"
      ? "no network"
      : d.network === "open"
        ? "reach any host"
        : `reach its model${d.addons?.length ? ", its addons' hosts" : ""}${hosts.length ? `, ${hosts.join(", ")}` : ""}${d.egress === "log-only" ? " (every host, logged)" : ""}`,
    d.permissions === "bypass" ? "never asks before acting" : "asks before it acts",
    ...(d.confinement === "nested" ? ["run containers (a weaker sandbox)"] : d.confinement === "privileged" ? ["run privileged (about as safe as no sandbox)"] : []),
    ...(d.display ? ["use your screen and clipboard"] : []),
  ];
}

/** A name not taken there (names compared without case): "Skill reviewer", else "Skill reviewer 2"… */
export function freeName(name: string, taken: string[]): string {
  const used = new Set(taken.map((t) => t.toLowerCase()));
  let found = name;
  for (let n = 2; used.has(found.toLowerCase()); n++) found = `${name} ${n}`;
  return found;
}
