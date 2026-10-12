// Who uses a skill of the library (D.17), in words: the projects that give it to all their agents,
// then the agents that picked it.
import type { Project, SkillInfo } from "./contracts.gen";

/** "all agents of shop, blog · picked by blog/review, ad-hoc/notes"; "" when no agent uses it. */
export function who(skill: Pick<SkillInfo, "projects" | "usedBy">, list: Project[]): string {
  const given = (skill.projects ?? []).map((id) => list.find((p) => p.id === id)?.name ?? id);
  const picked = (skill.usedBy ?? []).map((u) => u.replace(/^agents\//, ""));
  return [given.length ? `all agents of ${given.join(", ")}` : "", picked.length ? `picked by ${picked.join(", ")}` : ""]
    .filter(Boolean)
    .join(" · ");
}
