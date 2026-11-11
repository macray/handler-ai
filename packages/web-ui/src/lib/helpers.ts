// Handler's helpers (D.18: the agents given for its needs), as the UI says them: by the feature
// each serves (its name and icon, where you meet it), and what it can do. Two kinds of facts:
// what its feature fixes, shown locked ("set by Plans") because Handler holds it there (the plan
// builder's rules plan.builder-has-no-secret and plan.builder-reads-the-project-only, a chat
// helper working on a copy with no folder of its own, a reviewed skill mounted read-only, what a
// feature gives it); and the agent's own settings (its network, its switches), which are the
// agent's to change like any agent's. Apart from what it can do, what it works with: its skills
// (its definition's, and those its tools bring) and its tools, as the agent form lists them; a
// skill makes it better at something, never lets it reach more.
import type { AddonInfo, Agent, AgentDefinition } from "./contracts.gen";
import { networkWords, widenings, type NetworkMode } from "./safety";

export type HelperIcon = "plans" | "ask" | "improve" | "apps" | "skill-write" | "skill-review";

export type Feature = {
  need: string;
  feature: string; // the feature's name, as you meet it
  where: string; // where you meet it
  icon: HelperIcon;
  verb: string; // what the helper does there, in the feature's line: "Written by"
};

// in the order Settings → Helpers lists them
export const FEATURES: Feature[] = [
  { need: "plan-builder", feature: "Plans", where: "in each project", icon: "plans", verb: "Written by" },
  { need: "ask-router", feature: "Ask", where: "Chat → Ask", icon: "ask", verb: "Picked by" },
  { need: "prompt-writer", feature: "Improve until they pass", where: "a job's checks", icon: "improve", verb: "Rewritten by" },
  { need: "app-creator", feature: "Make your own apps", where: "Library → Apps", icon: "apps", verb: "Built by" },
  { need: "skill-creator", feature: "Write skills with an agent", where: "Library → Skills", icon: "skill-write", verb: "Written by" },
  { need: "skill-review", feature: "Review skills", where: "Library → Skills", icon: "skill-review", verb: "Reviewed by" },
];

export function featureOf(need: string): Feature {
  return FEATURES.find((f) => f.need === need) ?? { need, feature: need, where: "", icon: "ask", verb: "By" };
}

// the helpers' names, as their definitions give them (before the list is loaded)
const NAMES: Record<string, string> = {
  "plan-builder": "Plan builder",
  "ask-router": "Ask router",
  "prompt-writer": "Prompt writer",
  "app-creator": "App creator",
  "skill-creator": "Skill creator",
  "skill-review": "Skill reviewer",
};

export function needLabel(need: string): string {
  return NAMES[need] ?? need;
}

/** One fact of what a helper can do. `locked`: its feature fixes it ("set by Plans"). */
export type Fact = { key: string; label: string; text: string; chip?: string; locked: boolean; warn?: boolean; network?: NetworkMode };

// what each feature fixes, by Handler's own code (option A of stage 5's model impact note)
const LOCKED: Record<string, Omit<Fact, "locked">[]> = {
  "plan-builder": [
    { key: "project", label: "The project", text: "reads it, read-only", chip: "reads the project, read-only" },
    { key: "writes", label: "Writes", text: "a draft Handler keeps, never your folder", chip: "writes a draft Handler keeps" },
    { key: "network", label: "Network", text: "only its model's sites", network: "filtered" },
    { key: "tools", label: "Tools, secrets", text: "none", chip: "no tools, no secrets" },
  ],
  "ask-router": [
    { key: "given", label: "Is given", text: "what you typed, and what your apps can do", chip: "sees what you typed and what your apps can do" },
    { key: "answers", label: "Answers", text: "one pick per question, which Ask runs at once", chip: "one pick per question" },
  ],
  "prompt-writer": [
    { key: "given", label: "Is given", text: "a job's instructions, and what its checks say", chip: "sees a job's instructions and its checks" },
    { key: "writes", label: "Writes", text: "new instructions, kept only when you keep them", chip: "writes instructions you keep or not" },
  ],
  "app-creator": [{ key: "writes", label: "Works on", text: "a draft of the app's code Handler keeps, never your folders", chip: "works on a draft Handler keeps" }],
  "skill-creator": [{ key: "writes", label: "Works on", text: "a copy of the skill, saved to your library when you say so", chip: "works on a copy of the skill" }],
  "skill-review": [
    { key: "given", label: "Reads", text: "the skill, read-only", chip: "reads the skill, read-only" },
    { key: "answers", label: "Answers", text: "what it found: it never allows or blocks anything", chip: "says what it found, never blocks" },
  ],
};

type Settings = Pick<AgentDefinition, "network" | "egress" | "allow" | "confinement" | "display" | "addons" | "skills" | "modelAlone">;

/** An agent's settings as a definition says them (its tools by name). */
export function settingsOf(a: Agent): Settings {
  return { ...a, egress: a.egress ?? "enforce", addons: (a.addons ?? []).map((u) => u.addon) };
}

/** What a helper can do: what its feature fixes, locked, then its own settings (`of`: its agent,
 *  or the definition it is set up from) that its feature does not fix. */
export function factsOf(need: string, of: Settings): Fact[] {
  const locked = (LOCKED[need] ?? []).map((f): Fact => ({ ...f, locked: true }));
  const fixed = new Set(locked.map((f) => f.key));
  const own: Fact[] = [];
  if (of.modelAlone) {
    own.push({ key: "alone", label: "The model alone", text: "one call: no files, no tools, no sandbox", locked: false });
  } else {
    if (!fixed.has("network")) {
      const sites = (of.allow ?? []).length;
      const text =
        of.network === "filtered" ? `only its model's sites${of.addons?.length ? " and its tools'" : ""}${sites ? `, and ${networkWords("filtered", sites)} of yours` : ""}` : networkWords(of.network, 0);
      own.push({ key: "network", label: "Network", text, locked: false, network: of.network, warn: of.network === "open" });
    }
    for (const w of widenings(of)) own.push({ key: w.label, label: w.label, text: w.why, locked: false, warn: true });
  }
  return [...locked, ...own];
}

/** One line of what a helper works with: its skills, or its tools. */
export type Use = { key: "skills" | "tools"; label: string; text: string };

/** What a helper works with (`tools`: the installed tools, for the skills each brings): its
 *  skills, those of its tools named after theirs, then its tools unless its feature fixes none.
 *  Nothing for the model alone: its one fact says it has neither. */
export function usesOf(need: string, of: Settings, tools: AddonInfo[]): Use[] {
  if (of.modelAlone) return [];
  const names = of.addons ?? [];
  const brought = names.flatMap((t) => (tools.find((i) => i.name === t)?.skills ?? []).map((s) => `${s} (from the ${t} tool)`));
  const skills = [...(of.skills ?? []), ...brought];
  const uses: Use[] = [{ key: "skills", label: "Skills", text: skills.length ? skills.join(", ") : "none" }];
  if (!(LOCKED[need] ?? []).some((f) => f.key === "tools")) uses.push({ key: "tools", label: "Tools", text: names.length ? names.join(", ") : "none" });
  return uses;
}
