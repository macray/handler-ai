// What an app needs and may reach (H.2, H.9, H.11), in sentences for its Manage dialog.
import { api } from "./api";
import type { Todo } from "./blocked";
import { homePath, slug } from "./text";
import type { Agent, App, AppFileNeed, AppJob, AppRun, Automation, AutomationView, DirectoryEntry, HandlerNeed, AppManifestNeeds, AppManifestSuggestedAutomation, InboxMessage, UseRef, WhoWorks } from "./contracts.gen";
import type { Limits } from "./whoworks";

/** What the person sees an app called (H.1): its manifest's title ("Planner"), else its name (the
 *  app's id, "planner"). */
export function appTitle(app: { name: string; title?: string | null }): string {
  return app.title || app.name;
}

/** Names to titles, for what knows an app by its name alone (a pin, a message). */
export function appTitles(apps: { name: string; title?: string | null }[]): Record<string, string> {
  return Object.fromEntries(apps.map((a) => [a.name, appTitle(a)]));
}

/** Each app's news (E6, its badge on Apps): its inbox messages not read yet, those that open it
 *  (its own notifications and nudges, its automations' runs). By the app's name; none: absent. */
export function news(messages: InboxMessage[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const m of messages) if (m.app && !m.read) out[m.app] = (out[m.app] ?? 0) + 1;
  return out;
}

/** What an installed version may reach, with what was given its needs (`app`'s folders), and
 *  what each of its jobs reaches. */
export function reaches(needs: AppManifestNeeds, app: App): string[] {
  const out: string[] = [];
  if (needs.egress?.length) out.push(`Reaches ${needs.egress.join(", ")}.`);
  else out.push("Reaches no host: no network.");
  for (const [name, f] of Object.entries(needs.files ?? {})) {
    const path = app.files?.find((g) => g.name === name)?.path ?? `the folder you give for ${name}`;
    out.push(`${f.mode === "rw" ? "Reads and writes" : "Reads"} ${path}.`);
  }
  if (needs.secrets?.length) out.push(`Gets the secrets ${needs.secrets.join(", ")}.`);
  if (needs.notify) out.push("Sends you notifications (your inbox, desktop and phones).");
  for (const job of app.jobs ?? []) out.push(`Its job “${job.description}”: ${canDoWords(job, app).join("; ")}.`);
  return out;
}

/** A folder given to one of the app's needs, as a sentence names it: its path, else (or
 *  `byRole`, where its path is said once already) what the need is for ("Your notes"). */
function folderWords(app: Pick<App, "files">, need: string, byRole = false): string {
  const f = app.files?.find((x) => x.name === need);
  const role = (f?.description ?? need).replace(/\.$/, "");
  return byRole ? role : f?.path ? homePath(f.path) : `your folder “${role}”`;
}

/** What an installed app may touch, short, for its page (its Settings): each folder by what it
 *  is for (its path is said in What it uses), its hosts or no network, its secrets,
 *  notifications, then what each job reaches. */
export function touchWords(needs: AppManifestNeeds, app: App): string[] {
  const out = Object.entries(needs.files ?? {}).map(([name, f]) => `${folderWords(app, name, true)}: ${f.mode === "rw" ? "reads and writes" : "reads"}`);
  out.push(needs.egress?.length ? `Reaches ${needs.egress.join(", ")}` : "No network");
  if (needs.secrets?.length) out.push(`Gets the secrets ${needs.secrets.join(", ")}`);
  if (needs.notify) out.push("Sends you notifications (your inbox, desktop and phones)");
  for (const job of app.jobs ?? []) out.push(`Its job “${job.description}”: ${canDoWords(job, app, true).join(" · ")}`);
  return out;
}

/** What a job reaches (its Can do, H.1, rule app-job.can-do-is-the-app-s), in short sentences:
 *  each folder read or written (where it works), its schemas, its hosts or no network. */
export function canDoWords(job: Pick<AppJob, "canDo">, app: Pick<App, "files">, byRole = false): string[] {
  const c = job.canDo;
  const out = Object.entries(c.files ?? {}).map(
    ([need, access]) => `${access === "write" ? "reads and writes" : "reads"} ${folderWords(app, need, byRole)}${c.worksIn?.includes(need) ? ", working in it" : ""}`,
  );
  if (c.schemas?.length) out.push(`uses the notes formats ${c.schemas.join(", ")}`);
  out.push(c.egress?.length ? `reaches ${c.egress.join(", ")}` : "no network");
  return out;
}

/** A job that needs a program (a sandbox): it reaches folders, schemas or hosts (H.2: the model
 *  alone cannot run it). */
export function needsProgram(job: Pick<AppJob, "canDo">): boolean {
  const c = job.canDo;
  return !!(Object.keys(c.files ?? {}).length || c.schemas?.length || c.egress?.length);
}

/** The automations that run that job of the app (`run = { app, job }`, I.1), turned on. */
export function jobAutomations(app: string, job: string, automations: AutomationView[]): AutomationView[] {
  return automations.filter((x) => {
    const run = x.definition?.run;
    return x.enabled && !!run && typeof run === "object" && "job" in run && run.app === app && run.job === job;
  });
}

