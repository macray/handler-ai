// Who uses a skill of the library (D.17), in words: the projects that give it to all their agents,
// then the agents that picked it.
import type { Project, SkillInfo, SkillScan } from "./contracts.gen";

/** What handler's scan found in a skill's files, each kind counted ("2 scripts that run"); none: []. */
export function scanFindings(scan: SkillScan): string[] {
  const n = (count: number, one: string, many: string) => (count === 1 ? `1 ${one}` : `${count} ${many}`);
  return [
    scan.executables?.length && n(scan.executables.length, "script that runs", "scripts that run"),
    scan.binaries?.length && n(scan.binaries.length, "binary file", "binary files"),
    scan.hosts?.length && n(new Set(scan.hosts.map((h) => h.text)).size, "host it names", "hosts it names"),
    scan.hiddenText?.length && n(scan.hiddenText.length, "line with hidden characters", "lines with hidden characters"),
    scan.blobs?.length && n(scan.blobs.length, "long encoded run", "long encoded runs"),
  ].filter((x): x is string => !!x);
}

/** "all agents of shop, blog · picked by blog/review, ad-hoc/notes"; "" when no agent uses it. */
export function who(skill: Pick<SkillInfo, "projects" | "usedBy">, list: Project[]): string {
  const given = (skill.projects ?? []).map((id) => list.find((p) => p.id === id)?.name ?? id);
  const picked = (skill.usedBy ?? []).map((u) => u.replace(/^agents\//, ""));
  return [given.length ? `all agents of ${given.join(", ")}` : "", picked.length ? `picked by ${picked.join(", ")}` : ""]
    .filter(Boolean)
    .join(" · ");
}
