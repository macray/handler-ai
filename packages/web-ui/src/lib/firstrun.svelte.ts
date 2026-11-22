// Setting Handler up (E1): three steps, connect a model, say where your code is, your first
// project. Shown large on the empty Projects page (the landing) and, on every other page, in the
// menu's Set up Handler card, until the first project exists; then gone for good. Nothing is
// stored: what is done is read from the accounts, the providers, the work folders and the projects.
import { api } from "./api";
import type { AccountInfo, ProviderInfo, WorkFolderInfo } from "./contracts.gen";
import { notReached } from "./providers";

export type StepId = "model" | "folders" | "project";

/** What the steps are read from. */
export type SetupFacts = {
  ready: string[]; // accounts and providers ready to use (logged in, key set, reached)
  unready: number; // those there are but cannot be used yet (not logged in, no key, not reached)
  unreached: string[]; // providers on this computer whose last test failed
  roots: string[]; // the work folders, as written
  existing: string[]; // those of them that exist
};

/** Where the set-up is: each step done or not, the next one, how many are done. */
export type Setup = { model: boolean; folders: boolean; next: StepId; done: number; total: number };

/** Each step's name, as the steps and the card's "Next: …" say it. */
export const STEP_NAMES: Record<StepId, string> = {
  model: "Connect a model",
  folders: "Say where your code is",
  project: "Your first project",
};

/** The facts, from what handlerd lists. */
export function setupFacts(accounts: AccountInfo[], providers: ProviderInfo[], folders: WorkFolderInfo[]): SetupFacts {
  const unreached = providers.filter(notReached).map((p) => p.name);
  const all = [...accounts, ...providers];
  return {
    ready: all.filter((x) => x.status === "ready" && !unreached.includes(x.name)).map((x) => x.name),
    unready: all.filter((x) => x.status === "incomplete").length + unreached.length,
    unreached,
    roots: folders.map((f) => f.root),
    existing: folders.filter((f) => f.exists).map((f) => f.root),
  };
}

/** The steps: a model ready, a work folder that exists; the first not done is the next (the
 *  project, the last, is never done while the steps show). */
export function setupOf(f: SetupFacts): Setup {
  const model = f.ready.length > 0;
  const folders = f.existing.length > 0;
  return { model, folders, next: !model ? "model" : !folders ? "folders" : "project", done: Number(model) + Number(folders), total: 3 };
}

/** Whether the menu shows the Set up Handler card: once the projects and the facts are read,
 *  while there is no project, but not on Projects, which shows the steps large then. */
export function showsCard(projectsLoaded: boolean, projectCount: number, factsLoaded: boolean, view: string): boolean {
  return projectsLoaded && factsLoaded && projectCount === 0 && view !== "projects";
}

class FirstRun {
  facts = $state<SetupFacts | null>(null); // null: not read yet
  error = $state<string | null>(null);
  private asked = 0; // the reads asked for: an answer to one asked before the last is dropped

  /** Read again: on a page change, once a model is connected or a folder added. */
  load(): void {
    const mine = ++this.asked;
    Promise.all([api.accounts(), api.providers(), api.folders()]).then(
      ([a, p, f]) => {
        if (mine === this.asked) [this.facts, this.error] = [setupFacts(a, p, f.folders), null];
      },
      (e: Error) => {
        if (mine === this.asked) this.error = e.message;
      },
    );
  }

  get setup(): Setup | null {
    return this.facts && setupOf(this.facts);
  }
}

export const firstRun = new FirstRun();
