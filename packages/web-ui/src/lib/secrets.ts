// Secrets as Settings → Secrets shows them (D.14, E3): what each belongs to, where its value is,
// and whether agents can read it (else handler adds it to their requests to its hosts).
import type { SecretInfo } from "./contracts.gen";
import { href, type Route } from "./router.svelte";

export type Owner = { label: string; route: Route };

const OWNERS: Record<string, { word: string; route: Route }> = {
  accounts: { word: "Account", route: { view: "settings", section: "models" } },
  providers: { word: "Provider", route: { view: "settings", section: "models" } },
  bindings: { word: "Addon configuration", route: { view: "settings", section: "addons" } },
  apps: { word: "App", route: { view: "apps" } },
};

/** What a secret belongs to ("accounts/perso" → "Account perso"), with the page it is set on. */
export function owner(usedBy: string): Owner {
  const [kind = "", ...name] = usedBy.split("/");
  const known = OWNERS[kind];
  return known ? { label: `${known.word} ${name.join("/")}`, route: known.route } : { label: usedBy, route: { view: "settings", section: "secrets" } };
}

/** Its title: what it is to its owner ("Provider openrouter · key"), or its path when nothing uses it. */
export function title(s: SecretInfo): string {
  const usedBy = s.usedBy ?? [];
  if (!usedBy.length) return s.path;
  const slot = s.path.split("/").at(-1) ?? "";
  const what = slot === "apiKey" ? "key" : slot;
  return `${usedBy.map((u) => owner(u).label).join(", ")} · ${what}`;
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

/** Whether its value can be replaced here: one in handler's store whose owner does not set it itself
 *  (an account's token is its login, an app's secret restarts the app). */
export function replaceable(s: SecretInfo): boolean {
  return (s.source ?? "secret") === "secret" && !s.path.startsWith("accounts/") && !s.path.startsWith("apps/");
}

/** A stored value nothing uses: the only kind removed from here. */
export function removable(s: SecretInfo): boolean {
  return (s.source ?? "secret") === "secret" && !s.usedBy?.length && s.createdAt != null;
}

export const ownerHref = (usedBy: string) => href(owner(usedBy).route);
