// Which build makes what a session lacks (F.1 `missingImage`: a build target, D.4): a build of
// that target, or the toolbox's, which rebuilds the agent programs and addons already built.
import type { Build } from "./contracts.gen";

const ADDON = "addon:";

export function makes(build: Build, target: string): boolean {
  if (build.target === target) return true;
  if (build.target !== "toolbox") return false;
  if (target.startsWith(ADDON)) return (build.addons ?? []).includes(target.slice(ADDON.length));
  return (build.harnesses ?? []).includes(target);
}

/** The build to follow for `target` (`list` newest first): one running that makes it, else one
 *  that made it after `since` (the start refused): what was just built is not built again. */
export function following(list: Build[], target: string, since: string): Build | null {
  const making = list.filter((b) => makes(b, target));
  const after = (b: Build) => b.state === "succeeded" && Date.parse(b.endedAt ?? "") > Date.parse(since);
  return making.find((b) => b.state === "running") ?? making.find(after) ?? null;
}

/** What a running build is at, in words, from its `stage` (D.4: "build toolbox", "build vibe",
 *  "check addon:browser", "switch"): `name` names an agent program. Null: none said. */
export function stageWords(stage: string | null | undefined, name: (harness: string) => string): string | null {
  if (!stage) return null;
  if (stage === "switch") return "Switching to the new images";
  const [verb, ...rest] = stage.split(" ");
  const what = rest.join(" ");
  const doing = { build: "Building", update: "Updating", check: "Checking" }[verb ?? ""];
  if (!doing || !what) return null;
  const thing = what === "toolbox" || what === "network filter" ? `the ${what}` : what.startsWith(ADDON) ? `the ${what.slice(ADDON.length)} tool` : name(what);
  return `${doing} ${thing}`;
}

/** A running build's progress in its stage, when the runtime reports its steps ("STEP 3/7"):
 *  "step 3 of 7" and how far, 0–1. Null: not reported (a check, the switch). */
export function progress(build: Pick<Build, "state" | "step" | "steps">): { text: string; done: number } | null {
  if (build.state !== "running" || !build.step || !build.steps) return null;
  return { text: `step ${build.step} of ${build.steps}`, done: Math.min(1, build.step / build.steps) };
}
