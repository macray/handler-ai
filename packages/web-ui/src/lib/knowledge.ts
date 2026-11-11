// Knowledge (D.5): what the Knowledge page needs to show a folder of markdown notes.
// Pure string work, no DOM: unit-tested in tests/logic.test.ts.

import { FRONTMATTER } from "./skillmd";

export interface Frontmatter {
  meta: [string, string][]; // top-level "key: value" lines, in order
  body: string;
}

/** Split a leading `---` frontmatter block from a note. Only simple `key: value` lines are
 *  kept for display (lists and nested values are shown as written); no YAML parser needed. */
export function splitFrontmatter(text: string): Frontmatter {
  const match = FRONTMATTER.exec(text);
  if (!match) return { meta: [], body: text };
  const meta: [string, string][] = [];
  for (const line of (match[1] ?? "").split(/\r?\n/)) {
    const kv = /^([A-Za-z0-9_-]+):\s*(.*)$/.exec(line);
    if (kv?.[1] !== undefined) meta.push([kv[1], (kv[2] ?? "").replace(/^(["'])(.*)\1$/, "$2")]);
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
