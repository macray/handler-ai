// What the install holds, for the menu and the pages empty for want of a model (lib/menu.ts,
// emptyFor: a model ready) and those that grow with it: the apps installed, what the sources offer (D.26). Read
// again on each page change (installed, added or removed elsewhere) and shared: the menu, and
// Settings for its Voice section.
import { api } from "./api";
import { appTitles } from "./apps";

class MenuUseStore {
  apps = $state(0); // how many are installed
  titles = $state<Record<string, string>>({}); // what each app is called (H.1), by its name
  offered = $state(0);
  modelReady = $state(false); // an account or a provider ready to use
  modelKnown = $state(false); // modelReady read once

  load(): void {
    api.apps().then(
      (list) => ((this.apps = list.length), (this.titles = appTitles(list))),
      () => (this.apps = 0),
    );
    api.sources().then(
      (list) => (this.offered = list.reduce((n, s) => n + (s.items?.length ?? 0), 0)),
      () => (this.offered = 0),
    );
    this.loadModel();
  }

  /** A model ready: read again alone (a page saying "Connect a model first", while a login ends). */
  loadModel(): void {
    Promise.all([api.accounts(), api.providers()]).then(
      ([a, p]) => ((this.modelReady = [...a, ...p].some((x) => x.status === "ready")), (this.modelKnown = true)),
      () => {},
    );
  }

  /** Something to ask, chat with, or discover: an app installed, or something a source offers. */
  /** What the app of that name is called: its title, else its name. */
  title(name: string): string {
    return this.titles[name] ?? name;
  }

  get offers(): boolean {
    return this.apps > 0 || this.offered > 0;
  }
}

export const menuUse = new MenuUseStore();
