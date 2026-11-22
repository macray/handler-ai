// Home's sessions (E5): the shared ones waiting for the person on top ("Needs you"), then the
// other shared ones, the working first; and the trace of those no longer shared, kept on this
// phone only until the client starts again.
import type { SharedSession } from "./remote.gen";

export type SessionState = "needs" | "working" | "idle";

export interface HomeSessions {
  needs: SharedSession[];
  shared: SharedSession[];
}

/** No longer shared: its title and when it left Home (ms). */
export interface Unshared {
  id: string;
  title: string;
  at: number;
}

export function stateOf(s: SharedSession): SessionState {
  return s.pendingPermissions ? "needs" : s.busy ? "working" : "idle";
}

/** A state as its row says it, a word in its colour. */
export const STATE_WORDS: Record<SessionState, string> = { needs: "needs you", working: "working", idle: "idle" };

const folderOf = (s: SharedSession): string => s.scope.split("/").filter(Boolean).at(-1) ?? s.scope;

/** A session's name: its own title; until it has one, its project's name (its agent's outside
 *  projects), else its folder's last part. */
export function titleOf(s: SharedSession): string {
  return s.title ?? s.project ?? s.label ?? folderOf(s);
}

/** Where it runs, after its state: project · agent (an agent outside projects: the agent alone),
 *  without what its title already says. */
export function placeOf(s: SharedSession): string {
  if (s.title) return [s.project, s.agent ?? s.label].filter(Boolean).join(" · ");
  if (s.project) return s.agent ?? "";
  return "";
}

/** The shared sessions waiting for the person first, then the others (working before idle);
 *  the host's order kept inside each. */
export function homeSessions(sessions: SharedSession[]): HomeSessions {
  const needs = sessions.filter((s) => stateOf(s) === "needs");
  const rest = sessions.filter((s) => stateOf(s) !== "needs");
  return { needs, shared: [...rest.filter((s) => s.busy), ...rest.filter((s) => !s.busy)] };
}

/** The trace after a new list: the sessions that were shown and are gone added (latest first),
 *  those shared again removed. */
export function unsharedAfter(
  before: SharedSession[],
  after: SharedSession[],
  trace: Unshared[],
  now = Date.now(),
): Unshared[] {
  const ids = new Set(after.map((s) => s.id));
  const gone = before.filter((s) => !ids.has(s.id)).map((s) => ({ id: s.id, title: titleOf(s), at: now }));
  const kept = trace.filter((u) => !ids.has(u.id) && !gone.some((g) => g.id === u.id));
  return [...gone, ...kept];
}
