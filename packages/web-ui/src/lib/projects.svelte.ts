// Projects: what you work on. A project is a code folder, its caches setting and
// the skills it gives to all its agents, and its agents. An agent is one
// goal: its models (harnesses on accounts or providers, one per session), set up for the
// project, with settings all its own: an agent with a projectId, so sessions open on it as on
// an ad-hoc one.
//
// The one place that knows how projects and agents are described, saved and ordered. Views go
// through this module, ProjectEditor.svelte and AgentEditor.svelte.
import { accessOf, noAccess, requested, type ModelAccess } from "./access";
import { api } from "./api";
import type { AccountInfo, AddonUse, Agent, AgentInterface, AgentOrigin, AgentRequest, ModelAccess as RequestedModel, Project, ProjectSettingsRequest, ProviderInfo } from "./contracts.gen";
import { folderName } from "./agents";
import { withEntry, withList, type OwnHosts } from "./hosts";
import { NEW_AGENT, type Sandbox } from "./safety";
import { allows } from "./areas.svelte";
import { interfaceOf, newJob, switchedTo } from "./interface";
import { freeName } from "./text";

/** What an agent is set to: the body of create and of a full update. */
export type AgentSpec = Sandbox & {
  model: ModelAccess; // what it runs as (D.1); a session may run with another (D.19)
  name: string;
  description: string;
  instructions: string;
  display: boolean;
  allow: string[];
  blocked: string[]; // the hosts the person keeps blocked, never also allowed (A.3)
  addons: AddonUse[]; // its own, not those its project gives (G.3)
  knowledge: string[];
  default: boolean;
  remoteStart: boolean; // your paired devices may start sessions with it
  skills: string[]; // the skills it picks, not those its project gives (D.17)
  interface: string; // D.18, as JSON text: what its runs take and give back; "": none
  modelAlone: boolean; // no program: the model alone, on a provider, with no sandbox (D.18)
  origin: AgentOrigin | null; // the definition it was set up from, kept for good (D.18, H.2)
};

/** Where an agent lives, given when it is made and never changed (D.1): its project, its app
 *  (one of its parts, or Chat), or none: then its folder (null: a folder per session). */
export type Home = Pick<AgentRequest, "projectId" | "app" | "chat" | "scope">;

/** An agent's home, to save it again. */
export function homeOf(agent: Agent): Home {
  return agent.projectId ? { projectId: agent.projectId } : { app: agent.app ?? null, chat: agent.chat ?? false, scope: agent.scope ?? null };
}

export function emptyAgent(model: ModelAccess = noAccess()): AgentSpec {
  return {
    model: { ...model },
    name: "",
    description: "",
    instructions: "",
    ...NEW_AGENT,
    display: false,
    allow: [],
    blocked: [],
    addons: [],
    knowledge: [],
    default: false,
    remoteStart: false,
    skills: [],
    interface: "",
    modelAlone: false,
    origin: null,
  };
}

/** Who works, switched (D.18). The model alone has no sandbox: its settings go back to the
 *  defaults of new agents (only the sites it needs, which the daemon expects of it), with no addons, skills or
 *  display, and its model kept when on a provider, without a program; an agent program starts from
 *  those defaults too, its model to choose again. */
export function withModelAlone(spec: AgentSpec, alone: boolean): AgentSpec {
  const kept = spec.model.provider ? { ...spec.model, harness: null } : noAccess();
  return {
    ...spec,
    ...NEW_AGENT,
    modelAlone: alone,
    allow: [],
    blocked: [],
    addons: alone ? [] : spec.addons,
    skills: alone ? [] : spec.skills,
    display: false,
    model: alone ? kept : noAccess(),
  };
}

