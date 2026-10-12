// The harnesses handlerd knows (contract B), asked once per page load: their product names for every
// label ("Claude Code", never `claude-code`, docs/dev/ui-ux.md) and their session modes.
import { api } from "./api";
import type { HarnessInfo } from "./contracts.gen";

class Harnesses {
  list = $state<HarnessInfo[]>([]);
  private loading: Promise<HarnessInfo[]> | null = null;

  load(): Promise<HarnessInfo[]> {
    this.loading ??= api.harnesses().then(
      (list) => (this.list = list),
      () => {
        this.loading = null;
        return [];
      },
    );
    return this.loading;
  }

  /** Its product name; its name until the list is there. */
  product(name: string): string {
    return this.list.find((h) => h.name === name)?.product ?? name;
  }
}

export const harnesses = new Harnesses();

/** A harness's product name ("Claude Code"), for labels. */
export function productName(name: string): string {
  return harnesses.product(name);
}
