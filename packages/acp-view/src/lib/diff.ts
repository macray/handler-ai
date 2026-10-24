// A file's change as rows to show: one line each (added, removed or the same, with its line
// number), a changed line's words marked against the line it replaces, long unchanged runs folded
// to `context` lines around each change.
import { diffLines, diffWordsWithSpace } from "diff";

export type Segment = { text: string; changed: boolean };
export type Line = { kind: "add" | "del" | "same"; n: number; text: string; words?: Segment[] };
export type Row = Line | { kind: "fold"; id: number; lines: Line[] };

function split(value: string): string[] {
  const lines = value.split("\n");
  if (lines.at(-1) === "") lines.pop();
  return lines;
}

/** The words of `after` (or of `before`) that differ; null when most of the line changed. */
function words(before: string, after: string, side: "add" | "del"): Segment[] | null {
  const parts = diffWordsWithSpace(before, after);
  const kept = parts.filter((p) => !p.added && !p.removed).reduce((n, p) => n + p.value.length, 0);
  if (kept < Math.max(before.length, after.length) * 0.4) return null;
  return parts
    .filter((p) => (side === "add" ? !p.removed : !p.added))
    .map((p) => ({ text: p.value, changed: Boolean(p.added || p.removed) }));
}

export function lines(oldText: string | null | undefined, newText: string): Line[] {
  const out: Line[] = [];
  let oldN = 0;
  let newN = 0;
  const parts = diffLines(oldText ?? "", newText);
  for (let i = 0; i < parts.length; i++) {
    const part = parts[i]!;
    if (part.removed && parts[i + 1]?.added) {
      // a replaced block: its lines paired, to mark their words
      const dels = split(part.value);
      const adds = split(parts[i + 1]!.value);
      dels.forEach((text, j) => {
        const w = j < adds.length ? words(text, adds[j]!, "del") : null;
        out.push({ kind: "del", n: ++oldN, text, ...(w ? { words: w } : {}) });
      });
      adds.forEach((text, j) => {
        const w = j < dels.length ? words(dels[j]!, text, "add") : null;
        out.push({ kind: "add", n: ++newN, text, ...(w ? { words: w } : {}) });
      });
      i++;
      continue;
    }
    for (const text of split(part.value)) {
      if (part.added) out.push({ kind: "add", n: ++newN, text });
      else if (part.removed) out.push({ kind: "del", n: ++oldN, text });
      else {
        oldN++;
        out.push({ kind: "same", n: ++newN, text });
      }
    }
  }
  return out;
}

/** The rows: unchanged runs longer than needed folded, `context` lines kept next to a change. */
export function rows(all: Line[], context = 3): Row[] {
  const out: Row[] = [];
  let run: Line[] = [];
  let id = 0;
  const flush = (last: boolean) => {
    const first = out.length === 0;
    const head = first ? 0 : context; // after a change
    const tail = last ? 0 : context; // before the next one
    if (run.length > head + tail + 1) {
      out.push(...run.slice(0, head));
      out.push({ kind: "fold", id: id++, lines: run.slice(head, run.length - tail) });
      out.push(...run.slice(run.length - tail));
    } else out.push(...run);
    run = [];
  };
  for (const line of all) {
    if (line.kind === "same") run.push(line);
    else {
      flush(false);
      out.push(line);
    }
  }
  flush(true);
  return out;
}

export function counts(all: Line[]): { added: number; removed: number } {
  return { added: all.filter((l) => l.kind === "add").length, removed: all.filter((l) => l.kind === "del").length };
}
