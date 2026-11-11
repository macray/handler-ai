// Sources (D.26): git repositories offering apps, agents and addons. Each page lists what they
// offer of its own kind (the Apps page, the addon installer, a project's agents), saying where
// each comes from: "from Handler" for the official source, else the source's name. Discover
// lists them all, by kind; an item's page says what it does before it is installed.
import { api } from "./api";
import type { AddonInfo, Source, SourceItem, SourceItemDetail } from "./contracts.gen";
import { mayDo, toolNeeds, weakens } from "./setup";
import { navigate } from "./router.svelte";

/** Where something comes from, as its card says it. */
export function fromWords(source: Source): string {
  return source.official ? "from Handler" : `from ${source.name ?? source.id}`;
}

/** The source of an app (`App.fromSource`) said the same way, or null for one of no source. */
export function fromSourceWords(id: string | null | undefined, sources: Source[]): string | null {
  if (!id) return null;
  const found = sources.find((s) => s.id === id);
  return found ? fromWords(found) : id === "official" ? "from Handler" : `from ${id}`;
}

/** What the sources offer of one kind, readable ones only, each with its source. */
export function offered(sources: Source[], kind: SourceItem["kind"]): { source: Source; item: SourceItem }[] {
  return sources.flatMap((source) => (source.items ?? []).filter((i) => i.kind === kind && !i.error).map((item) => ({ source, item })));
}

export type KindPath = "apps" | "agents" | "addons";
/** What Discover offers: a source's system packages are installed with the addons needing them
 *  (B.7), never on a card or a page of their own. */
export type OfferedKind = Exclude<SourceItem["kind"], "system-package">;
export const KIND_PATH: Record<OfferedKind, KindPath> = { app: "apps", agents: "agents", addon: "addons" };

/** The page of one item, in Discover. */
export const itemRoute = (source: Source | string, item: SourceItem) =>
  ({ view: "discover-item", source: typeof source === "string" ? source : source.id, kind: KIND_PATH[item.kind as OfferedKind], name: item.name }) as const;

/** Its button's words: what pressing it does. */
export function actionWords(item: SourceItem): string | null {
  if (item.update) return item.kind === "addon" ? "See the update" : "Get it";
  if (item.kind === "agents") return "Set up…";
  return item.installed ? null : "Install";
}

/** Installing it goes to its kind's own page (D.26): an app's code taken, then its install page
 *  (its own page for the next version of one you have); agents read, then their set-up page (where
 *  they go is asked there, `project` chosen if given); a tool's preview, in Library → Tools → Get
 *  more. */
export async function takeItem(source: string, item: SourceItem, project?: string): Promise<void> {
  if (item.kind === "app") {
    const { app, added } = await api.appFromSource(source, item.name);
    navigate(added ? { view: "install-app", name: app.name } : { view: "apps", app: app.name });
  } else if (item.kind === "agents") {
    const read = await api.agentsFromSource(source, item.name);
    navigate({ view: "setup", file: read.name, ...(project ? { project } : {}) });
  } else {
    navigate({ view: "library", shelf: "tools", more: true, install: `source:${source}/${item.name}` });
  }
}

/** What an item may do and what it needs from you, in sentences, from its kind's manifest:
 *  its page says them before anything is installed (`addons`: the tools installed, so that its
 *  agents' tools are asked only for what is left to do). */
export function itemFacts(d: SourceItemDetail, addons: AddonInfo[]): { mayDo: { text: string; weakens?: boolean }[]; needs: string[] } {
  if (d.app) {
    const n = d.app.needs ?? {};
    const files = Object.values(n.files ?? {});
    return {
      mayDo: [
        { text: "keep its own data, on this computer" },
        ...files.map((f) => ({ text: `${f.mode === "ro" ? "read" : "read and write"} a folder you choose: ${f.description ?? "a folder"}` })),
        ...(n.egress ?? []).map((h) => ({ text: `reach ${h}`, weakens: true })),
        ...(n.notify ? [{ text: "notify you, here and on your phone" }] : []),
        ...Object.values(n.agents ?? {}).map((a) => ({ text: `run an agent: ${a.description ?? "its agent"}` })),
      ],
      needs: [
        ...files.map((f) => `a folder: ${f.description ?? "one you choose"}`),
        ...Object.values(n.agents ?? {}).map((a) => `an agent, on a model you choose: ${a.description ?? ""}`.replace(/: $/, "")),
        ...(n.secrets ?? []).map((s) => `a secret: ${s}`),
      ],
    };
  }
  if (d.agents) {
    const several = d.agents.agents.length > 1;
    return {
      mayDo: d.agents.agents.flatMap((a) =>
        mayDo(a.definition, "the project's folder").map((t) => ({
          text: several ? `${a.definition.agentName}: ${t}` : t,
          weakens: weakens(t),
        })),
      ),
      needs: [
        "a project to set them up in",
        several ? "a model for each agent" : "a model",
        ...toolNeeds([...new Set(d.agents.agents.flatMap((a) => a.definition.addons ?? []))], addons),
        ...[...new Set(d.agents.agents.flatMap((a) => a.definition.knowledge ?? []))].map((k) => `a notes folder: ${k}`),
      ],
    };
  }
  const a = d.addon;
  if (!a) return { mayDo: [], needs: [] };
  return {
    mayDo: [
      ...(a.egress ?? []).map((h) => ({ text: `let the agents given it reach ${h}`, weakens: true })),
      ...(a.image ? [{ text: `build its image on this computer (its Containerfile runs code)`, weakens: true }] : []),
      ...(a.commands?.length ? [{ text: `give its agents ${a.commands.join(", ")}` }] : []),
      ...(a.mcp?.length ? [{ text: "give every session its MCP server" }] : []),
      ...(a.skills?.length ? [{ text: `teach them: ${a.skills.join(", ")}` }] : []),
    ],
    needs: [...(a.settings ?? []).map((s) => `a setting: ${s.name}${s.required ? "" : " (optional)"}`), ...(a.secretSlots ?? []).map((s) => `a secret: ${s.name}`)],
  };
}
