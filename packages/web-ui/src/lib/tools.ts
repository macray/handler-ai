// Tools (G, the files' and the API's `addon`) and your connections to them (D.15, `binding`), as
// the Library says them: a tool's state in one word, what it reaches, where it comes from.
import type { AddonInfo, BindingInfo } from "./contracts.gen";
import { hasSlots } from "./setup";

/** A tool's state on the shelf: broken (it, or one of its connections, cannot be read), not set
 *  up (it asks for settings and has no connection), its image not ready, preparing, or ready. */
export type ToolState = "broken" | "not-set-up" | "not-ready" | "preparing" | "ready";

export function toolState(tool: AddonInfo, connections: BindingInfo[]): ToolState {
  if (tool.error || tool.state === "failed" || connections.some((c) => c.error)) return "broken";
  if (hasSlots(tool) && !connections.length) return "not-set-up";
  if (tool.state === "installed") return "not-ready";
  if (tool.state === "preparing") return "preparing";
  return "ready";
}

export const TOOL_STATE: Record<ToolState, string> = {
  broken: "Broken",
  "not-set-up": "Not set up",
  "not-ready": "Not ready",
  preparing: "Preparing",
  ready: "Ready",
};

/** What went wrong, in full, for a broken tool: its own message, then its connections'. */
export function brokenBecause(tool: AddonInfo, connections: BindingInfo[]): string[] {
  return [
    ...(tool.error ? [tool.error] : tool.state === "failed" ? [tool.stateDetail ?? "its image could not be built"] : []),
    ...connections.filter((c) => c.error).map((c) => `the connection ${c.name}: ${c.error}`),
  ];
}

/** How many sites it reaches: "5 sites", "no site". */
export function sitesWords(tool: AddonInfo): string {
  const n = tool.egress?.length ?? 0;
  return n ? `${n} site${n === 1 ? "" : "s"}` : "no site";
}

/** Where it comes from, in a few words. */
export function toolOrigin(tool: AddonInfo): string {
  if (tool.builtin) return "from Handler, built in";
  if (tool.source?.startsWith("source:")) {
    const id = tool.source.slice("source:".length).split("/")[0];
    const from = id === "official" ? "from Handler" : `from ${id}`;
    return tool.overridesBuiltin ? `${from}, in place of the built-in` : from;
  }
  return tool.overridesBuiltin ? "yours, in place of the built-in" : "yours";
}
