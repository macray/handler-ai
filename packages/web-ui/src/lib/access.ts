// What an agent runs as (contract E): a harness, the account or the provider its model calls use
// (exactly one), and a model. An account brings its harness; a provider needs one that speaks it,
// unless the agent is on the model alone (D.18: a provider, no harness). An agent has one (D.1); a
// session runs with it or another picked for that session (D.19).
import type { AgentModel, ModelAccess as RequestedModel, Session } from "./contracts.gen";
import { harnesses } from "./harnesses.svelte";

/** A model access, as a form edits it (null: not chosen, or the default). */
export type ModelAccess = { harness: string | null; account: string | null; provider: string | null; model: string | null };

type Named = { harness?: string | null; account?: string | null; provider?: string | null; model?: string | null };

export function noAccess(): ModelAccess {
  return { harness: null, account: null, provider: null, model: null };
}

export function accessOf(w: Named): ModelAccess {
  return { harness: w.harness ?? null, account: w.account ?? null, provider: w.provider ?? null, model: w.model ?? null };
}

/** The model a session ran with, to start another one with it. */
export function sessionModel(s: Pick<Session, "harness" | "account" | "provider" | "model">): RequestedModel {
  return requested(accessOf(s));
}

/** As a request names it: an account brings its harness, so only a provider's is sent. */
export function requested(a: ModelAccess): RequestedModel {
  return { ...a, harness: a.provider ? a.harness : null };
}

/** Chosen enough to save: an account, or a provider with its harness; on the model alone, a
 *  provider (no harness). */
export function chosen(a: ModelAccess, modelAlone = false): boolean {
  if (modelAlone) return !!a.provider && !a.harness;
  return !!a.account || (!!a.provider && !!a.harness);
}

/** What does the work, as the UI says it: the program's product name, or "The model alone". */
export function programLabel(w: Named): string {
  return w.harness ? harnesses.product(w.harness) : w.provider ? "The model alone" : "?";
}

/** `Claude Code · account claude-pro`, `Codex · provider llamacpp · qwen3`, `The model alone ·
 *  provider mistral-api · mistral-medium`. */
export function accessLabel(w: Named): string {
  const via = w.account ? `account ${w.account}` : `provider ${w.provider ?? "?"}`;
  return [programLabel(w), via, ...(w.model ? [w.model] : [])].join(" · ");
}

/** The same harness, account and provider: a session's conversation stays resumable. */
export function sameRun(a: Named, b: Named): boolean {
  return (a.harness ?? null) === (b.harness ?? null) && (a.account ?? null) === (b.account ?? null) && (a.provider ?? null) === (b.provider ?? null);
}

/** The same model, as a request names it (the harness of an account left out). */
export function sameModel(a: Named, b: Named): boolean {
  return JSON.stringify(requested(accessOf(a))) === JSON.stringify(requested(accessOf(b)));
}
