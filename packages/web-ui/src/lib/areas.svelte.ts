// Areas (D.19): Work, Personal, a client. A project has at most one; an account or a
// provider says which it may be used in (or `any`). The rule, as handlerd applies it: a project with
// an area runs only the accounts and providers made for it; without one, any. Loaded once and
// shared: the sidebar, the project pages and the model choice show an area's colour.
import { api } from "./api";
import type { AreaInfo, AreaRequest } from "./contracts.gen";

export const ANY = "any";
export const COLORS: AreaRequest["color"][] = ["blue", "violet", "cyan", "pink", "slate"];

class Areas {
  list = $state<AreaInfo[]>([]);
  error = $state<string | null>(null);

  async load(): Promise<void> {
    try {
      this.list = await api.areas();
      this.error = null;
    } catch (e) {
      this.error = (e as Error).message;
    }
  }

  /** The class giving its colour to `area-icon` and `area-tag` inside it; "" for none. */
  colorClass(name: string | null | undefined): string {
    const found = this.list.find((c) => c.name === name);
    return found ? `area-${found.color}` : "";
  }
}

export const areas = new Areas();

/** Whether an account or a provider made for `madeFor` may run in a project of `area`. */
export function allows(area: string | null | undefined, madeFor: string[] | undefined): boolean {
  return !area || (madeFor ?? []).includes(ANY) || (madeFor ?? []).includes(area);
}
