// A SKILL.md as the skill editor shows it (D.17): its `name` and `description` as fields, the
// rest of its frontmatter kept as written (`license`, `allowed-tools`, `metadata`…: shown and
// edited as text), and its instructions. handlerd checks the file when it is saved.

export type SkillDoc = { name: string; description: string; other: string; body: string };

const FRONTMATTER = /^---\r?\n([\s\S]*?)\r?\n?---[ \t]*(?:\r?\n|$)/;
const KEY = /^([A-Za-z0-9_-]+):(.*)$/;

/** Its top-level entries: each key with the lines that continue it (indented, or blank). */
function entries(front: string): { key: string | null; lines: string[] }[] {
  const found: { key: string | null; lines: string[] }[] = [];
  for (const line of front.split(/\r?\n/)) {
    const key = KEY.exec(line)?.[1];
    if (key !== undefined || !found.length) found.push({ key: key ?? null, lines: [line] });
    else found[found.length - 1]?.lines.push(line);
  }
  return found;
}

/** A scalar's value: plain, quoted, or a block (`|`, `>`). */
function scalar(lines: string[]): string {
  const first = (KEY.exec(lines[0] ?? "")?.[2] ?? "").trim();
  const rest = lines.slice(1).map((l) => l.trim());
  if (/^[|>][+-]?$/.test(first)) return rest.join(first.startsWith("|") ? "\n" : " ").trim();
  if (first.startsWith('"')) {
    try {
      return JSON.parse([first, ...rest].join(" ")) as string;
    } catch {
      return first.slice(1, -1);
    }
  }
  if (first.startsWith("'")) return [first, ...rest].join(" ").slice(1, -1).replaceAll("''", "'");
  return [first, ...rest].filter(Boolean).join(" ");
}

export function readSkill(text: string): SkillDoc {
  const match = FRONTMATTER.exec(text);
  if (!match) return { name: "", description: "", other: "", body: text };
  let name = "";
  let description = "";
  const other: string[] = [];
  for (const entry of entries(match[1] ?? "")) {
    if (entry.key === "name") name = scalar(entry.lines);
    else if (entry.key === "description") description = scalar(entry.lines);
    else other.push(...entry.lines);
  }
  return { name, description, other: other.join("\n").trim(), body: text.slice(match[0].length).replace(/^\s*\n/, "") };
}

/** A value YAML reads back as written: plain when it can be, else double-quoted (JSON's escapes). */
function yamlString(value: string): string {
  const plain = /^[^\s'"&*!|>%@`#{}[\],?:-][^\n]*$/.test(value) && !/: | #|\s$/.test(value);
  return plain ? value : JSON.stringify(value);
}

export function writeSkill(doc: SkillDoc): string {
  const other = doc.other.trim();
  const front = [`name: ${doc.name.trim()}`, `description: ${yamlString(doc.description.trim())}`, ...(other ? [other] : [])];
  return `---\n${front.join("\n")}\n---\n\n${doc.body.replace(/^\s*\n/, "")}`;
}

export const NEW_SKILL: SkillDoc = {
  name: "",
  description: "",
  other: "",
  body: "# What it is for\n\nThe steps the agent follows. Scripts it runs go in scripts/, longer documents in references/.\n",
};
