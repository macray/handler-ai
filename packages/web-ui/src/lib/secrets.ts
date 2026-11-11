// Secrets as Settings → Secrets shows them (D.14, E3): by state (what needs you, what is in use,
// what nothing uses), those in use by what they belong to; where each value is, and the page its
// owner is set on (where it is changed).
import type { SecretInfo } from "./contracts.gen";
import { href, type Route } from "./router.svelte";

// the kinds of owners ("providers/openrouter"), with the page each is set on
const OWNERS: Record<string, { page: string; route: (name: string, tool?: string) => Route }> = {
  accounts: { page: "Model access", route: () => ({ view: "settings", section: "models" }) },
  providers: { page: "Model access", route: () => ({ view: "settings", section: "models" }) },
  connections: { page: "Tools", route: (_, tool) => (tool ? { view: "tool", name: tool } : { view: "addons" }) },
  apps: { page: "Apps", route: (name) => ({ view: "apps", app: name }) },
};

/** The kinds of owners, in the page's order. */
export const GROUPS = [
  { id: "accounts", label: "Accounts" },
  { id: "providers", label: "Providers" },
  { id: "connections", label: "Tool connections" },
  { id: "apps", label: "Apps" },
] as const;

/** Its group: its first owner's kind, or "unused". */
export function group(s: SecretInfo): string {
  const kind = s.usedBy?.[0]?.split("/")[0];
  return kind && kind in OWNERS ? kind : "unused";
}

/**
 * Its state: `missing` (used, without a value), `exposed` (an agent reads the value itself),
 * `readable` (it would be read, but no agent gets it), `sealed`, or `unused`.
 */
export type SecretState = "missing" | "exposed" | "readable" | "sealed" | "unused";

export function stateOf(s: SecretInfo): SecretState {
  if (!s.usedBy?.length) return "unused";
  if (s.hasValue === false) return "missing";
  if (s.visible) return s.agents?.length ? "exposed" : "readable";
  return "sealed";
}

/** What needs you: a value missing, or one an agent reads. */
export const needsYou = (s: SecretInfo): boolean => ["missing", "exposed"].includes(stateOf(s));

/** Its owners' names ("openrouter") and its slot in words ("key", "theme token"). */
export function names(s: SecretInfo): { owner: string; slot: string } {
  const usedBy = s.usedBy ?? [];
  if (!usedBy.length) return { owner: s.path, slot: "" };
  const name = s.path.split("/").at(-1) ?? "";
  return {
    owner: usedBy.map((u) => u.split("/").slice(1).join("/")).join(", "),
    slot: name === "apiKey" ? "key" : name.replaceAll("_", " "),
  };
}

/** Where its value is, in words. */
export function source(s: SecretInfo): string {
  return {
    secret: "kept by Handler",
    env: "from an environment variable of Handler",
    file: "from a file",
    command: "printed by a command",
  }[s.source ?? "secret"];
}

/** Why an agent gets the value itself, short (`visible` is the daemon's sentence). */
export function why(visible: string): string {
  if (visible.startsWith("the proxy cannot carry it")) return "too short or not plain text to seal";
  if (visible.startsWith("no host to give it to")) return "no site to seal it to";
  return visible;
}

/** A host as people write it: without the https port. */
export const host = (h: string): string => h.replace(/:443$/, "");

/** An agent as "<project> · <agent>" (or its name alone), split for its chip. */
export function agent(label: string): { name: string; project?: string } {
  const at = label.lastIndexOf(" · ");
  return at < 0 ? { name: label } : { name: label.slice(at + 3), project: label.slice(0, at) };
}

/** A stored value nothing uses: the only kind removed from here. */
export function removable(s: SecretInfo): boolean {
  return (s.source ?? "secret") === "secret" && !s.usedBy?.length && s.createdAt != null;
}

/**
 * Where its owner is set, and its value changed: the page's name, the owner's, and its address.
 * `tools`: each connection's tool, for the tool's page.
 */
export function owner(usedBy: string, tools: Record<string, string> = {}): { page: string; name: string; href: string } {
  const [kind = "", ...rest] = usedBy.split("/");
  const name = rest.join("/");
  const o = OWNERS[kind]!;
  return { page: o.page, name, href: href(o.route(name, tools[name])) };
}
