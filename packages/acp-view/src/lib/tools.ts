// How a tool call reads in one line: its verb and title, paths relative to the session's folder,
// and what it gave back (the line under a collapsed step).
import type { ToolCallContent } from "@agentclientprotocol/sdk";
import { diffLines } from "diff";
import { blockText, type Entry, type ToolEntry } from "./session.svelte";

const VERBS: Record<string, string> = {
  read: "Read", edit: "Edit", delete: "Delete", move: "Move", search: "Search", execute: "Bash", think: "Think", fetch: "Fetch",
};

/** A path under `root` relative to it ("src/a.py"); others as they are. */
export function relative(path: string, root?: string | null): string {
  if (!root) return path;
  const base = root.endsWith("/") ? root : `${root}/`;
  return path.startsWith(base) ? path.slice(base.length) : path;
}

/** The step's verb and the rest of its title. A title that starts with its own verb ("Write
 *  notes.md", "Edit src/a.py") keeps it rather than getting a second one. */
export function headline(tool: ToolEntry, root?: string | null): { verb: string; title: string } {
  const title = root ? tool.title.replaceAll(root.endsWith("/") ? root : `${root}/`, "") : tool.title;
  const own = /^([A-Z][a-z]+)\s+(.*)$/s.exec(title);
  if (own) return { verb: own[1]!, title: own[2]! };
  return { verb: VERBS[tool.toolKind ?? ""] ?? "Tool", title };
}

function lines(text: string): string[] {
  return text
    .split("\n")
    .map((l) => l.trim())
    .filter((l) => l && !l.startsWith("```"));
}

function texts(content: ToolCallContent[]): string[] {
  return content.flatMap((c) => (c.type === "content" && c.content.type === "text" ? [blockText(c.content)] : []));
}

/** What the step gave back, in one line, or null when there is nothing worth saying. */
export function summary(tool: ToolEntry): string | null {
  const out = texts(tool.content).flatMap(lines);
  if (tool.status === "failed") return out[0] ?? null;
  let added = 0;
  let removed = 0;
  let diffs = 0;
  for (const c of tool.content) {
    if (c.type !== "diff") continue;
    diffs++;
    for (const part of diffLines(c.oldText ?? "", c.newText)) {
      if (part.added) added += part.count ?? 0;
      else if (part.removed) removed += part.count ?? 0;
    }
  }
  if (diffs) return `+${added} −${removed}`;
  if (tool.status !== "completed") return null;
  if (tool.toolKind === "read") return out.length ? `${out.length} line${out.length === 1 ? "" : "s"}` : null;
  if (tool.toolKind === "execute" || tool.toolKind === "search") return out.at(-1) ?? null;
  return null;
}

/** "12s", "1m05s", "2h03m". */
export function duration(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m${String(s % 60).padStart(2, "0")}s`;
  return `${Math.floor(m / 60)}h${String(m % 60).padStart(2, "0")}m`;
}

/** The step the agent is on ("Bash uv run pytest"), or null between steps. */
export function activity(entries: Entry[], root?: string | null): string | null {
  for (let i = entries.length - 1; i >= 0; i--) {
    const e = entries[i]!;
    if (e.kind === "user") return null;
    if (e.kind === "tool" && (e.status === "in_progress" || e.status === "pending")) {
      const { verb, title } = headline(e, root);
      return `${verb} ${title}`;
    }
  }
  return null;
}

/** What a turn did, said under it: "1m12s · 4 steps · 1 file changed"; null when it took no step
 *  and its time is not known. `entries` are the turn's own, after its prompt. */
export function turnSummary(entries: Entry[], ms?: number): string | null {
  const tools = entries.filter((e): e is ToolEntry => e.kind === "tool");
  const files = new Set(
    tools.flatMap((t) => [
      ...t.content.flatMap((c) => (c.type === "diff" ? [c.path] : [])),
      ...(t.toolKind === "edit" || t.toolKind === "delete" || t.toolKind === "move" ? t.locations.map((l) => l.path) : []),
    ]),
  );
  const parts = [
    ms === undefined ? null : duration(ms),
    tools.length ? `${tools.length} step${tools.length === 1 ? "" : "s"}` : null,
    files.size ? `${files.size} file${files.size === 1 ? "" : "s"} changed` : null,
  ].filter(Boolean);
  return parts.length && tools.length ? parts.join(" · ") : null;
}
