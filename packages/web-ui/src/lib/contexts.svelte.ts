// Project contexts (D.19): Work, Personal, a client. A project has at most one; an account or a
// provider says which it may be used in (or `any`). The rule, as handlerd applies it: a project with
// a context runs only the accounts and providers made for it; without one, any. Loaded once and
// shared: the sidebar, the project pages and the model choice show a context's colour.
import { api } from "./api";
import type { ContextInfo, ContextRequest } from "./contracts.gen";

export const ANY = "any";
export const COLORS: ContextRequest["color"][] = ["blue", "violet", "cyan", "pink", "slate"];

class Contexts {
  list = $state<ContextInfo[]>([]);
  error = $state<string | null>(null);

  async load(): Promise<void> {
    try {
      this.list = await api.contexts();
      this.error = null;
    } catch (e) {
      this.error = (e as Error).message;
    }
  }

  /** The class giving its colour to `ctx-icon` and `ctx-tag` inside it; "" for none. */
  colorClass(name: string | null | undefined): string {
    const found = this.list.find((c) => c.name === name);
    return found ? `ctx-${found.color}` : "";
  }
}

export const contexts = new Contexts();

/** Whether an account or a provider made for `madeFor` may run in a project of `context`. */
export function allows(context: string | null | undefined, madeFor: string[] | undefined): boolean {
  return !context || (madeFor ?? []).includes(ANY) || (madeFor ?? []).includes(context);
}
