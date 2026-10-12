// Projects: what you work on. A project is a code folder, its caches setting and
// the skills it gives to all its agents, and its agents. An agent is one
// goal: its models (harnesses on accounts or providers, one per session), set up for the
// project, with settings all its own: an agent with a projectId, so sessions open on it as on
// an ad-hoc one.
//
// The one place that knows how projects and agents are described, saved and ordered. Views go
// through this module, ProjectEditor.svelte and AgentEditor.svelte.
import { modelsOf, noAccess, requested, type ModelAccess } from "./access";
import { api } from "./api";
import type { AdHocAgentRequest, Agent, AgentInterface, AgentRequest, Project, ProjectSettingsRequest } from "./contracts.gen";
import { folderName } from "./agents";

/** How an agent is contained: its own, never inherited (D.8). */
export type Sandbox = Required<Pick<AgentRequest, "network" | "egress" | "confinement" | "permissions">>;

/** Presets: how a new project's first agent is contained, copied into it, never linked to it.
 *  Guarded (filtered network, enforced; auto-approve) is also what any new agent starts with (the
 *  daemon's defaults). Log only is not a preset: the network panel turns it on to learn hosts. */
export const PRESETS: { id: string; label: string; hint: string; sandbox: Sandbox }[] = [
  {
    id: "locked",
    label: "Locked down",
    hint: "No network, asks before acting",
    sandbox: { network: "none", egress: "enforce", confinement: "strict", permissions: "ask" },
  },
  {
    id: "guarded",
    label: "Guarded",
    hint: "Only the hosts it is allowed (its model's and addons' already are), never asks",
    sandbox: { network: "filtered", egress: "enforce", confinement: "strict", permissions: "bypass" },
  },
  {
    id: "open",
    label: "Open",
    hint: "Any host, never asks",
    sandbox: { network: "open", egress: "enforce", confinement: "strict", permissions: "bypass" },
  },
];

/** The preset an agent's sandbox settings are exactly, if any; otherwise its settings are its own. */
export function presetOf(s: { network?: string | null; egress?: string | null; confinement?: string | null; permissions?: string | null }):
  | (typeof PRESETS)[number]
  | undefined {
  return PRESETS.find(
    (p) =>
      s.network === p.sandbox.network &&
      (s.egress ?? "enforce") === p.sandbox.egress &&
      (s.confinement ?? "strict") === p.sandbox.confinement &&
      s.permissions === p.sandbox.permissions,
  );
}

/** What an agent is set to: the body of create and of a full update. */
export type AgentSpec = Sandbox & {
  models: ModelAccess[]; // what it runs as, the first by default (D.1)
  name: string;
  description: string;
  instructions: string;
  display: boolean;
  allow: string[];
  bindings: string[];
  knowledge: string[];
  default: boolean;
  remoteStart: boolean; // your paired devices may start sessions with it
  skills: string[]; // the skills it picks, not those its project gives (D.17)
  interface: string; // D.18, as JSON text: what its runs take and give back; "": none
};

export function emptyAgent(models: ModelAccess[] = [noAccess()]): AgentSpec {
  return {
    models: models.map((m) => ({ ...m })),
    name: "",
    description: "",
    instructions: "",
    ...PRESETS[1]!.sandbox,
    display: false,
    allow: [],
    bindings: [],
    knowledge: [],
    default: false,
    remoteStart: false,
    skills: [],
    interface: "",
  };
}

