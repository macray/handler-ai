// An agent's own environment variables (D.8): plain values in its settings, never a secret (a
// tool's connection gives those). Edited as rows in the agent form; saved as NAME → value.

/** One variable as typed: a row of the form. */
export type EnvRow = { name: string; value: string };

const NAME = /^[A-Za-z_][A-Za-z0-9_]*$/;

/** An agent's variables as rows, by name. */
export function envRows(env: Record<string, string> | null | undefined): EnvRow[] {
  return Object.entries(env ?? {})
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([name, value]) => ({ name, value }));
}

/** The rows typed: a row with neither a name nor a value is left out. */
function typed(rows: EnvRow[]): EnvRow[] {
  return rows.filter((r) => r.name.trim() || r.value).map((r) => ({ name: r.name.trim(), value: r.value }));
}

/** The rows to save, NAME → value. */
export function envOf(rows: EnvRow[]): Record<string, string> {
  return Object.fromEntries(typed(rows).map((r) => [r.name, r.value]));
}

/** Why the rows cannot be saved, or null. What Handler, its harness or its tools set already is
 *  said by the save (who sets it). */
export function envProblem(rows: EnvRow[]): string | null {
  const names = typed(rows).map((r) => r.name);
  const bad = names.find((n) => !NAME.test(n));
  if (bad === "") return "Give each environment variable a name.";
  if (bad !== undefined) return `Environment variable ${bad}: letters, digits and _ only, not starting with a digit.`;
  const twice = names.find((n, i) => names.indexOf(n) !== i);
  return twice ? `Environment variable ${twice} is set twice.` : null;
}
