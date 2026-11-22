// Knowledge (D.5): what the Knowledge page needs to show a folder of markdown notes.
// Pure string work, no DOM: unit-tested in tests/logic.test.ts.

import type { NotesCommit, NotesFileChange } from "./contracts.gen";
import { FRONTMATTER } from "./skillmd";

export interface Frontmatter {
  meta: [string, string][]; // top-level keys, in order: a value, or its indented lines as written
  body: string;
}

/** Split a leading `---` frontmatter block from a note, for display: each top-level key with its
 *  value, a list or nested value as its indented lines (trimmed, one per line); no YAML parser. */
export function splitFrontmatter(text: string): Frontmatter {
  const match = FRONTMATTER.exec(text);
  if (!match) return { meta: [], body: text };
  const meta: [string, string][] = [];
  for (const line of (match[1] ?? "").split(/\r?\n/)) {
    const kv = /^([A-Za-z0-9_-]+):\s*(.*)$/.exec(line);
    const last = meta.at(-1);
    if (kv?.[1] !== undefined) meta.push([kv[1], (kv[2] ?? "").replace(/^(["'])(.*)\1$/, "$2")]);
    else if (last && /^\s/.test(line) && line.trim()) last[1] = last[1] ? `${last[1]}\n${line.trim()}` : line.trim();
  }
  return { meta, body: text.slice(match[0].length).replace(/^\s*\n/, "") };
}

/** The folder containing a path relative to the root ("." for the root). */
export function dirname(path: string): string {
  const i = path.lastIndexOf("/");
  return i < 0 ? "." : path.slice(0, i);
}

export function join(folder: string, name: string): string {
  return folder === "." ? name : `${folder}/${name}`;
}

export type KnowledgeTarget = { folder: string } | { note: string };

/** Where a link found in a file of `from` (a folder, relative to the root) leads inside the
 *  root: a folder (links to `x/` or `x/_index.md`) or a note (`*.md`). null for anything else:
 *  external links, anchors, links leaving the root, other files. */
export function resolveLink(from: string, href: string): KnowledgeTarget | null {
  if (!href || /^[a-z][a-z0-9+.-]*:/i.test(href) || href.startsWith("#") || href.startsWith("/")) {
    return null;
  }
  const clean = href.replace(/[?#].*$/, "");
  const parts = from === "." ? [] : from.split("/");
  for (const raw of clean.split("/")) {
    let part: string;
    try {
      part = decodeURIComponent(raw);
    } catch {
      return null;
    }
    if (part === "" || part === ".") continue;
    if (part === "..") {
      if (!parts.length) return null; // leaves the root
      parts.pop();
    } else parts.push(part);
  }
  const path = parts.join("/") || ".";
  if (path === "_index.md" || path.endsWith("/_index.md")) return { folder: dirname(path) };
  if (path.endsWith(".md")) return { note: path };
  if (clean.endsWith("/") || !/\.[A-Za-z0-9]+$/.test(path)) return { folder: path };
  return null;
}

/** One entry of a folder's history (D.5), titled by who made it: the agents and apps given the
 *  folder read-write that ran then ("CV assistant (app)", "website or Keeper"), else you or
 *  another program; its time is shown beside it. */
export function changeTitle(c: NotesCommit): string {
  switch (c.kind) {
    case "first":
      return `History started · ${c.fileCount} file${c.fileCount === 1 ? "" : "s"} kept as ${c.fileCount === 1 ? "it was" : "they were"}`;
    case "while-off":
      return "Changed while Handler was not running · by you or another program";
    case "undo":
      return "Undo (by you)";
    default: {
      const who = c.couldWrite ?? [];
      return who.length ? who.map((w) => (w.app ? `${w.name} (app)` : w.name)).join(" or ") : "You or another program";
    }
  }
}

export type DiffLine = { kind: "add" | "del" | "same" | "gap"; sign: string; text: string };

/** A unified diff's lines to show: the sign in a column of its own (`+`, `−`), apart from the
 *  text (whose own `-`, a markdown list's, stays in the text); a gap between two hunks, no hunk
 *  header. */
export function diffLines(diff: string): DiffLine[] {
  const out: DiffLine[] = [];
  for (const line of diff.replace(/\n$/, "").split("\n")) {
    if (line.startsWith("@@")) {
      if (out.length) out.push({ kind: "gap", sign: "", text: "…" });
    } else if (line.startsWith("+")) out.push({ kind: "add", sign: "+", text: line.slice(1) });
    else if (line.startsWith("-")) out.push({ kind: "del", sign: "−", text: line.slice(1) });
    else if (!line.startsWith("\\")) out.push({ kind: "same", sign: "", text: line.slice(1) });
  }
  return out;
}

const lines = (n: number): string => `${n} line${n === 1 ? "" : "s"}`;

/** A file's change in words ("added 1 line", "new file, 1 line", "removed 1 line"), from what
 *  handlerd counted; `under`, the heading all its changed lines are under, when they share one.
 *  An undo's files are "put back" (or "removed", one it had added). */
export function fileChange(f: NotesFileChange, undo = false): { says: string; under: string | null } {
  if (undo) return { says: f.change === "deleted" ? "removed" : "put back", under: null };
  const plain = f.change === "added" ? "new file" : f.change === "deleted" ? "file removed" : "changed";
  if (f.link) return { says: `${plain}, a link${"linkTarget" in f && f.linkTarget ? ` to ${f.linkTarget}` : ""}`, under: null };
  const adds = f.added;
  const dels = f.removed ?? 0;
  if (adds == null) return { says: plain, under: null };
  if (f.change === "added") return { says: `new file, ${lines(adds)}`, under: null };
  if (f.change === "deleted") return { says: `file removed, ${lines(dels)}`, under: null };
  const says =
    adds && dels ? (adds === dels ? `changed ${lines(adds)}` : `added ${lines(adds)}, removed ${dels}`) : adds ? `added ${lines(adds)}` : dels ? `removed ${lines(dels)}` : "changed";
  return { says, under: f.under ?? null };
}
