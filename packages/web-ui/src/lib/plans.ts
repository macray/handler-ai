// Plans (D.27), in words: how far one went, from where it may run again; on review, who runs it
// and the fix offered. Drafts: New plan (a draft for a project, the plan builder's session on it),
// continued, thrown away.
import { accessOf, noAccess, type ModelAccess } from "./access";
import { api, ApiError } from "./api";
import type { PlanDraft, PlanRead, PlanRunner, PlanView, Project } from "./contracts.gen";
import { agentLabel, emptyAgent, type AgentSpec } from "./projects.svelte";
import { navigate } from "./router.svelte";
import { sessions } from "./sessions.svelte";
import { freeName } from "./text";

/** "1 of 3 steps done". */
export function stepsDone(p: PlanView): string {
  const done = p.steps.filter((s) => s.state === "done").length;
  return `${done} of ${p.steps.length} step${p.steps.length === 1 ? "" : "s"} done`;
}

/** The steps it may run again from, once stopped or done: up to its first step not done. */
export function restartable(p: PlanView): number[] {
  if (p.state === "running") return [];
  const first = p.steps.find((s) => s.state !== "done")?.n ?? p.steps.length;
  return p.steps.filter((s) => s.n <= first).map((s) => s.n);
}

/** A step's time limit in words: "3 hours", "90 minutes". */
export function limit(seconds: number): string {
  if (seconds % 3600 === 0) return `${seconds / 3600} hour${seconds === 3600 ? "" : "s"}`;
  return `${Math.round(seconds / 60)} minutes`;
}

/** The agent that runs a plan read, as offered on review: the one chosen, else the one its
 *  `Agent:` line names; none when neither is one of the folder's runners. */
export function runnerOf(read: PlanRead): PlanRunner | undefined {
  return read.runners?.find((r) => r.id === read.agentId);
}

/** What the review page offers to fix who runs it: "switch" its runner to Auto-approve, "create"
 *  a plan runner when no agent of the project may run steps; none otherwise. */
export function runnerFix(read: PlanRead): "switch" | "create" | null {
  if (runnerOf(read)?.bypass === false) return "switch";
  if (!read.runners?.length && read.projectId) return "create";
  return null;
}

/** A new agent of the project to run plans' steps (D.27): only the sites it needs, never asking, in the
 *  project's folder, on what the project's default agent runs as (a model of its area), else on
 *  any agent program of the project's; saved by you, in the new-agent form. */
export function planRunner(project: Project): AgentSpec {
  const programs = project.agents.filter((a) => !a.modelAlone && !a.app);
  const like = programs.find((a) => a.id === project.defaultAgent) ?? programs[0];
  const name = freeName("plan-runner", project.agents.map(agentLabel));
  return {
    ...emptyAgent(like ? accessOf(like.model) : noAccess()),
    name,
    description: "Runs the steps of the plans you approve, one after another.",
  };
}

/** New plan: a draft for the project, and a session of the plan builder on it (D.27), opened.
 *  False, nothing done, when no builder is set up yet: the caller shows its set-up card.
 *  `model`: one of the project's area, for this session, when the builder's own is not. Refused
 *  (its model, its rights), the draft goes and the error is thrown: "not for this project's
 *  area" lets the caller offer another model. */
export async function startPlan(projectId: string, model?: ModelAccess): Promise<boolean> {
  const builder = (await api.handlerNeeds()).find((n) => n.name === "plan-builder");
  if (!builder?.agentId) return false;
  const agent = await api.agent(builder.agentId);
  const draft = await api.createPlanDraft({ projectId });
  try {
    navigate({ view: "session", key: sessions.open(await api.buildPlan(agent.id, draft.id, model), agent).key });
  } catch (e) {
    await api.deletePlanDraft(draft.id);
    throw e;
  }
  return true;
}

/** The plan builder's model refused for the project's area: another one is to be chosen. */
export function areaRefused(e: unknown): boolean {
  return e instanceof ApiError && e.title === "not for this project's area";
}

/** Open a draft's builder session again. */
export async function continueBuilder(sessionId: string): Promise<void> {
  const session = await api.session(sessionId);
  navigate({ view: "session", key: sessions.open(session, await api.agent(session.agentId)).key });
}

/** Throw a draft away, once confirmed: its text goes; its builder session stays. */
export async function throwAwayDraft(d: PlanDraft): Promise<boolean> {
  if (!confirm(`Throw away the draft${d.title ? ` "${d.title}"` : ""}? Its text goes; plans approved from it stay.`)) return false;
  await api.deletePlanDraft(d.id);
  return true;
}
