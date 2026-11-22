// Who works (E2, D.1, D.19): one control in three linked parts, account or provider ▾ · program ·
// model ▾. This is its logic, the component (WhoWorks) only shows it. The first menu lists the
// person's accounts and providers, one row each, grouped (Subscriptions; API keys and local
// models), each saying which programs it works with; what cannot run here is folded, with a count
// and why: not made for the project's area (running one anyway is the terminal's, outside the
// project), or not ready (its login's words). The program part is text when the row has one
// program, a menu when several (alphabetical, the model alone last: offered only where this agent
// may be on it, else greyed with why). The model part is the row's models, "default model" first.
// Nothing is picked between two rows: one ready row is chosen by itself, the agent's own is chosen
// as it is; two or more and none chosen, the person chooses. An agent running unattended on a
// subscription gets one line recommending an API key, with a switch to one (vendors' terms).
import { requested, sameModel, type ModelAccess } from "./access";
import { loginProblem } from "./accounts";
import { allows } from "./areas.svelte";
import type { AccountInfo, Agent, HarnessInfo, ModelAccess as RequestedModel, ProviderInfo } from "./contracts.gen";

/** Where the control is: the agent, what the person connected, and what may change. */
export type Place = {
  agent: Pick<Agent, "name" | "model" | "area" | "modelAlone">;
  accounts: AccountInfo[];
  providers: ProviderInfo[];
  harnesses: HarnessInfo[]; // for the programs' product names and their logins' verdicts
  loaded: boolean; // the accounts and providers are known (before: the agent's own only)
  form: boolean; // the agent form, choosing the agent's own model (else a session's or a run's)
  switchKind: boolean; // the agent form: the model alone and an agent program may be swapped
  limits?: Limits; // what the work asks of who does it (an app's job, H.2)
};

/** What the work asks of who does it, each choice that cannot do it greyed with why (an app's
 *  job, H.2, rule app-job.runs-as-its-who-works): `alone`, why the model alone cannot (the job
 *  reaches folders, schemas or hosts: it needs a program); `unattended`, why a subscription
 *  whose login's terms refuse runs nobody follows cannot (an automation runs it, I.7). */
export type Limits = { alone?: string | null; unattended?: string | null };

/** A program of a row: a harness, or "" for the model alone. */
export type Program = { harness: string; label: string; offered: boolean; why: string | null };

/** A model of a row: "" its default. */
export type Model = { value: string; label: string; detail: string | null; own: boolean; problem: string | null };

export type Kind = "subscription" | "API key" | "local";

/** One account or provider in the first menu. */
export type Row = {
  key: string;
  name: string;
  account: string | null;
  provider: string | null;
  group: "subscriptions" | "keys";
  kind: Kind;
  kindWords: string; // "for your own use", "pay per use", "a local model on this computer"
  programs: Program[]; // alphabetical, the model alone last
  worksWith: string; // "works with Claude Code, pi"
  models: Model[];
  short: string; // a provider's models in short: "a, b, c…"
  own: boolean; // the agent's own
  problem: string | null; // the agent's own model's, when it cannot start now
  why: string | null; // null: it can be chosen; else greyed in place, with why
};

/** What cannot run here, folded under its count. */
export type Folded = {
  name: string;
  kind: Kind;
  why: string; // "made for Personal", "Logged out 2 days ago"
  action: "Log in" | "Log in again" | null; // an account's login to do
  own: boolean;
  anyway: string | null; // the command running it here anyway (outside the project), not in the agent form
};
export type Fold = { label: string; count: number; rows: Folded[] };
export type Folds = { area: Fold | null; notReady: Fold | null; areaHint: string | null };

/** What is chosen: a row, its program ("" the model alone), its model ("" its default). */
export type Choice = { key: string; harness: string; model: string };

export type State = "chosen" | "ask" | "none";

const KIND_WORDS: Record<Kind, string> = { subscription: "for your own use", "API key": "pay per use", local: "a local model on this computer" };
export const ALONE = "The model alone";

const keyOf = (x: { account?: string | null; provider?: string | null }) => (x.account ? `account:${x.account}` : `provider:${x.provider}`);
const sentence = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

function productOf(place: Place, harness: string): string {
  return harness ? (place.harnesses.find((h) => h.name === harness)?.product ?? harness) : ALONE;
}

