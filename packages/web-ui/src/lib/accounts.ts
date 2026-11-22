// An account's login when it does not work (D.9, E1, E8), in the same words on its row, in the
// model-access picker and in `handler account list`: "Logged out <when>" when the login Handler
// was given ended (a token past its `expiresAt`: the only end handlerd can tell), with "Log in
// again"; "Not logged in" when it has none, with "Log in".
import type { AccountInfo } from "./contracts.gen";
import { ago } from "./agents";

export type LoginProblem = { text: string; action: "Log in" | "Log in again"; ended: boolean };

/** What stops it being used, or null when it is ready (or invalid: its own error says why). */
export function loginProblem(a: Pick<AccountInfo, "status" | "problems" | "expiresAt">, now = Date.now()): LoginProblem | null {
  if (a.status !== "incomplete") return null;
  // handlerd gives an end only to a login it has (`loggedInAt` + its harness's lifetime), and
  // says incomplete with one only once it passed
  if (a.expiresAt) return { text: `Logged out ${ago(a.expiresAt, now)}`, action: "Log in again", ended: true };
  const other = (a.problems ?? []).filter((p) => p !== "not logged in").join("; ");
  return { text: other ? other.charAt(0).toUpperCase() + other.slice(1) : "Not logged in", action: "Log in", ended: false };
}