/** What who works for these jobs cannot be (H.2), each greyed with why in the Who works control:
 *  the model alone when one of them reaches folders, schemas or hosts; a subscription refusing
 *  runs nobody follows when an automation runs one of them (`unattended`). */
export function jobLimits(jobs: Pick<AppJob, "canDo" | "description">[], unattended: boolean): Limits {
  const reaching = jobs.find(needsProgram);
  return {
    alone: reaching ? `“${reaching.description}” reaches folders, schemas or hosts: it needs a program` : null,
    unattended: unattended ? "its terms refuse automations' runs" : null,
  };
}

/** Who works, as a line says it: "fake · Claude Code · default model". */
export function whoWorksWords(who: WhoWorks, product: (harness: string) => string): string {
  return [who.account ?? who.provider ?? "?", who.program ? product(who.program) : "the model alone", who.model ?? "default model"].join(" · ");
}

/** One line of what a version adds (`App.source.addedNeeds`, H.2, H.15), as a sentence: what the
 *  app or one of its jobs may now reach. */
export function addedWords(line: string, app: Pick<App, "files" | "jobs">): string {
  const job = /^job ([a-z0-9-]+)(?:: (.*))?$/.exec(line);
  if (job) {
    const name = job[1]!;
    const what = app.jobs?.find((j) => j.name === name)?.description;
    const named = what ? `its job “${what}”` : `its job ${name}`;
    if (!job[2]) return `a new job, ${what ? `“${what}”` : name}`;
    return `${named} ${reachWords(job[2], app)}`;
  }
  if (line === "notifications") return "sends you notifications";
  if (line.startsWith("secret ")) return `gets the secret ${line.slice(7)}`;
  const file = /^file ([a-z0-9-]+) \((r|rw)\)$/.exec(line);
  if (file) return `${file[2] === "rw" ? "reads and writes" : "reads"} ${folderWords(app, file[1]!)}`;
  return reachWords(line, app);
}

/** "file NEED (read|write)", "schema ID", "egress host:port", as words. */
function reachWords(what: string, app: Pick<App, "files">): string {
  const file = /^file ([a-z0-9-]+) \((read|write)\)$/.exec(what);
  if (file) return `${file[2] === "write" ? "reads and writes" : "reads"} ${folderWords(app, file[1]!)}`;
  if (what.startsWith("schema ")) return `uses the notes format ${what.slice(7)}`;
  if (what.startsWith("egress ")) return `reaches ${what.slice(7)}`;
  return what;
}

/** What started one of an app's runs (H.11), in words: "Ask", "Try", "a nudge", "the
 *  automation weekly", "its code". */
export function startedByWords(run: Pick<AppRun, "startedBy">): string {
  const s = run.startedBy;
  if (s.by === "automation") return `the automation ${"automation" in s ? s.automation : ""}`.trimEnd();
  if (s.by === "action" && "via" in s) return s.via === "ask" ? "Ask" : s.via === "nudge" ? "a nudge" : "Try";
  return "its code";
}

/** What it needs that was not given (or no longer fits): it cannot be deployed or start. */
export function missing(app: App): string[] {
  return [
    ...(app.files ?? []).filter((f) => !f.path).map((f) => `the folder ${f.name}`),
    ...(app.jobs?.length && !app.whoWorks ? ["who works"] : []),
    ...(app.secrets ?? []).filter((s) => !s.set).map((s) => `the secret ${s.name}`),
  ];
}

/** What Handler uses an agent for, one tag each (D.18): "Skill reviewer" (a need of Handler's it
 *  was given for). */
export function usedFor(agent: Agent, needs: HandlerNeed[]): string[] {
  return needs.filter((b) => b.agentId === agent.id).map((b) => b.definition.agentName);
}

/** What runs an agent and stops when it is deleted (D.22): Handler (a need it was given for),
 *  automations that run it or run when its sessions stop. */