/** The settings of an existing agent, to edit them. */
export function agentSpec(agent: Agent, project: Pick<Project, "defaultAgent">): AgentSpec {
  return {
    model: accessOf(agent.model),
    name: agent.name ?? "",
    description: agent.description ?? "",
    instructions: agent.instructions ?? "",
    network: agent.network,
    egress: agent.egress ?? "enforce",
    confinement: agent.confinement,
    permissions: agent.permissions,
    display: agent.display ?? false,
    allow: [...(agent.allow ?? [])],
    blocked: [...(agent.blocked ?? [])],
    addons: (agent.addons ?? []).map((u) => ({ ...u })),
    knowledge: [...(agent.knowledge ?? [])],
    default: project.defaultAgent === agent.id,
    remoteStart: agent.remoteStart ?? false,
    skills: [...(agent.skills ?? [])],
    interface: agent.interface ? JSON.stringify(agent.interface, null, 2) : "",
    modelAlone: agent.modelAlone ?? false,
    origin: agent.origin ?? null,
  };
}

/** The interface typed as JSON (D.18); throws when it is not JSON. */
export function parseInterface(text: string): AgentInterface | null {
  if (!text.trim()) return null;
  try {
    return JSON.parse(text) as AgentInterface;
  } catch (e) {
    throw new Error(`Interface: not JSON (${(e as Error).message})`);
  }
}

/** The body that creates or replaces an agent in its home (D.2). Of a project, its name is its
 *  goal (required, D.8), and it may be its default or be started from a phone; elsewhere neither. */
export function agentBody(spec: AgentSpec, home: Home, confirmRisks = false, toolboxAdds: string[] = []): AgentRequest {
  const text = (value: string) => value.trim() || null;
  const { model, default: isDefault, remoteStart, ...rest } = spec;
  const ofProject = !!home.projectId;
  return {
    ...rest,
    ...home,
    model: requested(model),
    name: text(spec.name),
    description: text(spec.description),
    instructions: text(spec.instructions),
    interface: parseInterface(spec.interface),
    default: ofProject && isDefault,
    remoteStart: ofProject && remoteStart,
    confirmRisks,
    toolboxAdds,
  };
}

/** What a project is set to: the body of a full update. */
export type ProjectSpec = {
  name: string;
  description: string;
  folder: string;
  defaultAgent: string | null;
  caches: NonNullable<ProjectSettingsRequest["caches"]>; // the toolbox's caches for its agents
  area: string | null; // its area (D.19): the accounts and providers it runs
  skills: string[]; // the skills it gives to all its agents (D.17)
  addons: AddonUse[]; // the addons it gives to all its agents (G.3)
};

export function emptyProject(folder = ""): ProjectSpec {
  return { name: "", description: "", folder, defaultAgent: null, caches: "project", area: null, skills: [], addons: [] };
}

/** A copy of an agent's settings for a new agent of the same project ("Duplicate"): nothing stays
 *  linked to the original. */
export function duplicateAgent(agent: Agent, taken: string[]): AgentSpec {
  const spec = agentSpec(agent, { defaultAgent: null });
  const name = freeName(`${agentLabel(agent)}-copy`, taken);
  return { ...spec, model: { ...spec.model }, name, origin: null }; // a copy is set up from nothing
}

/** A job made from an agent (Talk or Brief) for an automation to run: its copy, named
 *  `<name>-job`, with a job's form and result (its brief's form kept) and never asking (no one is
 *  there to answer: Auto-approve, confirmed on save as any widening). */
export function jobFrom(agent: Agent, taken: string[]): AgentSpec {
  const spec = duplicateAgent(agent, taken);
  const name = freeName(`${agentLabel(agent)}-job`, taken);
  const iface = spec.interface ? switchedTo("job", spec.interface) : JSON.stringify(interfaceOf(newJob()), null, 2);
  return { ...spec, name, interface: iface, permissions: "bypass" };
}

export function projectSpec(p: Project): ProjectSpec {
  return {
    name: p.name,
    description: p.description ?? "",
    folder: p.folder,
    defaultAgent: p.defaultAgent ?? null,
    caches: p.caches ?? "project",
    area: p.area ?? null,
    skills: p.skills ?? [],
    addons: (p.addons ?? []).map((u) => ({ ...u })),
  };
}

export function projectBody(spec: ProjectSpec): ProjectSettingsRequest {
  return { ...spec, name: spec.name.trim() || null, description: spec.description.trim() || null };
}

