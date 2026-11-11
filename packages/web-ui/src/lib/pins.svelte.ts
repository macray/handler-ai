// The menu's Pinned (D.28): projects and apps mixed, in the person's order, kept by handlerd so
// every browser shows the same. Pin, unpin and reorder send the whole list; the menu shows the
// change at once. Refused (this list was old: a project deleted elsewhere), the change is made
// again on handlerd's list; refused again, the menu goes back to it.
import { api } from "./api";
import type { Pin } from "./contracts.gen";
import { moved } from "./menu";

const same = (a: Pin, kind: Pin["kind"], id: string) => a.kind === kind && a.id === id;

class PinStore {
  items = $state<Pin[]>([]);
  error = $state<string | null>(null);
  // the changes made here: a list asked for before one is older than it, asked for again
  private changes = 0;

  async load(): Promise<void> {
    const before = this.changes;
    try {
      const items = (await api.pins()).items;
      if (before !== this.changes) return this.load();
      this.items = items;
    } catch {
      /* the daemon is away: the menu keeps what it showed */
    }
  }

  has(kind: Pin["kind"], id: string): boolean {
    return this.items.some((p) => same(p, kind, id));
  }

  pin(kind: Pin["kind"], id: string): Promise<void> {
    return this.change((items) => (items.some((p) => same(p, kind, id)) ? items : [...items, { kind, id }]));
  }

  unpin(kind: Pin["kind"], id: string): Promise<void> {
    return this.change((items) => items.filter((p) => !same(p, kind, id)));
  }

  toggle(kind: Pin["kind"], id: string): Promise<void> {
    return this.has(kind, id) ? this.unpin(kind, id) : this.pin(kind, id);
  }

  move(from: number, to: number): Promise<void> {
    const pin = this.items[from];
    const target = this.items[to];
    if (!pin || !target) return Promise.resolve();
    // by what is moved and where, so it applies to handlerd's list too
    return this.change((items) => {
      const at = (p: Pin) => items.findIndex((x) => same(x, p.kind, p.id));
      return moved(items, at(pin), at(target));
    });
  }

  private async change(make: (items: Pin[]) => Pin[]): Promise<void> {
    const before = this.items;
    this.changes++;
    this.items = make(before);
    this.error = null;
    try {
      this.items = (await api.setPins({ items: this.items })).items;
      return;
    } catch {
      /* this list was old: made again on handlerd's */
    }
    try {
      const fresh = (await api.pins()).items;
      this.items = make(fresh);
      this.items = (await api.setPins({ items: this.items })).items;
    } catch (e) {
      this.items = before;
      this.error = (e as Error).message;
      void this.load();
      throw e;
    }
  }
}

export const pins = new PinStore();
