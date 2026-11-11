// Agents set up from definitions: those of an agents file (D.23: a project's agents exported,
// read again to be set up elsewhere), the one of Handler's needs (D.18: its helpers), an app's
// (H.2). Set up on one page that asks each agent for what it needs (its tools installed, its model,
// a configuration of each tool with settings, a knowledge folder for each it reads), then creates
// its agents with the origin of what they were set up from.
import { chosen, noAccess, type ModelAccess } from "./access";
import type { AddonInfo, AddonPreview, AddonUse, AgentDefinition, AgentOrigin, AgentRequest, AgentsFile, BindingInfo, HandlerNeed } from "./contracts.gen";
import { agentBody, type AgentSpec } from "./projects.svelte";
import { definitionSpec } from "./runs";
import { slug } from "./text";

/** An agent's name in an agents file, as handlerd makes it (agents_files.slug): "Order triage" →
 *  "order-triage". */
export function partName(name: string): string {
  return slug(name).slice(0, 60) || "agent";
}

/** Whether an agent uses the tool through a connection filling its settings (G.2). */
export function hasSlots(addon: AddonInfo): boolean {
  return !!addon.settings?.length || !!addon.secretSlots?.length;
}

/** What the tools a definition names ask of you (G.3): those not installed, to install first;
 *  those installed that have settings, a connection to each. One installed without settings
 *  asks nothing: it is used by its name. */
export function toolsAsked(names: string[], addons: AddonInfo[]): { install: string[]; connect: string[] } {
  const installed = (n: string): AddonInfo | undefined => addons.find((a) => a.name === n);
  return {
    install: names.filter((n) => !installed(n)),
    connect: names.filter((n) => {
      const tool = installed(n);
      return tool !== undefined && hasSlots(tool);
    }),
  };
}

/** The tool a definition names that is not installed, in words. */
export function toolToInstall(name: string): string {
  return `the ${name} tool, from Library → Tools`;
}

/** What those tools ask of you, in words. */
export function toolNeeds(names: string[], addons: AddonInfo[]): string[] {
  const { install, connect } = toolsAsked(names, addons);
  return [...install.map(toolToInstall), ...connect.map((n) => `a connection to ${n}`)];
}

/** What you choose for one agent when setting it up. */
export type Choice = {
  model: ModelAccess;
  bindings: Record<string, string>; // addon with settings → the configuration given ("": none yet)
  knowledge: Record<string, string>; // the name it reads → the folder given ("": none yet)
};

/** Its first choices: a configuration of each addon with settings when you have one, the
 *  knowledge folder of the same name when you have it; its model is always yours to choose. */
export function firstChoice(d: AgentDefinition, bindings: BindingInfo[], addons: AddonInfo[], folders: string[]): Choice {
  const valid = bindings.filter((b) => !b.error);
  const { connect } = toolsAsked(d.addons ?? [], addons);
  return {
    model: noAccess(),
    bindings: Object.fromEntries(connect.map((a) => [a, valid.find((b) => b.addon === a)?.name ?? ""])),
    knowledge: Object.fromEntries((d.knowledge ?? []).map((k) => [k, folders.includes(k) ? k : ""])),
  };
}

/** What is still to do before it can be set up, in words (none: ready): its tools not
 *  installed (`addons`: those that are; `coming`: those installed with it, G.5), then what is
 *  left to choose. */
export function missing(d: AgentDefinition, c: Choice, addons: AddonInfo[], coming: string[] = []): string[] {
  return [
    ...toolsAsked(d.addons ?? [], addons).install.filter((n) => !coming.includes(n)).map(toolToInstall),
    ...(chosen(c.model, d.modelAlone ?? false) ? [] : [d.modelAlone ? "a provider" : "its model"]),
    ...Object.entries(c.bindings).flatMap(([addon, b]) => (b ? [] : [`a connection to ${addon}`])),
    ...Object.entries(c.knowledge).flatMap(([name, k]) => (k ? [] : [`a notes folder for ${name}`])),
  ];
}

/** An agent's settings: its definition's (an agents file's agent, a need's), with what you
 *  chose. */
export function chosenSpec(d: AgentDefinition, c: Choice): AgentSpec {
  return {
    ...definitionSpec(d),
    model: { ...c.model },
    addons: addonUses(d.addons ?? [], c.bindings),
    knowledge: Object.values(c.knowledge).filter(Boolean),
  };
}

/** The addons an agent uses (G.3): each by its name, with the configuration chosen for those
 *  with settings. */
export function addonUses(names: string[], bindings: Record<string, string>): AddonUse[] {
  return names.map((addon) => (bindings[addon] ? { addon, binding: bindings[addon] } : { addon }));
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
  if (d.modelAlone) return [`nothing outside its call${d.knowledge?.length ? `; its notes are sent to its provider` : ""}`];
  const hosts = d.allow ?? [];
  return [
    folder ? `read and write ${folder}` : "a new folder each session",
    d.network === "none"
      ? "no network"
      : d.network === "open"
        ? "reach any host"
        : `reach its model${d.addons?.length ? ", its tools' hosts" : ""}${hosts.length ? `, ${hosts.join(", ")}` : ""}${d.egress === "log-only" ? " (every host, logged)" : ""}`,
    d.permissions === "bypass" ? "never asks before acting" : "asks before it acts",
    ...(d.confinement === "nested" ? ["run containers (a weaker sandbox)"] : d.confinement === "privileged" ? ["run privileged (about as safe as no sandbox)"] : []),
    ...(d.display ? ["use your screen and clipboard"] : []),
  ];
}

/** Whether a line of what it may do weakens its sandbox: said in amber, the others not. */
export function weakens(may: string): boolean {
  return /any host|never asks|containers|privileged|screen/.test(may);
}

/** Whether a tool a source offers can be installed with the agents needing it (G.5): one with
 *  settings or secrets is used through a connection, made in Library → Tools first. */
export function comesAlong(tool: Pick<AddonPreview, "settings" | "secretSlots">): boolean {
  return !tool.settings?.length && !tool.secretSlots?.length;
}

