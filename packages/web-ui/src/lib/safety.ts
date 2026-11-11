// What an agent may do, as the UI says it (contract D.8): its network, one of three modes shown
// as a meter (more bars, safer: No network 3, Only these sites 2, Any site 1, amber), and the
// switches that widen its sandbox beyond what a new agent starts with, each its own amber chip.
// No named preset: a new agent starts with only the sites it needs, never asking (the daemon's
// defaults for a setting left out, rule save.new-agents-start-with-only-the-sites-they-need).
import type { AccountInfo, AddonInfo, AddonUse, Agent, AgentRequest, ProviderInfo, RequiredHost } from "./contracts.gen";
import type { ModelAccess } from "./access";

export type NetworkMode = Agent["network"];

/** How an agent is contained: its own, never inherited (D.8). */
export type Sandbox = Required<Pick<AgentRequest, "network" | "egress" | "confinement" | "permissions">>;

/** What a new agent starts with: only the sites it needs (filtered, enforced), a strict sandbox,
 *  never asking. */
export const NEW_AGENT: Sandbox = { network: "filtered", egress: "enforce", confinement: "strict", permissions: "bypass" };

export const NETWORK_MODES: { mode: NetworkMode; label: string; bars: 1 | 2 | 3 }[] = [
  { mode: "none", label: "No network", bars: 3 },
  { mode: "filtered", label: "Only these sites", bars: 2 },
  { mode: "open", label: "Any site", bars: 1 },
];

/** The meter's bars: more is safer. */
export function barsOf(network: NetworkMode | null | undefined): 1 | 2 | 3 {
  return network === "none" ? 3 : network === "open" ? 1 : 2;
}

/** The network in a word or two, for a chip: "No network", "4 sites", "Any site". */
export function networkWords(network: NetworkMode | null | undefined, sites: number): string {
  if (network === "none") return "No network";
  if (network === "open") return "Any site";
  return `${sites} site${sites === 1 ? "" : "s"}`;
}

type Widening = { label: string; why: string };

/** What weakens its sandbox beyond what a new agent starts with, but its network's mode (the
 *  meter says that): each is its own amber chip. Never a default. */
export function widenings(
  a: { network?: string | null; egress?: string | null; confinement?: string | null; display?: boolean | null },
  caches?: string | null,
): Widening[] {
  return [
    a.network === "filtered" && a.egress === "log-only" ? { label: "Learning the sites", why: "Every site is let through and logged" } : null,
    a.confinement === "nested" ? { label: "Runs containers", why: "Podman or Docker inside its sandbox: a weaker confinement" } : null,
    a.confinement === "privileged" ? { label: "Privileged", why: "About as safe as no sandbox" } : null,
    a.display ? { label: "Windows on my screen", why: "It opens windows on your screen and reads what you copy" } : null,
    caches === "global" ? { label: "Shared caches", why: "Its toolchain caches are shared with your other projects" } : null,
  ].filter((w) => w !== null);
}

/** In one line: "4 sites · Runs containers", "Any site". */
export function safetyLine(a: Parameters<typeof widenings>[0] & { network?: NetworkMode | null }, sites: number): string {
  return [networkWords(a.network, sites), ...widenings(a).map((w) => w.label)].join(" · ");
}

/** A site an agent needs for what it uses, and why ("its model", "the github tool"). */
export type NeededSite = { host: string; why: string };

/** The host of an endpoint, as the filter matches it. */
function hostOf(url: string): string | null {
  try {
    return new URL(url).hostname || null;
  } catch {
    return null;
  }
}

/** handlerd's reason ("account claude-perso", "provider mistral", "the github tool: acme-bot",
 *  "MCP server github"), in the person's words: "its model", "the github tool". */
export function whyOf(by: string): string {
  const tool = by.match(/^the ([^:]+) tool\b/)?.[1] ?? by.match(/^MCP server ([^:]+)/)?.[1];
  return tool ? `the ${tool} tool` : "its model";
}

/** The sites an agent needs for what it uses, each once: its model's (the account's login hosts,
 *  the provider's endpoints) and its tools'. A saved agent unchanged has handlerd's own list
 *  (`saved`, D.2's required hosts, also its harness's own servers); one being changed, what its
 *  model and tools say they reach. */
export function neededSites(
  model: ModelAccess,
  addons: AddonUse[],
  infos: { accounts: AccountInfo[]; providers: ProviderInfo[]; addons: AddonInfo[] },
  saved?: RequiredHost[],
): NeededSite[] {
  const found: NeededSite[] = [];
  const add = (host: string | null, why: string) => {
    if (host && !found.some((s) => s.host === host)) found.push({ host, why });
  };
  if (saved) {
    for (const r of saved) add(r.host, whyOf(r.by));
    return found;
  }
  if (model.account) for (const h of infos.accounts.find((a) => a.name === model.account)?.hosts ?? []) add(h, "its model");
  if (model.provider) for (const url of Object.values(infos.providers.find((p) => p.name === model.provider)?.endpoints ?? {})) add(hostOf(url), "its model");
  for (const use of addons) for (const h of infos.addons.find((a) => a.name === use.addon)?.egress ?? []) add(h, `the ${use.addon} tool`);
  return found;
}