/** The settings of an existing agent, to edit them. */
export function agentSpec(agent: Agent, project: Pick<Project, "defaultAgent">): AgentSpec {
  return {
    models: modelsOf(agent),
    name: agent.name ?? "",
    description: agent.description ?? "",
    instructions: agent.instructions ?? "",
    network: agent.network,
    egress: agent.egress ?? "enforce",
    confinement: agent.confinement,
    permissions: agent.permissions,
    display: agent.display ?? false,
    allow: [...(agent.allow ?? [])],
    bindings: [...(agent.bindings ?? [])],
    knowledge: [...(agent.knowledge ?? [])],
    default: project.defaultAgent === agent.id,
    remoteStart: agent.remoteStart ?? false,
    skills: [...(agent.skills ?? [])],
    interface: agent.interface ? JSON.stringify(agent.interface, null, 2) : "",
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

export function agentBody(spec: AgentSpec, confirmRisks = false): AgentRequest {
  const text = (value: string) => value.trim() || null;
  const { models, ...rest } = spec;
  return {
    ...rest,
    models: models.map(requested) as AgentRequest["models"],
    name: spec.name.trim(), // an agent of a project's goal: required (D.8)
    description: text(spec.description),
    instructions: text(spec.instructions),
    interface: parseInterface(spec.interface),
    confirmRisks,
  };
}

/** An ad-hoc agent's body (D.2): no project, so no default or phone start; `folder` null:
 *  folderless, a folder per session; `origin`: the built-in agent it is (D.18). */
export function adHocBody(spec: AgentSpec, folder: string | null, origin: string | null = null, confirmRisks = false): AdHocAgentRequest {
  const { default: _default, remoteStart: _remote, ...body } = agentBody(spec, confirmRisks);
  return { ...body, name: body.name || null, scope: folder, origin };
}

/** What a project is set to: the body of a full update. */
export type ProjectSpec = {
  name: string;
  description: string;
  folder: string;
  defaultAgent: string | null;
  caches: NonNullable<ProjectSettingsRequest["caches"]>; // the toolbox's caches for its agents
  context: string | null; // its context (D.19): the accounts and providers it runs
};

export function emptyProject(folder = ""): ProjectSpec {
  return { name: "", description: "", folder, defaultAgent: null, caches: "project", context: null };
}

/** A copy of an agent's settings for a new agent of the same project ("Duplicate"): nothing stays
 *  linked to the original. */
export function duplicateAgent(agent: Agent, taken: string[]): AgentSpec {
  const spec = agentSpec(agent, { defaultAgent: null });
  const base = `${agentLabel(agent)}-copy`;
  let name = base;
  for (let i = 2; taken.some((t) => t.toLowerCase() === name.toLowerCase()); i++) name = `${base}-${i}`;
  return { ...spec, models: spec.models.map((m) => ({ ...m })), name };
}

export function projectSpec(p: Project): ProjectSpec {
  return {
    name: p.name,
    description: p.description ?? "",
    folder: p.folder,
    defaultAgent: p.defaultAgent ?? null,
    caches: p.caches ?? "project",
    context: p.context ?? null,
  };
}

export function projectBody(spec: ProjectSpec): ProjectSettingsRequest {
  return { ...spec, name: spec.name.trim() || null, description: spec.description.trim() || null };
}

/** The hosts an agent's sandboxes allow on top of the required ones: its own (D.8). */
export async function saveHosts(agent: Agent, allow: string[]): Promise<void> {
  const project = await api.project(agent.projectId ?? "");
  await api.updateAgent(project.id, agent.id, agentBody({ ...agentSpec(agent, project), allow }));
  await projects.refresh();
}

/** How an agent is named in lists: its name (its first model's account or provider by default). */
export function agentLabel(agent: Pick<Agent, "name" | "models">): string {
  const first = agent.models[0];
  return agent.name || first?.account || first?.provider || first?.harness || "agent";
}

/** Another agent of the project set up like `spec` but for its models: the place to add a model
 *  to, rather than a new agent (one goal, one agent). */
export function sameSetup(spec: AgentSpec, others: Agent[], project: Pick<Project, "defaultAgent">): Agent | undefined {
  const setup = (s: AgentSpec) => {
    const { models: _m, name: _n, default: _d, remoteStart: _r, ...rest } = s;
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

/** Search: every word of `query` in its name, folder, description or agents. */
export function matches(p: Project, query: string): boolean {
  const agents = p.agents.flatMap((a) => [a.name, ...a.models.flatMap((m) => [m.account, m.provider, m.harness])]);
  const text = [p.name, p.folder, p.description, ...agents].join(" ").toLowerCase();
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
      this.list = await api.projects();
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
    return found ? `${found.project.name} · ${agentLabel(found.agent)}` : agent.name || (agent.scope ? folderName(agent.scope) : agentLabel(agent));
  }
}

export const projects = new ProjectStore();