/** An agent's own hosts (D.8): those its sandboxes allow on top of the required ones, and those
 *  the person keeps blocked (A.3), applied to its running sandboxes at once. */
export async function saveHosts(agent: Agent, hosts: OwnHosts): Promise<Agent> {
  const project = agent.projectId ? await api.project(agent.projectId) : { defaultAgent: null };
  const saved = await api.updateAgent(agent.id, agentBody({ ...agentSpec(agent, project), ...hosts }, homeOf(agent)));
  if (agent.projectId) await projects.refresh();
  return saved;
}

/** Hosts refused to a run of the agent (F.9) put in one of its lists, off the other: *Keep
 *  blocked* on a plan's step or an automation's run. */
export async function decideHosts(agentId: string, hosts: string[], list: keyof OwnHosts): Promise<Agent> {
  const agent = await api.agent(agentId);
  const own = { allow: agent.allow ?? [], blocked: agent.blocked ?? [] };
  return saveHosts(agent, withList(own, list, hosts.reduce((l, h) => withEntry(l, h), own[list])));
}

/** Its permissions switched to Auto-approve (bypass), the rest of its settings as they are: the
 *  review of a plan's fix (D.27). It widens what the agent may do: the caller confirmed it. */
export async function switchToBypass(agent: Agent): Promise<Agent> {
  const project = agent.projectId ? await api.project(agent.projectId) : { defaultAgent: null };
  const spec: AgentSpec = { ...agentSpec(agent, project), permissions: "bypass" };
  const saved = await api.updateAgent(agent.id, agentBody(spec, homeOf(agent), true));
  if (agent.projectId) await projects.refresh();
  return saved;
}

/** Make a model picked for one session the agent's own (D.1): "Make Opus Dev's default". */
export async function makeModelDefault(agent: Agent, model: RequestedModel): Promise<Agent> {
  const project = agent.projectId ? await api.project(agent.projectId) : { defaultAgent: null };
  const saved = await api.updateAgent(agent.id, agentBody({ ...agentSpec(agent, project), model: accessOf(model) }, homeOf(agent)));
  if (agent.projectId) await projects.refresh();
  return saved;
}

/** How an agent is named in lists: its name; else its folder's (one made by the command line
 *  outside projects), else its model's account or provider. */
export function agentLabel(agent: Pick<Agent, "name" | "model"> & { scope?: string | null }): string {
  const m = agent.model;
  return agent.name || (agent.scope ? folderName(agent.scope) : null) || m.account || m.provider || m.harness || "agent";
}

/** Another agent of the project set up like `spec` but for its model: the one to start with
 *  that model instead, rather than a new agent (one goal, one agent). */
export function sameSetup(spec: AgentSpec, others: Agent[], project: Pick<Project, "defaultAgent">): Agent | undefined {
  const setup = (s: AgentSpec) => {
    const { model: _m, name: _n, default: _d, remoteStart: _r, ...rest } = s;
    return JSON.stringify({ ...rest, description: rest.description.trim(), instructions: rest.instructions.trim() });
  };
  const mine = setup(spec);
  return others.find((a) => setup(agentSpec(a, project)) === mine);
}

/** Most recently used first, then newest. */
export function byRecentUse(list: Project[]): Project[] {
  const key = (p: Project) => p.lastUsedAt ?? p.createdAt;
  return [...list].sort((a, b) => key(b).localeCompare(key(a)));
}

/** What a project's suggested first agent runs on ("An agent to work with you here"): what the
 *  default agent of the project used last runs on, when ready and made for `area`; else the only
 *  account or provider ready for it. None when two or more could be: the person chooses, in the
 *  agent form (never the wrong account by default). */
