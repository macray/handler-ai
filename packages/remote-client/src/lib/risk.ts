// Which permission asks take a slide on the phone (the scope picked, then a slide to confirm it),
// and which two plain buttons. The computer decides (D.7's `ask.risk`, rule
// phone.an-ask-is-risky-unless-known-safe): it knows the session's folder and network policy, the
// phone does not. An ask it said nothing of (a second one waiting) is risky.
import type { SessionAsk } from "./remote.gen";

const RISKY: Record<string, string> = {
  execute: "A command runs with the agent's access: it can change or delete files in the folder.",
  delete: "It deletes a file: this phone cannot bring it back.",
  move: "It moves or renames a file: what uses it may stop finding it.",
  fetch: "It reaches a site on the network.",
};
const UNSURE = "Handler cannot tell that it stays in this folder.";

/** The computer's word on this ask: the session's `ask` when it is this very tool call. */
export function hostRisk(tool: { toolCallId: string }, ask: SessionAsk | null | undefined): SessionAsk["risk"] | null {
  return ask && ask.toolCallId === tool.toolCallId ? ask.risk : null;
}

/** Why the ask is risky, in a sentence; null when the computer says it is safe (two buttons
 *  answer it). */
export function riskOf(tool: { toolCallId: string; kind?: string | null }, ask: SessionAsk | null | undefined): string | null {
  if (hostRisk(tool, ask) === "safe") return null;
  return RISKY[tool.kind ?? ""] ?? UNSURE;
}

/** Where it acts, as far as the computer said: a safe ask stays in the folder; a fetch reaches
 *  the network. null when it does not say. */
export function reachOf(tool: { toolCallId: string; kind?: string | null }, ask: SessionAsk | null | undefined): string | null {
  if (hostRisk(tool, ask) === "safe") return "in the folder";
  if (tool.kind === "fetch") return "uses the network";
  return null;
}
