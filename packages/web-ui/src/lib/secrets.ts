// Secrets as Settings → Secrets shows them (D.14, E3): grouped by what they belong to, where each
// value is, and the page its owner is set on (where it is changed).
import type { SecretInfo } from "./contracts.gen";
import { href, type Route } from "./router.svelte";

// the kinds of owners ("providers/openrouter"), with the page each is set on
const OWNERS: Record<string, Route> = {
  accounts: { view: "settings", section: "models" },
  providers: { view: "settings", section: "models" },
  bindings: { view: "addons" },
  apps: { view: "apps" },
};

/** The groups of the page, in its order: by the kind of what a secret belongs to. */
export const GROUPS = [
  { id: "accounts", label: "Accounts" },
  { id: "providers", label: "Providers" },
  { id: "bindings", label: "Addon configurations" },
  { id: "apps", label: "Apps" },
  { id: "unused", label: "Not used" },
] as const;

/** Its group: its first owner's kind, or "unused". */
export function group(s: SecretInfo): string {
  const kind = s.usedBy?.[0]?.split("/")[0];
  return kind && kind in OWNERS ? kind : "unused";
}

/** Its title in its group: its owners' names and the slot ("openrouter · key"), or its path. */
export function slot(s: SecretInfo): string {
  const usedBy = s.usedBy ?? [];
  if (!usedBy.length) return s.path;
  const name = s.path.split("/").at(-1) ?? "";
  return `${usedBy.map((u) => u.split("/").slice(1).join("/")).join(", ")} · ${name === "apiKey" ? "key" : name}`;
}

/** Where its value is, in words. */
export function source(s: SecretInfo): string {
  const where = {
    secret: "kept by Handler",
    env: "from an environment variable of Handler",
    file: "from a file",
    command: "printed by a command",
  }[s.source ?? "secret"];
  return s.hasValue === false ? `${where}: not set` : where;
}

/** A stored value nothing uses: the only kind removed from here. */
export function removable(s: SecretInfo): boolean {
  return (s.source ?? "secret") === "secret" && !s.usedBy?.length && s.createdAt != null;
}

/** The page where its owner is set, and its value changed. */
export const ownerHref = (usedBy: string) => href(OWNERS[usedBy.split("/")[0]!]!);
