// What an app needs and may reach (H.2, H.9, H.11), in sentences for its Manage dialog.
import { api } from "./api";
import type { Agent, App, AppFileNeed, Automation, HandlerNeed, AppManifestNeeds, AppManifestSuggestedAutomation, UseRef } from "./contracts.gen";

/** What an installed version may reach, with what was given its needs (`app`'s folders and
 *  agents; `label`: an agent's name). */
export function reaches(needs: AppManifestNeeds, app: App, label: (id: string) => string): string[] {
  const out: string[] = [];
  if (needs.egress?.length) out.push(`Reaches ${needs.egress.join(", ")}.`);
  else out.push("Reaches no host: no network.");
  for (const [name, f] of Object.entries(needs.files ?? {})) {
    const path = app.files?.find((g) => g.name === name)?.path ?? `the folder you give for ${name}`;
    out.push(`${f.mode === "rw" ? "Reads and writes" : "Reads"} ${path}.`);
  }
  if (needs.secrets?.length) out.push(`Gets the secrets ${needs.secrets.join(", ")}.`);
  if (needs.notify) out.push("Sends you notifications (your inbox, desktop and phones).");
  for (const name of Object.keys(needs.agents ?? {})) {
    const given = app.agents?.find((a) => a.name === name)?.agentId;
    out.push(`Runs ${given ? `your agent ${label(given)}` : `the agent you give for ${name}`} when you use it, and reads its results.`);
  }
  return out;
}

/** What it needs that was not given (or no longer fits): it cannot be deployed or start. */
export function missing(app: App): string[] {
  return [
    ...(app.files ?? []).filter((f) => !f.path).map((f) => `the folder ${f.name}`),
    ...(app.agents ?? []).filter((a) => !a.agentId || a.problem).map((a) => `the agent ${a.name}`),
    ...(app.secrets ?? []).filter((s) => !s.set).map((s) => `the secret ${s.name}`),
  ];
}

/** What Handler or an app uses an agent for, one tag each (D.18, H.2): "Skill reviewer" (a
 *  need of Handler's it was given for), "Planner" (an app it was given to). */
export function usedFor(agent: Agent, needs: HandlerNeed[], apps: App[]): { label: string; app: boolean }[] {
  const handler = needs.filter((b) => b.agentId === agent.id).map((b) => ({ label: b.definition.agentName, app: false }));
  const given = apps.filter((app) => app.agents?.some((a) => a.agentId === agent.id)).map((app) => ({ label: app.name, app: true }));
  return [...handler, ...given];
}

/** What runs an agent and stops when it is deleted (D.22): Handler (a need it was given for),
 *  apps it was given to, automations that run it or run when its sessions stop. */
export async function dependents(agentId: string): Promise<UseRef[]> {
  const { usedBy } = await api.uses("agent", agentId);
  return (usedBy ?? []).filter((r) => r.kind === "handler" || r.kind === "app" || r.kind === "automation");
}

/** What deleting an agent stops, in a sentence ("" when nothing uses it). */
export function stopsWhenDeleted(refs: UseRef[]): string {
  const all = [...new Set(refs.map((r) => (r.kind === "handler" ? `Handler (${r.how})` : `the ${r.kind} ${r.label}`)))];
  if (!all.length) return "";
  const list = all.length === 1 ? all[0] : `${all.slice(0, -1).join(", ")} and ${all.at(-1)}`;
  return ` It is used by ${list}: ${all.length === 1 ? "it stops" : "they stop"} until you give ${all.length === 1 ? "it" : "them"} another agent.`;
}

/** `stopsWhenDeleted` for that agent, read now. */
export async function deletionStops(agent: Agent): Promise<string> {
  return stopsWhenDeleted(await dependents(agent.id).catch(() => []));
}

/** An agent's name in a list of choices: its project's too. */
export function agentChoice(agent: Agent, projects: Map<string, string>): string {
  const name = agent.name ?? agent.scope ?? agent.id;
  const project = agent.projectId ? projects.get(agent.projectId) : undefined;
  return project ? `${name} (project ${project})` : name;
}

/** The folder an app keeps its data in (H.2): the one its agents work in, else its only
 *  read-write one; none: an app with no folder of yours (it is outside projects). */
export function dataNeed(app: Pick<App, "files" | "agents">): AppFileNeed | undefined {
  const files = app.files ?? [];
  const worked = files.find((f) => (app.agents ?? []).some((a) => a.worksIn === f.name));
  const rw = files.filter((f) => f.mode === "rw");
  return worked ?? (rw.length === 1 ? rw[0] : undefined);
}

/** The automation one of an app's suggestions makes: its name and definition (its agent's names
 *  are written by handlerd from the agent given, I.1). */
export function suggested(app: Pick<App, "name">, s: AppManifestSuggestedAutomation): { name: string; definition: Automation } {
  const slug = s.description.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  const name = `${app.name}-${slug}`.slice(0, 64).replace(/-+$/, "");
  return { name, definition: { apiVersion: "handler.automation/v1", description: s.description, when: s.when, app: app.name, run: { agent: s.run.agent, input: s.run.input } } };
}