export async function dependents(agentId: string): Promise<UseRef[]> {
  const { usedBy } = await api.uses("agent", agentId);
  return (usedBy ?? []).filter((r) => r.kind === "handler" || r.kind === "automation");
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

/** The folder an app keeps its data in (H.2): the one its jobs work in, else its only
 *  read-write one; none: an app with no folder of yours (it is outside projects). */
export function dataNeed(app: Pick<App, "files" | "jobs">): AppFileNeed | undefined {
  const files = app.files ?? [];
  const worked = files.find((f) => (app.jobs ?? []).some((j) => j.canDo.worksIn?.includes(f.name)));
  const rw = files.filter((f) => f.mode === "rw");
  return worked ?? (rw.length === 1 ? rw[0] : undefined);
}

/** The automation one of an app's suggestions makes: its name and definition, a run of the
 *  app's job, or a call to one of its routes (I.1, I.3). */
export function suggested(app: Pick<App, "name">, s: AppManifestSuggestedAutomation): { name: string; definition: Automation } {
  const name = `${app.name}-${slug(s.description)}`.slice(0, 64).replace(/-+$/, "");
  const base = { apiVersion: "handler.automation/v1" as const, description: s.description, when: s.when };
  const run = s.run.call ? { app: app.name, call: s.run.call } : { app: app.name, job: s.run.job!, input: s.run.input };
  return { name, definition: { ...base, run } };
}

/** The app whose job an automation runs; none for any other run. */
export function automationApp(definition: Automation | null | undefined): string | undefined {
  const run = definition?.run;
  return run && typeof run === "object" && "job" in run ? run.app : undefined;
}

/** A folder offered on the install page for one of the app's folders (E6): a new one (`isNew`,
 *  made at Install), or one you have; `inNotes`: in your notes root. */
export type FolderSuggestion = { path: string; isNew: boolean; inNotes?: boolean };

type Listed = { path: string; entries: DirectoryEntry[] };

/** One of the app's folders, offered from the work folders and from your notes (H.9: an app's
 *  folder may be anywhere in your home), each with its folders one level down. In each: a new
 *  folder named after the app (its folder `need` other than its data's: `<app>-<need>`) where
 *  none of that name is, and the folders you have named after it (the app's: its name or title).
 *  A new one in the first work folder only. Your notes first when `notesFirst` (its data is notes:
 *  its jobs use notes formats), last otherwise. Only suggestions: another folder can be picked. */
export function folderSuggestions(
  app: { name: string; title?: string | null },
  roots: Listed[],
  opts: { need?: string; notes?: Listed | null; notesFirst?: boolean } = {},
): FolderSuggestion[] {
  const name = opts.need ? `${app.name}-${opts.need}` : app.name;
  const names = new Set((opts.need ? [name] : [app.name, slug(appTitle(app))]).map((n) => n.toLowerCase()));
  const have = (r: Listed) => r.entries.filter((e) => names.has(e.name.toLowerCase())).map((e) => e.path);
  const fresh = (r: Listed) => (r.entries.some((e) => e.name.toLowerCase() === name.toLowerCase()) ? [] : [`${r.path.replace(/\/+$/, "")}/${name}`]);
  const first = roots[0];
  const work = [...(first ? fresh(first).map((path) => ({ path, isNew: true })) : []), ...roots.flatMap((r) => have(r).map((path) => ({ path, isNew: false })))];
  const n = opts.notes;
  const notes = n ? [...fresh(n).map((path) => ({ path, isNew: true, inNotes: true })), ...have(n).map((path) => ({ path, isNew: false, inNotes: true }))] : [];
  return opts.notesFirst ? [...notes, ...work] : [...work, ...notes];
}

/** What the install page still has to be given, each with the step where it is chosen (`at`):
 *  the app's folder, its other folders, who works on its jobs (H.2), its secrets. Empty: Install
 *  can go. */
export function stillToChoose(c: {
  title: string;
  data?: AppFileNeed;
  target: string;
  others: AppFileNeed[];
  otherFolders: Record<string, string>;
  secrets: App["secrets"];
  given: Record<string, string>;
  jobs?: boolean; // it has jobs: who works on them is chosen here
  who?: WhoWorks | null;
}): Todo[] {
  const at = (step: string) => `[data-step=${JSON.stringify(step)}]`;
  const left: Todo[] = [];
  if (c.data && !c.data.path && !c.target) left.push({ text: `${c.title}'s folder`, at: at("folder") });
  for (const f of c.others) if (!f.path && !c.otherFolders[f.name]) left.push({ text: `its folder ${f.name}`, at: at(`folder:${f.name}`) });
  if (c.jobs && !c.who) left.push({ text: "who works on its jobs", at: `${at("who-works")} [data-testid="model-choice-access"]` });
  for (const s of c.secrets ?? []) if (!s.set && !c.given[s.name]?.trim()) left.push({ text: `the secret ${s.name}`, at: at(`secret:${s.name}`) });
  return left;
}

const TAIL_LINES = 40; // with no mark of the step in the log: its last lines
const TAIL_MAX = 300; // a step's lines at most (a test run's output is long)

/** The end of an app's log that tells why a step failed: from the last line marking a deploy
 * (`== deploy 0.9.0 (#3)`: its tests' output and why it failed) or a start (`starting …`: what
 * its backend printed), else its last lines. */
export function logTail(log: string, from: "deploy" | "start" = "deploy"): string {
  const lines = log.replace(/\n$/, "").split("\n");
  const mark = from === "deploy" ? /^\[[^\]]+\] == deploy / : /^\[[^\]]+\] (starting|trying) /;
  let at = -1;
  for (let i = lines.length - 1; i >= 0 && at < 0; i--) if (mark.test(lines[i] ?? "")) at = i;
  const start = at < 0 ? lines.length - TAIL_LINES : Math.max(at, lines.length - TAIL_MAX);
  return lines.slice(Math.max(start, 0)).join("\n");
}
