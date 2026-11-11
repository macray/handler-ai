// A provider's test (D.12): its server asked for its models from where a sandbox would. A server
// on this computer is shown ready only once it answered.
import type { ProviderInfo, ProviderModel, ProviderReach } from "./contracts.gen";

const THIS_COMPUTER = ["127.0.0.1", "localhost", "[::1]", "host.containers.internal"];

/** Whether an endpoint is a server on this computer (as handlerd says of a saved provider). */
export function onThisComputer(url: string): boolean {
  try {
    return THIS_COMPUTER.includes(new URL(url.trim()).hostname);
  } catch {
    return false;
  }
}

export type ReachState = "untested" | "testing" | "ready" | "not reached";

/** A test's state in words: "Ready: … answered, 2 models" or "Not reached: why". */
export function reachLine(reach: ProviderReach): string {
  if (!reach.ok) return `Not reached: ${reach.error}`;
  const where = reach.urls.map((u) => new URL(u).host).join(", ");
  const n = reach.models?.length ?? 0;
  return `Ready: ${where} answered, ${n === 0 ? "serving no model yet" : n === 1 ? "1 model" : `${n} models`}`;
}

/** A provider's state in the list (after its dot): a server on this computer is ready once reached. */
export function statusOf(p: ProviderInfo): { state: "ready" | "warn" | "danger"; text: string } {
  if (p.status === "invalid") return { state: "danger", text: "Can't be used" };
  if (p.status === "incomplete") return { state: "warn", text: "To finish" };
  if (!p.local) return { state: "ready", text: "Ready" };
  if (!p.reached) return { state: "warn", text: "Not tested yet" };
  return p.reached.ok ? { state: "ready", text: "Ready" } : { state: "danger", text: "Not reached" };
}

/** The form's models after a test: what the server serves when none is typed yet; else the typed
 * ones, their context filled where the server reports it and none is typed. */
export function fillModels(models: ProviderModel[], served: ProviderModel[]): ProviderModel[] {
  if (!models.some((m) => m.id.trim())) return served.map((m) => ({ ...m }));
  return models.map((m) => {
    const found = served.find((s) => s.id === m.id);
    return found?.contextWindow && !m.contextWindow ? { ...m, contextWindow: found.contextWindow } : m;
  });
}
