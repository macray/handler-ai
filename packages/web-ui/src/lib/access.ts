// What an agent runs as (contract E): a harness, the account or the provider its model calls use
// (exactly one), and a model. An account brings its harness; a provider needs one that speaks it.
// An agent has one or more (D.1), the first by default; each session runs with one of them.
import type { Agent, AgentModel, ModelAccess as RequestedModel, Session } from "./contracts.gen";
import { harnesses } from "./harnesses.svelte";

/** One of an agent's models, as a form edits it (null: not chosen, or the default). */
export type ModelAccess = { harness: string | null; account: string | null; provider: string | null; model: string | null };

type Named = { harness?: string | null; account?: string | null; provider?: string | null; model?: string | null };

export function noAccess(): ModelAccess {
  return { harness: null, account: null, provider: null, model: null };
}

export function accessOf(w: Named): ModelAccess {
  return { harness: w.harness ?? null, account: w.account ?? null, provider: w.provider ?? null, model: w.model ?? null };
}

/** An agent's models, to edit them. */
export function modelsOf(agent: Pick<Agent, "models">): ModelAccess[] {
  return agent.models.map(accessOf);
}

/** The model a session ran with, to start another one with it. */
export function sessionModel(s: Pick<Session, "harness" | "account" | "provider" | "model">): RequestedModel {
  return requested(accessOf(s));
}

/** As a request names it: an account brings its harness, so only a provider's is sent. */
export function requested(a: ModelAccess): RequestedModel {
  return { ...a, harness: a.provider ? a.harness : null };
}

/** Chosen enough to save: an account, or a provider with its harness. */
export function chosen(a: ModelAccess): boolean {
  return !!a.account || (!!a.provider && !!a.harness);
}

/** `Claude Code · account claude-pro`, `Codex · provider llamacpp · qwen3`. */
export function accessLabel(w: Named): string {
  const via = w.account ? `account ${w.account}` : `provider ${w.provider ?? "?"}`;
  return [w.harness ? harnesses.product(w.harness) : "?", via, ...(w.model ? [w.model] : [])].join(" · ");
}

/** The same harness, account and provider: a session's conversation stays resumable. */
export function sameRun(a: Named, b: Named): boolean {
  return (a.harness ?? null) === (b.harness ?? null) && (a.account ?? null) === (b.account ?? null) && (a.provider ?? null) === (b.provider ?? null);
}

/** The same model, as a request names it (the harness of an account left out). */
export function sameModel(a: Named, b: Named): boolean {
  return JSON.stringify(requested(accessOf(a))) === JSON.stringify(requested(accessOf(b)));
}