function hasModel(place: Place): boolean {
  return !!(place.agent.model.account || place.agent.model.provider);
}

function isOwn(place: Place, x: { account?: string | null; provider?: string | null }): boolean {
  const m = place.agent.model;
  return hasModel(place) && keyOf(x) === keyOf(m);
}

/** A provider's models, speech ones left out. */
function idsOf(p: ProviderInfo | undefined): string[] {
  return (p?.models ?? []).filter((m) => !m.speech).map((m) => m.id);
}

/** A provider's models, in short, beside its name: "Sonnet, Opus, Haiku…". */
export function shortModels(p: ProviderInfo | undefined): string {
  const ids = idsOf(p);
  return ids.length > 3 ? `${ids.slice(0, 3).join(", ")}…` : ids.join(", ");
}

/** The programs a row works with: an account its one, a provider those that speak it
 *  (alphabetical by product name), then the model alone where the provider has it. */
function programsOf(place: Place, harnesses: string[], modelAlone: boolean): Program[] {
  const { agent, switchKind } = place;
  const forAgent = (alone: boolean) => switchKind || agent.modelAlone === alone;
  const programs = harnesses
    .map((h): Program => ({ harness: h, label: productOf(place, h), offered: forAgent(false), why: forAgent(false) ? null : "not for this agent" }))
    .sort((a, b) => a.label.localeCompare(b.label, undefined, { sensitivity: "base" }));
  if (modelAlone) {
    const why = forAgent(true) ? (place.limits?.alone ?? null) : "not for this agent";
    programs.push({ harness: "", label: ALONE, offered: !why, why });
  }
  return programs;
}

/** A subscription whose login's terms refuse runs nobody follows (I.7), where the work runs so. */
function refusedUnattended(place: Place, kind: Kind, harnesses: string[]): string | null {
  const why = place.limits?.unattended;
  if (!why || kind !== "subscription") return null;
  return harnesses.some((h) => place.harnesses.find((x) => x.name === h)?.login?.unattended === "refused") ? why : null;
}

/** A row's models: its default first (a provider's first model beside it), then the agent's own
 *  when it names one, then the provider's others. An account has no list. */
function modelsOf(place: Place, x: { account: string | null; provider: string | null }, own: boolean): Model[] {
  const ids = x.provider ? idsOf(place.providers.find((p) => p.name === x.provider)) : [];
  const m = place.agent.model;
  const mine = own ? (m.model ?? "") : null;
  const problem = own ? (m.problem ?? null) : null;
  const models: Model[] = [{ value: "", label: "default model", detail: ids[0] ?? null, own: mine === "", problem: mine === "" ? problem : null }];
  if (mine) models.push({ value: mine, label: mine, detail: null, own: true, problem });
  for (const id of ids.slice(1)) if (id !== mine) models.push({ value: id, label: id, detail: null, own: false, problem: null });
  return models;
}

function row(place: Place, x: { account: string | null; provider: string | null }, kind: Kind, harnesses: string[], modelAlone: boolean): Row {
  const own = isOwn(place, x);
  const programs = programsOf(place, harnesses, modelAlone);
  const offered = programs.filter((p) => p.offered);
  const why = refusedUnattended(place, kind, harnesses) ?? (offered.length
    ? null
    : kind === "subscription"
      ? "needs an API key"
      : programs.length
        ? `${programs.map((p) => p.label).join(", ")} only`
        : "works with no program");
  return {
    key: keyOf(x),
    name: (x.account ?? x.provider)!,
    account: x.account,
    provider: x.provider,
    group: kind === "subscription" ? "subscriptions" : "keys",
    kind,
    kindWords: KIND_WORDS[kind],
    programs,
    worksWith: `works with ${offered.length ? offered.map((p) => (p.harness ? p.label : "the model alone")).join(", ") : "nothing here"}`,
    models: modelsOf(place, x, own),
    short: shortModels(place.providers.find((p) => p.name === x.provider)),
    own,
    problem: own ? (place.agent.model.problem ?? null) : null,
    why,
  };
}

/** The first menu's rows: subscriptions, then API keys and local models, those ready and made
 *  for the area; the agent's own first (its group first), even when it cannot start now. */