export function suggestedAccess(
  all: Project[],
  accounts: AccountInfo[],
  providers: ProviderInfo[],
  area: string | null | undefined,
): ModelAccess | null {
  const account = (name?: string | null) => accounts.find((a) => a.name === name && a.status === "ready" && allows(area, a.areas));
  const provider = (name?: string | null) => providers.find((p) => p.name === name && p.status === "ready" && allows(area, p.areas));
  for (const p of byRecentUse(all)) {
    const used = p.agents.find((a) => a.id === p.defaultAgent);
    if (!used || used.modelAlone) continue;
    if (account(used.model.account) || (provider(used.model.provider) && used.model.harness)) return accessOf(used.model);
  }
  const ready = [
    ...accounts.filter((a) => a.harness && account(a.name)).map((a) => ({ ...noAccess(), harness: a.harness ?? null, account: a.name })),
    ...providers.filter((p) => p.harnesses?.length && provider(p.name)).map((p) => ({ ...noAccess(), harness: p.harnesses![0]!, provider: p.name })),
  ];
  return ready.length === 1 ? ready[0]! : null;
}

/** By name: a list where each project keeps its place (the Projects page, the menu's pinned). */
export function byName(list: Project[]): Project[] {
  return [...list].sort((a, b) => a.name.localeCompare(b.name));
}

/** A folder as a row says it: `~` for the home (/home/<you>, /Users/<you>), and past four parts
 *  the middle cut (`~/Documents/…/thesis`); the whole path is in its tooltip. */
export function shortFolder(folder: string): string {
  const path = folder.replace(/\/+$/, "").replace(/^\/(home|Users)\/[^/]+(?=\/|$)/, "~");
  const parts = path.split("/");
  return parts.length > 4 ? [parts[0], parts[1], "…", parts.at(-1)].join("/") : path;
}

/** Whether the Projects filter keeps a project: each word in what its row shows (its name,
 *  description, folder), so a match is never hidden. */
export function matches(p: Pick<Project, "name" | "folder" | "description">, query: string): boolean {
  const text = [p.name, p.folder, p.description].join(" ").toLowerCase();
  return query
    .toLowerCase()
    .split(/\s+/)
    .every((word) => text.includes(word));
}

/** The projects a skill or an addon configuration is used in: those that give it to all their
 *  agents (`given`, ids) and those of the agents that picked it (`usedBy`: "agents/<project>/<agent>"). */
export function usedIn(list: Project[], usedBy: string[] = [], given: string[] = []): Project[] {
  return list.filter((p) => given.includes(p.id) || usedBy.some((u) => u.startsWith(`agents/${p.name}/`)));
}

/** A picker's choices: those used in project `projectId` first, then the others, each in order;
 *  with, for each, the other projects it is used in ("used in shop, blog"). */
export function byUse<T extends { usedBy?: string[]; projects?: string[] }>(
  list: Project[],
  choices: T[],
  projectId?: string,
): { choice: T; note: string }[] {
  const rows = choices.map((choice) => {
    const where = usedIn(list, choice.usedBy, choice.projects);
    const others = where.filter((p) => p.id !== projectId).map((p) => p.name);
    return { choice, here: where.some((p) => p.id === projectId), note: others.length ? `used in ${others.join(", ")}` : "" };
  });
  return [...rows.filter((r) => r.here), ...rows.filter((r) => !r.here)].map(({ choice, note }) => ({ choice, note }));
}

class ProjectStore {
  list = $state<Project[]>([]);
  loaded = $state(false);
  error = $state<string | null>(null);
  async refresh(): Promise<void> {
    try {
      const list = await api.projects();
      this.list = list;
      this.error = null;
    } catch (e) {
      this.error = (e as Error).message;
    } finally {
      this.loaded = true;
    }
  }

  get(id: string | null | undefined): Project | undefined {
    return id ? this.list.find((p) => p.id === id) : undefined;
  }

  /** An agent's project, and the agent as listed in it, when it is an agent of a project. */
  of(agent: Pick<Agent, "id" | "projectId">): { project: Project; agent: Agent } | undefined {
    const project = this.get(agent.projectId);
    const listed = project?.agents.find((a) => a.id === agent.id);
    return project && listed ? { project, agent: listed } : undefined;
  }

  /** "shop · review" for a session's agent; its name or folder for an ad-hoc one. */
  label(agent: Agent): string {
    const found = this.of(agent);
    return found ? `${found.project.name} · ${agentLabel(found.agent)}` : agentLabel(agent);
  }
}

export const projects = new ProjectStore();
