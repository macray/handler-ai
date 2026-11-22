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

/** Where it comes from, as its page's *From* says it: "Handler, built in", "Handler's own
 *  tools", "the source acme", "a folder you chose", "an archive online", "your tools folder";
 *  and "in place of the built-in". */
export function toolFrom(tool: AddonInfo): string {
  if (tool.builtin) return "Handler, built in";
  const id = tool.source?.startsWith("source:") ? tool.source.slice("source:".length).split("/")[0] : null;
  const other = tool.source && /^[a-z]+:\/\//.test(tool.source) ? "an archive online" : tool.source ? "a folder you chose" : "your tools folder";
  const from = id === "official" ? "Handler's own tools" : id ? `the source ${id}` : other;
  return tool.overridesBuiltin ? `${from}, in place of the built-in` : from;
}

/** The Tools shelf's Yours: each tool with its connections, then the connections whose tool is
 *  not installed (or that cannot be read), listed apart. */
export function shelfOf(tools: AddonInfo[], connections: BindingInfo[]): { tools: { tool: AddonInfo; connections: BindingInfo[] }[]; orphans: BindingInfo[] } {
  return {
    tools: tools.map((tool) => ({ tool, connections: connections.filter((c) => c.addon === tool.name) })),
    orphans: connections.filter((c) => !tools.some((t) => t.name === c.addon)),
  };
}

/** Who a connection is given to, by its `usedBy` ("agents/shop/dev", "projects/blog",
 *  "ad-hoc/<id>"), said as the rest of the UI says them: "shop · dev", "all agents of blog",
 *  "<id> (outside projects)". */
export function connectionUsers(usedBy: string[] = []): string[] {
  return usedBy.map((u) => {
    const [kind = "", ...rest] = u.split("/");
    if (kind === "agents") return rest.join(" · ");
    if (kind === "projects") return `all agents of ${rest.join("/")}`;
    return `${rest.join("/")} (outside projects)`;
  });
}

/** Who a tool is given to, from what uses it (D.22): its agents by their label, its projects
 *  as "all agents of <project>", each once; the rest (an automation, an app) left out. */
export function toolUsers(refs: { kind: string; label: string }[] = []): string[] {
  const named = refs.flatMap((r) => (r.kind === "agent" ? [r.label] : r.kind === "project" ? [`all agents of ${r.label}`] : []));
  return [...new Set(named)];
}

/** "given to shop · dev and blog · writer", or "not given to any agent yet". */
export function givenWords(users: string[]): string {
  if (!users.length) return "not given to any agent yet";
  const list = users.length === 1 ? users[0] : `${users.slice(0, -1).join(", ")} and ${users.at(-1)}`;
  return `given to ${list}`;
}

/** What a connection holds, in short: its settings' values (its address, its store), then its
 *  secrets, sealed: ["dev.shop.example.com", "theme_token sealed"]. */
export function connectionFacts(c: BindingInfo): string[] {
  return [...Object.values(c.settings ?? {}), ...(c.secrets?.length ? [`${c.secrets.join(", ")} sealed`] : [])];
}