export function rowsOf(place: Place): Row[] {
  const { agent, accounts, providers, loaded } = place;
  const fits = (areas: string[] | undefined) => allows(agent.area, areas);
  const shown = (x: { name: string; status: string; areas?: string[] }, account: boolean) =>
    fits(x.areas) && (x.status === "ready" || isOwn(place, account ? { account: x.name } : { provider: x.name }));
  const subs = accounts.filter((a) => a.harness && shown(a, true)).map((a) => row(place, { account: a.name, provider: null }, "subscription", [a.harness!], false));
  const keys = providers
    .filter((p) => shown(p, false))
    .map((p) => row(place, { account: null, provider: p.name }, p.local ? "local" : "API key", p.harnesses ?? [], !!p.modelAlone));
  // not loaded yet: the agent's own, from its model alone
  const m = agent.model;
  if (!loaded && hasModel(place)) {
    const x = { account: m.account ?? null, provider: m.account ? null : (m.provider ?? null) };
    const harnesses = x.account ? [m.harness ?? ""] : m.harness ? [m.harness] : [];
    return [row(place, x, x.account ? "subscription" : "API key", harnesses, !m.harness)];
  }
  const ownFirst = (list: Row[]) => [...list.filter((r) => r.own), ...list.filter((r) => !r.own)];
  const [first, second] = [ownFirst(subs), ownFirst(keys)];
  return second.some((r) => r.own) ? [...second, ...first] : [...first, ...second];
}

/** What cannot run here: not made for the project's area (counted first), not ready; each with why. */
export function foldsOf(place: Place, now = Date.now()): Folds {
  const { agent, accounts, providers, form } = place;
  const madeFor = (areas: string[] | undefined) => (areas?.length ? `made for ${areas.join(", ")}` : `not made for ${agent.area} projects`);
  const anyway = (name: string) => (form ? null : `handler run ${name} --anyway`);
  const area: Folded[] = [];
  const notReady: Folded[] = [];
  for (const a of accounts) {
    if (!a.harness) continue;
    const mine = isOwn(place, { account: a.name });
    if (!allows(agent.area, a.areas)) area.push({ name: a.name, kind: "subscription", why: madeFor(a.areas), action: null, own: mine, anyway: anyway(a.name) });
    else if (a.status !== "ready" && !mine) {
      const login = loginProblem(a, now);
      const why = login?.text ?? a.error ?? (a.problems?.length ? sentence(a.problems.join("; ")) : "Not ready");
      notReady.push({ name: a.name, kind: "subscription", why, action: login?.action ?? null, own: false, anyway: null });
    }
  }
  for (const p of providers) {
    const kind: Kind = p.local ? "local" : "API key";
    const mine = isOwn(place, { provider: p.name });
    if (!allows(agent.area, p.areas)) area.push({ name: p.name, kind, why: madeFor(p.areas), action: null, own: mine, anyway: anyway(p.name) });
    else if (p.status !== "ready" && !mine) {
      const why = p.error ?? (p.problems?.length ? sentence(p.problems.join("; ")) : "Not ready");
      notReady.push({ name: p.name, kind, why, action: null, own: false, anyway: null });
    }
  }
  const fold = (label: string, rows: Folded[]): Fold | null => (rows.length ? { label, count: rows.length, rows } : null);
  return {
    area: fold(`Not for ${agent.area} projects`, area),
    notReady: fold("Not ready", notReady),
    areaHint: area.length && form ? "An agent of this project runs only what is made for its area (Settings → Model access)." : null,
  };
}

/** The program part: a menu when there is a choice, or the model alone greyed (so the person
 *  learns it exists); else plain text (a subscription's one program; an agent on the model alone,
 *  whose kind is fixed: its row's programs are not for it). */
export function programPart(r: Row): "text" | "menu" {
  const offered = r.programs.filter((p) => p.offered).length;
  return offered > 1 || (offered === 1 && r.programs.some((p) => !p.offered && p.harness === "")) ? "menu" : "text";
}

/** The row chosen: its program kept when the row has it, else the row's first; its model back
 *  to the default (the agent's own, on its own row and program). */
export function pickRow(place: Place, rows: Row[], current: Choice | null, key: string): Choice | null {
  const r = rows.find((x) => x.key === key);
  if (!r || r.why) return current;
  const offered = r.programs.filter((p) => p.offered);
  const harness = (offered.find((p) => p.harness === current?.harness) ?? offered[0])?.harness ?? "";
  const ownProgram = r.own && harness === ownHarness(place, r);
  return { key, harness, model: ownProgram ? (place.agent.model.model ?? "") : "" };
}

