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
