// What the install holds, for the menu (lib/menu.ts, menuShows: a model ready) and the pages that
// grow with it: the apps installed, what the sources offer (D.26). Read
// again on each page change (installed, added or removed elsewhere) and shared: the menu, and
// Settings for its Voice section.
import { api } from "./api";

class MenuUseStore {
  apps = $state(0); // how many are installed
  offered = $state(0);
  modelReady = $state(false); // an account or a provider ready to use

  load(): void {
    api.apps().then(
      (list) => (this.apps = list.length),
      () => (this.apps = 0),
    );
    api.sources().then(
      (list) => (this.offered = list.reduce((n, s) => n + (s.items?.length ?? 0), 0)),
      () => (this.offered = 0),
    );
    Promise.all([api.accounts(), api.providers()]).then(
      ([a, p]) => (this.modelReady = [...a, ...p].some((x) => x.status === "ready")),
      () => {},
    );
  }

  /** Something to ask, chat with, or discover: an app installed, or something a source offers. */
  get offers(): boolean {
    return this.apps > 0 || this.offered > 0;
  }
}

export const menuUse = new MenuUseStore();