/** Another program on the same row: the model kept. */
export function pickProgram(rows: Row[], current: Choice, harness: string): Choice {
  const r = rows.find((x) => x.key === current.key);
  return r?.programs.some((p) => p.offered && p.harness === harness) ? { ...current, harness } : current;
}

export function pickModel(current: Choice, model: string): Choice {
  return { ...current, model };
}

function ownHarness(place: Place, r: Row): string {
  return r.account ? (r.programs[0]?.harness ?? "") : (place.agent.model.harness ?? "");
}

/** What is chosen first: the agent's own as it is; else the one row that can be chosen; else
 *  nothing (two or more: the person chooses, never the wrong account by default). */
export function initial(place: Place, rows: Row[]): Choice | null {
  const mine = rows.find((r) => r.own);
  if (mine) {
    const harness = ownHarness(place, mine);
    // its program no longer one of its row's (the kind just switched): the row's first
    if (!mine.programs.some((p) => p.offered && p.harness === harness)) return pickRow(place, rows, null, mine.key) ?? null;
    return { key: mine.key, harness, model: place.agent.model.model ?? "" };
  }
  const can = rows.filter((r) => !r.why);
  const [only] = can;
  return can.length === 1 && only ? pickRow(place, rows, null, only.key) : null;
}

/** The control's state: chosen; two or more and none chosen ("Choose an account", never picks
 *  for you); nothing can run here ("Connect a model to start"). */
export function stateOf(rows: Row[], choice: Choice | null): State {
  if (choice && rows.some((r) => r.key === choice.key)) return "chosen";
  return rows.some((r) => !r.why) ? "ask" : "none";
}

/** The choice, as the agent's model is written. */
export function accessOfChoice(rows: Row[], choice: Choice | null): ModelAccess | null {
  const r = choice && rows.find((x) => x.key === choice.key);
  if (!r || !choice) return null;
  return { harness: choice.harness || null, account: r.account, provider: r.provider, model: choice.model || null };
}

/** For a session: undefined when it is the agent's own, else the model as a request names it. */
export function sessionValue(place: Place, rows: Row[], choice: Choice | null): RequestedModel | undefined {
  const picked = accessOfChoice(rows, choice);
  return !picked || sameModel(picked, place.agent.model) ? undefined : requested(picked);
}

/** The model part's words: "default model" until changed. */
export function modelLabel(choice: Choice | null): string {
  return choice?.model || "default model";
}

/** Changed for this session only: what the footer says, and its button making it the agent's own. */
export function sessionNote(place: Place, rows: Row[], choice: Choice | null): { text: string; makeDefault: string } | null {
  const r = choice && rows.find((x) => x.key === choice.key);
  if (!r || !choice || !sessionValue(place, rows, choice)) return null;
  const name = place.agent.name;
  const m = place.agent.model;
  const stays = m.account ?? m.provider;
  return {
    text: `${modelLabel(choice)} on ${r.name}, for this session only. ${name} stays on ${stays ? `${stays} · ${m.model ?? "default model"}` : "its own"}.`,
    makeDefault: `Make it ${name}'s default`,
  };
}

/** An agent running unattended (a job, an automation: the caller says) on a subscription: one line
 *  recommending an API key (vendors' terms), with a switch to one that works with the same program
 *  when there is one, else another; its login's verdict with its terms when they are to check. */
export function unattendedLine(
  place: Place,
  rows: Row[],
  choice: Choice | null,
  unattended: boolean,
): { text: string; verdict: string | null; terms: string | null; switchTo: Choice | null; switchName: string | null } | null {
  const r = choice && rows.find((x) => x.key === choice.key);
  if (!unattended || !r || !choice || r.kind !== "subscription") return null;
  const login = place.harnesses.find((h) => h.name === choice.harness)?.login;
  const keys = rows.filter((x) => x.group === "keys" && !x.why);
  const same = keys.find((x) => x.programs.some((p) => p.offered && p.harness === choice.harness)) ?? keys[0];
  return {
    text: "A subscription is for sessions you follow. An API key is recommended here.",
    verdict: login?.unattended ?? null,
    terms: login?.unattended === "check-terms" ? login.terms : null,
    switchTo: same ? pickRow(place, rows, choice, same.key) : null,
    switchName: same?.name ?? null,
  };
}
